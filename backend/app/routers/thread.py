"""The teacher's whole interface: one thread with the class agent, one card on
screen rebuilt from records on every read, and buttons for everything that
changes state - which the teacher may also ask the agent for in words.
"""

import re
import unicodedata
import uuid
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update

from app.agent import approaches, classroom, store, student_mode, thread
from app.agent.brief import LessonBrief
from app.agent.llm import LLMClient, LLMError, get_llm_client
from app.agent.materials import UnsupportedMaterial, extract
from app.agent.policy import PolicyRules
from app.auth import CurrentTeacher, DbSession, teacher_session
from app.config import get_settings
from app.enums import (
    Audience,
    ContractStatus,
    EvidenceKind,
    ExceptionStatus,
    LeakageCheck,
    MessageRole,
    ScoreStatus,
    SessionStatus,
    TeacherAction,
    ValidationOutcome,
)
from app.events import broker
from app.ledger import append
from app.lifecycle import close_expired
from app.models import (
    AgentTurn,
    Class,
    Exception_,
    LessonContract,
    LessonOutcome,
    Material,
    Message,
    Session,
    SessionParticipant,
    TeacherAccessLog,
    User,
)
from app.routers import learn as learn_router
from app.routers import lessons as lessons_router
from app.routers import teacher as teacher_router

router = APIRouter(prefix="/api/teacher/thread", tags=["thread"])

Agent = Annotated[LLMClient, Depends(get_llm_client)]

# How far back the thread is returned.
WINDOW = 60


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    text: str
    material_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class FocusOut(BaseModel):
    """The lesson the next thing the teacher says will change."""

    lesson_id: uuid.UUID
    title: str
    status: str


class ThreadOut(BaseModel):
    messages: list[MessageOut]
    strip: list[dict]
    lessons: int
    focus: FocusOut | None = None
    # The one card on screen, built from records every time.
    showing: dict | None = None


def _log(db, teacher: User, action: TeacherAction, session_id=None, student_id=None, detail=None):
    db.add(
        TeacherAccessLog(
            teacher_id=teacher.id,
            session_id=session_id,
            student_id=student_id,
            action=action.value,
            detail=detail or {},
        )
    )


async def _thread(db, teacher: User, showing: dict | None = None) -> ThreadOut:
    """The conversation and the one card on screen: `showing`, or what was last shown."""
    await close_expired(db)
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    rows = await store.messages(db, conversation.id, limit=WINDOW)
    focus = await thread.focus_of(db, conversation, teacher)
    if showing is None:
        showing = conversation.showing
    if showing is None and focus.lesson is not None and rows:
        showing = {"type": "lesson", "lesson_id": str(focus.lesson.id)}
    card = await thread.build_card(db, teacher, showing)
    conversation.showing = showing if card else None

    out = [
        MessageOut(
            id=m.id,
            role=m.role,
            text=m.text,
            material_ids=[str(x) for x in m.material_ids],
            created_at=m.created_at,
        )
        for m in rows
    ]
    count = await db.scalar(
        select(func.count(func.distinct(LessonContract.plan_id))).where(
            LessonContract.teacher_id == teacher.id, LessonContract.archived_at.is_(None)
        )
    )
    await db.commit()
    return ThreadOut(
        messages=out,
        strip=await thread.strip(db, teacher),
        lessons=count or 0,
        showing=card,
        focus=(
            FocusOut(
                lesson_id=focus.lesson.id,
                title=LessonBrief.model_validate(focus.lesson.brief or {}).title
                or focus.lesson.title,
                status=focus.lesson.status,
            )
            if focus.lesson is not None
            else None
        ),
    )


@router.get("", response_model=ThreadOut)
async def read_thread(teacher: CurrentTeacher, db: DbSession) -> ThreadOut:
    return await _thread(db, teacher)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    material_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)

    @field_validator("text")
    @classmethod
    def _said_something(cls, value: str) -> str:
        # The database can't store a NUL character, and nobody means to type one.
        value = value.replace("\x00", "")
        if not value.strip():
            raise ValueError("Write something to the agent.")
        return value


@router.post("/messages", response_model=ThreadOut)
async def say(body: MessageIn, teacher: CurrentTeacher, db: DbSession, agent: Agent) -> ThreadOut:
    """Say something to the agent; every kind of request is this one endpoint."""
    known = set(
        (
            await db.scalars(
                select(Material.id).where(
                    Material.teacher_id == teacher.id, Material.id.in_(body.material_ids)
                )
            )
        ).all()
    )
    try:
        reply = await thread.respond(
            db,
            agent,
            teacher=teacher,
            text=body.text.strip(),
            material_ids=[m for m in body.material_ids if m in known],
        )
    except thread.ThreadUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"The agent couldn't answer just now. Your message is saved; try again. ({exc})",
        ) from exc
    # What the agent chose to show, or what doing as it was asked put there; with
    # nothing chosen the card already up stays.
    return await _thread(db, teacher, await _as_asked(db, teacher, agent, reply))


_DOING = {
    "approve": "approve it",
    "run": "start it",
    "pause": "pause it",
    "resume": "resume it",
    "end": "end it",
}


async def _as_asked(db, teacher: User, agent, reply: Message) -> dict | None:
    """Do what the teacher asked for in words, in order, through the buttons' own
    handlers. The first that can't be done is said in the thread and the rest are left."""
    card = reply.data.get("card")
    for action in reply.data.get("do", []):
        try:
            body = await _button(db, teacher, action, reply.data.get("class_ref"))
            if body is not None:
                card = await _HANDLERS[action](db, teacher, body, agent)
        except HTTPException as exc:
            await thread.event(db, teacher, text=f"Couldn't {_DOING[action]}: {exc.detail}")
            await db.commit()
            break
    if reply.data.get("guide"):
        try:
            card = await _guide(
                db, teacher, await _guide_button(db, teacher, reply.data["guide"]), agent
            )
        except HTTPException as exc:
            await thread.event(db, teacher, text=f"Couldn't pass that on: {exc.detail}")
            await db.commit()
    return card


async def _guide_button(db, teacher: User, guide: dict) -> "ActionIn":
    """The Guide press for the student the teacher named, in the lesson running now."""
    focus = await _current_focus(db, teacher)
    session = focus.session
    if session is None or session.status == SessionStatus.CLOSED.value:
        session = await db.scalar(
            select(Session)
            .join(Class, Class.id == Session.class_id)
            .where(
                Class.teacher_id == teacher.id,
                Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            )
            .order_by(Session.created_at.desc())
        )
    if session is None:
        raise HTTPException(status_code=409, detail="No lesson is running.")
    wanted = guide["student_ref"].strip().lower()
    students = (await classroom.pulse(db, session)).students
    named = [s for s in students if s.pseudonym.lower() == wanted]
    if len(named) != 1:
        raise HTTPException(status_code=422, detail=f"{guide['student_ref']} isn't in this lesson.")
    return ActionIn(
        action="guide", session_id=session.id, student_id=named[0].student_id, text=guide["text"]
    )


async def _button(db, teacher: User, action: str, class_ref: str | None) -> "ActionIn | None":
    """The button press that matches what was asked; None when it is already so."""
    focus = await _current_focus(db, teacher)
    if action in ("approve", "run"):
        lesson = focus.lesson
        if lesson is None:
            raise HTTPException(status_code=422, detail="Say which lesson you mean.")
        if action == "approve":
            # "Approve it and start it" about an approved lesson is only the start.
            if lesson.status != ContractStatus.DRAFT.value:
                return None
            return ActionIn(action="approve", lesson_id=lesson.id)
        classes = (
            await db.scalars(
                select(Class).where(Class.teacher_id == teacher.id).order_by(Class.label)
            )
        ).all()
        wanted = (class_ref or "").strip().lower()
        named = [k for k in classes if k.label.lower() == wanted]
        if len(named) != 1 and len(classes) != 1:
            labels = ", ".join(k.label for k in classes) or "you have none yet"
            raise HTTPException(status_code=422, detail=f"Say which class: {labels}.")
        return ActionIn(action="run", lesson_id=lesson.id, class_id=(named or classes)[0].id)

    session = focus.session
    if session is None or session.status == SessionStatus.CLOSED.value:
        session = await db.scalar(
            select(Session)
            .join(Class, Class.id == Session.class_id)
            .where(
                Class.teacher_id == teacher.id,
                Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            )
            .order_by(Session.created_at.desc())
        )
    if session is None:
        raise HTTPException(status_code=409, detail="No lesson is running.")
    return ActionIn(action=action, session_id=session.id)


# ---------- materials ----------


async def _current_focus(db, teacher: User) -> thread.Focus:
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    return await thread.focus_of(db, conversation, teacher)


async def _owned_lesson(db, teacher: User, lesson_id: uuid.UUID) -> LessonContract:
    lesson = await db.get(LessonContract, lesson_id)
    if lesson is None or lesson.teacher_id != teacher.id or lesson.archived_at is not None:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    return lesson


async def _versions(db, plan_id: uuid.UUID) -> list[LessonContract]:
    return list(
        (
            await db.scalars(
                select(LessonContract)
                .where(LessonContract.plan_id == plan_id)
                .order_by(LessonContract.version)
            )
        ).all()
    )


@router.post("/materials", response_model=ThreadOut, status_code=status.HTTP_201_CREATED)
async def attach(
    teacher: CurrentTeacher,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    lesson_id: Annotated[uuid.UUID | None, Form()] = None,
) -> ThreadOut:
    """Attach a file to the lesson being worked on, or to a new one if there is none."""
    limit = get_settings().material_max_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            status_code=413, detail=f"That file is over {get_settings().material_max_mb} MB."
        )
    try:
        extracted = extract(file.filename or "upload", file.content_type, content)
    except UnsupportedMaterial as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    if lesson_id is not None:
        lesson = await _owned_lesson(db, teacher, lesson_id)
    else:
        lesson = (await _current_focus(db, teacher)).lesson
    if lesson is None:
        lesson = thread.new_lesson(db, teacher)
        await db.flush()

    material = Material(
        teacher_id=teacher.id,
        plan_id=lesson.plan_id,
        filename=(file.filename or "upload")[:255],
        media_type=extracted.media_type,
        size_bytes=len(content),
        content=content,
        extracted_text=extracted.text,
    )
    db.add(material)
    await db.flush()
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    await store.add_message(
        db,
        conversation,
        role=MessageRole.EVENT,
        text=f"Attached {material.filename}",
        material_ids=[str(material.id)],
        data={
            "lesson_id": str(lesson.id),
            "material": {
                "id": str(material.id),
                "filename": material.filename,
                "readable": bool(material.extracted_text) or extracted.is_image,
            },
        },
    )
    await db.commit()
    return await _thread(db, teacher, {"type": "lesson", "lesson_id": str(lesson.id)})


# ---------- buttons ----------


class ActionIn(BaseModel):
    """A button on a card. Everything that changes state comes through here."""

    action: Literal[
        "show_lesson",
        "show_lessons",
        "show_class",
        "show_student",
        "show_transcript",
        "show_outcomes",
        "focus_lesson",
        "new_lesson",
        "follow_up",
        "clear",
        "approve",
        "run",
        "pause",
        "resume",
        "end",
        "suggest_outcomes",
        "confirm_outcome",
        "acknowledge",
        "guide",
        "delete_material",
        "delete_lesson",
        "set_unit",
        "set_approach",
        "start_approach",
        "copy_with_approach",
        "preview_lesson",
    ]
    lesson_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    student_id: uuid.UUID | None = None
    class_id: uuid.UUID | None = None
    outcome_id: uuid.UUID | None = None
    exception_id: uuid.UUID | None = None
    material_id: uuid.UUID | None = None
    text: str = Field(default="", max_length=1000)
    show_to_student: bool = False
    points: dict[str, int] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("text", "comment")
    @classmethod
    def _no_nul(cls, value: str | None) -> str | None:
        return value.replace("\x00", "") if isinstance(value, str) else value


def _need(value, what: str):
    if value is None:
        raise HTTPException(status_code=422, detail=f"{what} is needed for that.")
    return value


@router.get("/lessons", response_model=dict)
async def lessons(teacher: CurrentTeacher, db: DbSession) -> dict:
    """Every lesson, for the picker. Nothing is written to the thread."""
    return await thread.lessons_card(db, teacher)


@router.post("/actions", response_model=ThreadOut)
async def act(body: ActionIn, teacher: CurrentTeacher, db: DbSession, agent: Agent) -> ThreadOut:
    handler = _HANDLERS[body.action]
    return await _thread(db, teacher, await handler(db, teacher, body, agent))


async def _mark(db, teacher, *, lesson_id=None, session_id=None):
    """A blank event saying what the teacher turned to, only when it changes."""
    focus = await _current_focus(db, teacher)
    same_lesson = lesson_id and focus.lesson is not None and str(focus.lesson.id) == lesson_id
    same_session = session_id and focus.session is not None and str(focus.session.id) == session_id
    if same_lesson or same_session:
        return
    await thread.event(db, teacher, text="", lesson_id=lesson_id, session_id=session_id)


async def _show_lesson(db, teacher, body, agent):
    lesson = await _owned_lesson(db, teacher, _need(body.lesson_id, "A lesson"))
    await _mark(db, teacher, lesson_id=str(lesson.id))
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def _show_lessons(db, teacher, body, agent):
    return {"type": "lessons"}


async def _show_class(db, teacher, body, agent):
    session = await teacher_session(_need(body.session_id, "A lesson"), teacher, db)
    _log(db, teacher, TeacherAction.REVIEW_STUDENT, session.id, detail={"view": "class"})
    await _mark(db, teacher, session_id=str(session.id))
    await db.commit()
    return {"type": "class", "session_id": str(session.id)}


async def _student_in(db, session: Session, student_id: uuid.UUID) -> User:
    admitted = await db.scalar(
        select(SessionParticipant.id).where(
            SessionParticipant.session_id == session.id,
            SessionParticipant.student_id == student_id,
        )
    )
    student = await db.get(User, student_id)
    if admitted is None or student is None:
        raise HTTPException(status_code=404, detail="Student not in this lesson.")
    return student


async def _show_student(db, teacher, body, agent):
    session = await teacher_session(_need(body.session_id, "A lesson"), teacher, db)
    student = await _student_in(db, session, _need(body.student_id, "A student"))
    _log(db, teacher, TeacherAction.REVIEW_STUDENT, session.id, student.id)
    await db.commit()
    return {
        "type": "student",
        "session_id": str(session.id),
        "student_id": str(student.id),
    }


async def _show_transcript(db, teacher, body, agent):
    """Reading a student's transcript is deliberate, and logged as such."""
    session = await teacher_session(_need(body.session_id, "A lesson"), teacher, db)
    student = await _student_in(db, session, _need(body.student_id, "A student"))
    _log(db, teacher, TeacherAction.TRANSCRIPT_DRILLDOWN, session.id, student.id)
    await db.commit()
    return {
        "type": "student",
        "session_id": str(session.id),
        "student_id": str(student.id),
        "conversation": True,
    }


async def _show_outcomes(db, teacher, body, agent):
    session = await teacher_session(_need(body.session_id, "A lesson"), teacher, db)
    return {"type": "outcomes", "session_id": str(session.id)}


async def _delete_material(db, teacher, body, agent):
    """Take a file back off the agent; the lesson card simply loses it."""
    material = await db.get(Material, _need(body.material_id, "A file"))
    if material is None or material.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="File not found.")
    plan = material.plan_id
    await db.delete(material)
    await db.commit()
    lesson = await db.scalar(
        select(LessonContract)
        .where(LessonContract.plan_id == plan, LessonContract.archived_at.is_(None))
        .order_by(LessonContract.version.desc())
    )
    return {"type": "lesson", "lesson_id": str(lesson.id)} if lesson else None


async def _follow_up(db, teacher, body, agent):
    """A shared difficulty becomes a request for a new lesson, drafted like any other."""
    note = body.text.strip()
    if not note:
        raise HTTPException(status_code=422, detail="Say which difficulty to follow up.")
    try:
        reply = await thread.respond(
            db,
            agent,
            teacher=teacher,
            text=(
                "Several students share a difficulty. Draft a new lesson, a short "
                f"follow-up activity about {note}."
            ),
            force_new=True,
        )
    except thread.ThreadUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="The agent couldn't draft it just now."
        ) from exc
    return reply.data.get("card")


async def _clear(db, teacher, body, agent):
    """Delete the talk; lessons, evidence and the audit trail stay."""
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    await db.execute(delete(Message).where(Message.conversation_id == conversation.id))
    conversation.showing = None
    await db.commit()
    return None


async def _new_lesson(db, teacher, body, agent):
    """Clear the focus and the card, so the next thing said starts a new lesson."""
    await thread.event(db, teacher, text="", clears_focus=True)
    (await store.teacher_thread(db, teacher_id=teacher.id)).showing = None
    await db.commit()
    return None


async def _preview_lesson(db, teacher, body, agent):
    """How step 1 would open for a student, from the draft as it stands, written into the
    thread. Nothing reaches any student; one model call."""
    lesson = await _owned_lesson(db, teacher, _need(body.lesson_id, "A lesson"))
    brief = LessonBrief.model_validate(lesson.brief or {})
    if not brief.steps:
        raise HTTPException(status_code=422, detail="Give the lesson a first step to preview.")
    try:
        out, result = await student_mode.preview_opening(
            agent, brief=brief, approach=lesson.approach
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=f"No preview this time: {exc}") from exc
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    db.add(
        AgentTurn(
            conversation_id=conversation.id,
            mode="preview",
            context_manifest={"mode": "preview", "lesson_id": str(lesson.id)},
            policy_version=student_mode.POLICY_VERSION,
            prompt_version=student_mode.prompt_version(),
            provider=result.provider,
            model=result.model,
            latency_ms=result.latency_ms,
            validation_outcome=ValidationOutcome.OK.value,
            leakage_check=LeakageCheck.SKIPPED.value,
            conflicts=[],
            request={"preview": True},
            response={"raw": result.raw[:6000]},
        )
    )
    await thread.event(
        db,
        teacher,
        text=f"How step 1 would open for a student, as the lesson stands:\n\n{out.message}",
        lesson_id=str(lesson.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def _approve(db, teacher, body, agent):
    """Record the teacher's approval; only now can the agent teach from this brief."""
    lesson = await _owned_lesson(db, teacher, _need(body.lesson_id, "A lesson"))
    if lesson.status != ContractStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail="This version is already approved.")
    brief = LessonBrief.model_validate(lesson.brief or {})
    if brief.missing():
        raise HTTPException(
            status_code=422,
            detail="Before approving, the lesson needs " + ", ".join(brief.missing()) + ".",
        )
    await db.execute(
        update(LessonContract)
        .where(
            LessonContract.plan_id == lesson.plan_id,
            LessonContract.id != lesson.id,
            LessonContract.status == ContractStatus.ACTIVE.value,
        )
        .values(status=ContractStatus.CLOSED.value)
    )
    lesson.status = ContractStatus.ACTIVE.value
    lesson.activated_at = datetime.now(UTC)
    lesson.activated_by = teacher.id
    lesson.title = brief.title.strip()[:255] or lesson.title
    lesson.subject = brief.subject.strip()[:64] or lesson.subject
    if brief.to_check:
        # Approval is the teacher confirming everything the agent filled in.
        brief.to_check = []
        lesson.brief = brief.model_dump(mode="json")
    running_older = await db.scalar(
        select(func.count(Session.id))
        .join(LessonContract, LessonContract.id == Session.contract_id)
        .where(
            LessonContract.plan_id == lesson.plan_id,
            Session.contract_id != lesson.id,
            Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
        )
    )
    await thread.event(
        db,
        teacher,
        text=(
            f"Approved “{lesson.title}”. The class running now keeps the earlier version; the "
            "next start uses this one."
            if running_older
            else f"Approved “{lesson.title}”. The agent will teach it exactly as it stands."
        ),
        lesson_id=str(lesson.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def _run(db, teacher, body, agent):
    """Start the lesson with a class now; one at a time, even when Start is pressed twice."""
    if teacher.id in _starting:
        raise HTTPException(status_code=409, detail="Already starting a lesson. Give it a moment.")
    _starting.add(teacher.id)
    try:
        return await _start(db, teacher, body)
    finally:
        _starting.discard(teacher.id)


# shortcut: one API process, so an in-memory set serialises Start per teacher; use a database
# lock if the API ever runs as several processes.
_starting: set[uuid.UUID] = set()


async def _start(db, teacher, body):
    lesson = await _owned_lesson(db, teacher, _need(body.lesson_id, "A lesson"))
    if lesson.status != ContractStatus.ACTIVE.value:
        approved = next(
            (
                v
                for v in reversed(await _versions(db, lesson.plan_id))
                if v.status == ContractStatus.ACTIVE.value
            ),
            None,
        )
        if approved is None:
            raise HTTPException(status_code=409, detail="Approve the lesson before running it.")
        lesson = approved
    klass = await db.get(Class, _need(body.class_id, "A class"))
    if klass is None or klass.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="Class not found.")
    # A teacher runs one lesson at a time.
    running = (
        await db.execute(
            select(Session, Class)
            .join(Class, Class.id == Session.class_id)
            .where(
                Class.teacher_id == teacher.id,
                Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            )
        )
    ).first()
    if running is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"You already have a lesson running with {running[1].label}. End that one first."
            ),
        )
    booked = await lessons_router.book_lesson(
        lessons_router.LessonIn(plan_version_id=lesson.id, class_id=klass.id), teacher, db
    )
    started = await lessons_router.start_lesson(booked.lesson_id, teacher, db)
    await thread.event(
        db,
        teacher,
        text=(
            f"Started with {klass.label}: {started.students} "
            f"student{'s' if started.students != 1 else ''}, {started.steps} "
            f"step{'s' if started.steps != 1 else ''}."
        ),
        session_id=str(started.lesson_id),
    )
    await db.commit()
    return {"type": "class", "session_id": str(started.lesson_id)}


async def _state(db, teacher, body, agent, *, to: SessionStatus, said: str):
    """Pause, resume or end; `said` is the event line, with {title}, or blank for a mark."""
    session = await teacher_session(_need(body.session_id, "A lesson"), teacher, db)
    await teacher_router.set_state(session.id, to, teacher, db)
    if said:
        contract = await db.get(LessonContract, session.contract_id)
        title = contract.title if contract else "the lesson"
        text = said.format(title=title)
        if to is SessionStatus.CLOSED:
            text += await _still_open(db, session.id)
        await thread.event(db, teacher, text=text, session_id=str(session.id))
    else:
        await _mark(db, teacher, session_id=str(session.id))
    await db.commit()
    return (
        {"type": "outcomes", "session_id": str(session.id)}
        if to is SessionStatus.CLOSED
        else {"type": "class", "session_id": str(session.id)}
    )


async def _still_open(db, session_id) -> str:
    """A sentence on the alerts still open in a lesson that has just ended, or nothing."""
    kinds = (
        await db.scalars(
            select(Exception_.kind).where(
                Exception_.session_id == session_id,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
    ).all()
    if not kinds:
        return ""
    worst = " including a wellbeing concern" if "safeguarding" in kinds else ""
    n = len(kinds)
    return (
        f" {n} alert{'s are' if n != 1 else ' is'} still open{worst}: "
        f"{'they are' if n != 1 else 'it is'} on the outcomes card."
    )


async def _suggest_outcomes(db, teacher, body, agent):
    session = await teacher_session(_need(body.session_id, "A lesson"), teacher, db)
    if session.status != SessionStatus.CLOSED.value:
        raise HTTPException(status_code=409, detail="End the lesson before reviewing outcomes.")
    try:
        suggested = await classroom.suggest_outcomes(db, agent, session=session)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail="The agent couldn't review just now.") from exc
    said = (
        "The summary of the lesson and a note on each student, for you to confirm."
        if suggested
        else "Nothing to sum up for this lesson: no student took part in it."
    )
    await thread.event(db, teacher, text=said, session_id=str(session.id))
    await db.commit()
    return {"type": "outcomes", "session_id": str(session.id)}


async def _confirm_outcome(db, teacher, body, agent):
    """The teacher's decision; their points replace the suggestion where given."""
    session = await teacher_session(_need(body.session_id, "A lesson"), teacher, db)
    outcome = await db.get(LessonOutcome, _need(body.outcome_id, "An outcome"))
    if outcome is None or outcome.session_id != session.id:
        raise HTTPException(status_code=404, detail="Outcome not found.")
    chosen = []
    for c in outcome.suggested.get("criteria", []):
        value = body.points.get(c["name"], c["points"])
        if not 0 <= value <= int(c["max"]):
            raise HTTPException(
                status_code=422, detail=f"{c['name']} must be between 0 and {c['max']}."
            )
        # A reason written for other points is not the reason for these.
        reason = c.get("reason", "") if value == c["points"] else ""
        chosen.append({**c, "points": value, "reason": reason})
    outcome.confirmed = {
        "criteria": chosen,
        "keep": outcome.suggested.get("keep", ""),
        "develop": outcome.suggested.get("develop", []),
    }
    outcome.confirmed_total = sum(c["points"] for c in chosen)
    outcome.comment = body.comment
    outcome.status = ScoreStatus.CONFIRMED.value
    outcome.confirmed_by = teacher.id
    outcome.confirmed_at = datetime.now(UTC)
    _log(
        db,
        teacher,
        TeacherAction.CONFIRM_SCORE,
        session.id,
        outcome.student_id,
        {"suggested": outcome.suggested_total, "confirmed": outcome.confirmed_total},
    )
    left = await db.scalar(
        select(func.count(LessonOutcome.id)).where(
            LessonOutcome.session_id == session.id,
            LessonOutcome.status != ScoreStatus.CONFIRMED.value,
        )
    )
    if not left:
        done = await db.scalar(
            select(func.count(LessonOutcome.id)).where(LessonOutcome.session_id == session.id)
        )
        await thread.event(
            db,
            teacher,
            text=(
                "Confirmed the outcome for 1 student."
                if done == 1
                else f"Confirmed the outcomes for {done} students."
            ),
            session_id=str(session.id),
        )
    await db.commit()
    return {"type": "outcomes", "session_id": str(session.id)}


async def _acknowledge(db, teacher, body, agent):
    """Dealt with: the card on screen stays up, one alert lighter, wherever it was pressed (the
    class board, a student's card, or the outcomes card with marks still being typed)."""
    alert = await db.get(Exception_, _need(body.exception_id, "An alert"))
    session_id = alert.session_id if alert is not None else None
    await teacher_router.acknowledge(body.exception_id, teacher, db)
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    if conversation.showing is None and session_id:
        return {"type": "class", "session_id": str(session_id)}
    # None keeps what was last shown; it is rebuilt from the records, without this alert.
    return None


async def _guide(db, teacher, body, agent):
    """Tell the agent how to teach this student, and the student too if chosen."""
    session = await teacher_session(_need(body.session_id, "A lesson"), teacher, db)
    student = await _student_in(db, session, _need(body.student_id, "A student"))
    if session.status == SessionStatus.CLOSED.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "This lesson has ended, so the agent can't act on that. Your note for this "
                "student goes with their outcome on the outcomes card."
            ),
        )
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Say what the agent should do.")
    await append(
        db,
        session_id=session.id,
        student_id=student.id,
        kind=EvidenceKind.TEACHER_GUIDANCE,
        payload={"text": text, "shown_to_student": body.show_to_student},
        provenance={"source": "teacher", "teacher_id": str(teacher.id)},
    )
    convo = await store.student_conversation(db, session_id=session.id, student_id=student.id)
    await store.add_message(
        db,
        convo,
        role=MessageRole.EVENT,
        audience=Audience.ALL if body.show_to_student else Audience.TEACHER,
        text=(
            f"From your teacher: {text}"
            if body.show_to_student
            else f"Teacher guidance for the agent: {text}"
        ),
    )
    _log(
        db,
        teacher,
        TeacherAction.GUIDE_STUDENT,
        session.id,
        student.id,
        {"shown_to_student": body.show_to_student},
    )
    await db.commit()
    # The agent acts on it now, not whenever the student next happens to write.
    acted = False
    if session.status == SessionStatus.OPEN.value:
        try:
            await learn_router._turn(db, agent, session, student, None, None, guidance=text)
            acted = True
        except HTTPException:
            await db.rollback()
    said = f"Sent {student.pseudonym} your note. " if body.show_to_student else ""
    await thread.event(
        db,
        teacher,
        text=said
        + (
            f"The agent has written to {student.pseudonym} to do as you asked."
            if acted
            else (
                f"The agent will do as you asked once you resume and {student.pseudonym} writes."
                if session.status == SessionStatus.PAUSED.value
                else f"The agent will do as you asked when {student.pseudonym} next writes."
            )
        ),
        session_id=str(session.id),
    )
    await db.commit()
    await broker.publish(session.id, {"type": "guidance", "student": student.pseudonym})
    return {
        "type": "student",
        "session_id": str(session.id),
        "student_id": str(student.id),
    }


async def _delete_lesson(db, teacher, body, agent):
    """A lesson never taught is deleted with its files; one that has been taught is archived.
    Not while one of its classes still has an alert open: that would leave a student who asked
    for the teacher, or was upset, with nobody to see it."""
    lesson = await _owned_lesson(db, teacher, _need(body.lesson_id, "A lesson"))
    versions = await _versions(db, lesson.plan_id)
    ids = [v.id for v in versions]
    waiting = await db.scalar(
        select(func.count(Exception_.id))
        .join(Session, Session.id == Exception_.session_id)
        .where(Session.contract_id.in_(ids), Exception_.status == ExceptionStatus.OPEN.value)
    )
    if waiting:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{waiting} alert{'s' if waiting != 1 else ''} from this lesson still "
                f"need{'' if waiting != 1 else 's'} you. Press Dealt with on "
                f"{'each' if waiting != 1 else 'it'} (on the class or the outcomes card), "
                "then remove the lesson."
            ),
        )
    # A run still going ends with the lesson; nothing should keep running with no lesson behind it.
    live = (
        await db.scalars(
            select(Session).where(
                Session.contract_id.in_(ids),
                Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            )
        )
    ).all()
    ended_for = 0
    for session in live:
        ended_for += (
            await db.scalar(
                select(func.count(SessionParticipant.id)).where(
                    SessionParticipant.session_id == session.id
                )
            )
            or 0
        )
        await teacher_router.set_state(session.id, SessionStatus.CLOSED, teacher, db)
    focus = await _current_focus(db, teacher)
    in_focus = focus.lesson is not None and focus.lesson.plan_id == lesson.plan_id
    taught = await db.scalar(select(func.count(Session.id)).where(Session.contract_id.in_(ids)))
    if taught:
        now = datetime.now(UTC)
        for v in versions:
            v.archived_at = now
    else:
        await db.execute(delete(Material).where(Material.plan_id == lesson.plan_id))
        for v in versions:
            await db.delete(v)
    title = LessonBrief.model_validate(lesson.brief or {}).title or lesson.title
    said = f"Removed “{title}”."
    if live:
        who = f"{ended_for} student{'s' if ended_for != 1 else ''}"
        said += f" It was running, so it has ended for {who}."
    # Removing another lesson from the list leaves the one being worked on in focus.
    await thread.event(db, teacher, text=said, clears_focus=in_focus)
    await db.commit()
    return {"type": "lessons"} if in_focus else None


async def _set_unit(db, teacher, body, agent):
    """Put a lesson in a unit by name, or take it out. Every version of it moves together. A
    name the teacher has used before, in any case, is reused as they first spelled it."""
    lesson = await _owned_lesson(db, teacher, _need(body.lesson_id, "A lesson"))
    # Invisible characters (zero-width spaces and the like) never make a different unit.
    visible = "".join(ch for ch in body.text if unicodedata.category(ch) != "Cf")
    name = " ".join(visible.split())[:80].rstrip() or None
    if name:
        used = (
            await db.scalars(
                select(LessonContract.unit)
                .where(
                    LessonContract.teacher_id == teacher.id,
                    LessonContract.archived_at.is_(None),
                    LessonContract.unit.is_not(None),
                )
                .distinct()
            )
        ).all()
        name = {u.casefold(): u for u in used}.get(name.casefold(), name)
    for v in await _versions(db, lesson.plan_id):
        v.unit = name
    title = LessonBrief.model_validate(lesson.brief or {}).title or lesson.title
    await thread.event(
        db,
        teacher,
        text=f"Put “{title}” in the unit {name}." if name else f"Took “{title}” out of its unit.",
        lesson_id=str(lesson.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def _set_approach(db, teacher, body, agent):
    """Tag a lesson with the teaching approach it is to be taught by, with the rule that goes
    with it, or take the tag off. Like any change to an approved lesson it makes a new version
    to approve: the approved version, a class running now and every run already taught keep
    the approach they had."""
    lesson = await _owned_lesson(db, teacher, _need(body.lesson_id, "A lesson"))
    name = body.text.strip().lower() or None
    if name is not None and name not in approaches.NAMES:
        raise HTTPException(status_code=422, detail="The approach is direct or inquiry.")
    current = await thread.current_version(db, lesson.plan_id) or lesson
    draft = await thread.draft_to_work_on(db, current)
    draft.approach = name
    if name:
        brief = LessonBrief.model_validate(draft.brief or {})
        brief.rules = brief.rules.model_copy(update=approaches.RULES[name])
        brief.rules_text = approaches.rules_text_for(brief.rules_text, name)
        draft.brief = brief.model_dump(mode="json")
    approved = any(
        v.status == ContractStatus.ACTIVE.value for v in await _versions(db, lesson.plan_id)
    )
    title = LessonBrief.model_validate(draft.brief or {}).title or draft.title
    said = (
        f"“{title}” is to be taught by {approaches.NAMES[name]}."
        if name
        else f"Took the teaching approach off “{title}”."
    )
    if approved:
        said += " That is a change: approve it to use it."
    await thread.event(db, teacher, text=said, lesson_id=str(draft.id))
    await db.commit()
    return {"type": "lesson", "lesson_id": str(draft.id)}


async def _start_approach(db, teacher, body, agent):
    """A new lesson to be taught by the chosen approach, with its rule already set. From here
    the agent is told the approach while it drafts, and again on every turn with a student. An
    empty draft from an earlier press is reused rather than piling up."""
    name = body.text.strip().lower()
    if name not in approaches.NAMES:
        raise HTTPException(status_code=422, detail="The approach is direct or inquiry.")
    lesson = await thread.empty_draft_of(db, teacher) or thread.new_lesson(db, teacher)
    lesson.approach = name
    lesson.brief = LessonBrief(
        rules=PolicyRules(**approaches.RULES[name]),
        rules_text=approaches.RULE_WORDS[name],
    ).model_dump(mode="json")
    await db.flush()
    await thread.event(
        db,
        teacher,
        text=(
            f"A new lesson, to be taught by {approaches.NAMES[name]}. Describe it and the agent "
            "builds it that way."
        ),
        lesson_id=str(lesson.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def _copy_with_approach(db, teacher, body, agent):
    """The same lesson again, to be taught by the other approach: identical steps, questions,
    answers, marks and files; only the approach, its rule and the title's ending differ."""
    picked = await _owned_lesson(db, teacher, _need(body.lesson_id, "A lesson"))
    name = body.text.strip().lower()
    if name not in approaches.NAMES:
        raise HTTPException(status_code=422, detail="The approach is direct or inquiry.")
    # The lesson as it stands now, not whichever version the button was pressed on.
    source = await thread.current_version(db, picked.plan_id) or picked
    brief = LessonBrief.model_validate(source.brief or {})
    base = _APPROACH_SUFFIX.sub("", brief.title or source.title).strip()
    suffix = f" ({approaches.NAMES[name]})"
    brief.title = base[: 255 - len(suffix)].rstrip() + suffix
    brief.rules = brief.rules.model_copy(update=approaches.RULES[name])
    brief.rules_text = approaches.rules_text_for(brief.rules_text, name)
    # Checked before it is saved: a copy the platform can't read would break the thread.
    brief = LessonBrief.model_validate(brief.model_dump(mode="json"))
    copy = LessonContract(
        plan_id=uuid.uuid4(),
        teacher_id=teacher.id,
        title=brief.title,
        subject=source.subject,
        status=ContractStatus.DRAFT.value,
        version=1,
        brief=brief.model_dump(mode="json"),
        use_past_lessons=source.use_past_lessons,
        unit=source.unit,
        approach=name,
    )
    db.add(copy)
    await db.flush()
    for m in await thread.materials_of(db, source.plan_id):
        db.add(
            Material(
                teacher_id=teacher.id,
                plan_id=copy.plan_id,
                filename=m.filename,
                media_type=m.media_type,
                size_bytes=m.size_bytes,
                content=m.content,
                extracted_text=m.extracted_text,
            )
        )
    await thread.event(
        db,
        teacher,
        text=(
            f"Made “{brief.title}”: the same steps, questions, marks and files, to be taught by "
            f"{approaches.NAMES[name]}. Approve it when you are ready."
        ),
        lesson_id=str(copy.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(copy.id)}


# The approach a copy's title ends with, in any case, so copying a copy does not stack them.
_APPROACH_SUFFIX = re.compile(r"\s*\((?:direct instruction|guided inquiry)\)\s*$", re.IGNORECASE)


_HANDLERS = {
    "show_lesson": _show_lesson,
    "show_lessons": _show_lessons,
    "show_class": _show_class,
    "show_student": _show_student,
    "show_transcript": _show_transcript,
    "show_outcomes": _show_outcomes,
    "focus_lesson": _show_lesson,
    "new_lesson": _new_lesson,
    "follow_up": _follow_up,
    "clear": _clear,
    "approve": _approve,
    "run": _run,
    "pause": partial(_state, to=SessionStatus.PAUSED, said=""),
    "resume": partial(_state, to=SessionStatus.OPEN, said=""),
    "end": partial(
        _state,
        to=SessionStatus.CLOSED,
        said="Ended “{title}”. Press Write the summary for how the class did and a note on "
        "each student.",
    ),
    "suggest_outcomes": _suggest_outcomes,
    "confirm_outcome": _confirm_outcome,
    "acknowledge": _acknowledge,
    "guide": _guide,
    "delete_material": _delete_material,
    "delete_lesson": _delete_lesson,
    "set_unit": _set_unit,
    "set_approach": _set_approach,
    "start_approach": _start_approach,
    "copy_with_approach": _copy_with_approach,
    "preview_lesson": _preview_lesson,
}
