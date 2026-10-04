"""The teacher's whole interface: one thread with the class agent, one card on
screen rebuilt from records on every read, and buttons for everything that
changes state - which the teacher may also ask the agent for in words.
"""

import uuid
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from app.agent import classroom, store, thread
from app.agent.brief import LessonBrief
from app.agent.llm import LLMClient, LLMError, get_llm_client
from app.agent.materials import UnsupportedMaterial, extract
from app.auth import CurrentTeacher, DbSession, teacher_session
from app.config import get_settings
from app.enums import (
    Audience,
    ContractStatus,
    EvidenceKind,
    MessageRole,
    ScoreStatus,
    SessionStatus,
    TeacherAction,
)
from app.events import broker
from app.ledger import append
from app.lifecycle import close_expired
from app.models import (
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
        select(func.count(LessonContract.id)).where(
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
    return card


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
        "use_past_lessons",
        "delete_material",
        "delete_lesson",
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
    value: bool = False
    points: dict[str, int] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=1000)


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
    await thread.event(
        db,
        teacher,
        text=f"Approved “{lesson.title}”. The agent will teach it exactly as it stands.",
        lesson_id=str(lesson.id),
    )
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def _run(db, teacher, body, agent):
    """Start the lesson with a class now."""
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
        text=f"Started with {klass.label}: {started.students} students, {started.steps} steps.",
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
        await thread.event(db, teacher, text=said.format(title=title), session_id=str(session.id))
    else:
        await _mark(db, teacher, session_id=str(session.id))
    await db.commit()
    return (
        {"type": "outcomes", "session_id": str(session.id)}
        if to is SessionStatus.CLOSED
        else {"type": "class", "session_id": str(session.id)}
    )


async def _suggest_outcomes(db, teacher, body, agent):
    session = await teacher_session(_need(body.session_id, "A lesson"), teacher, db)
    if session.status != SessionStatus.CLOSED.value:
        raise HTTPException(status_code=409, detail="End the lesson before reviewing outcomes.")
    try:
        suggested = await classroom.suggest_outcomes(db, agent, session=session)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail="The agent couldn't review just now.") from exc
    await thread.event(
        db,
        teacher,
        text=(
            "Suggested outcomes, for you to confirm."
            if suggested
            else "Nothing to suggest for this lesson - no student took part in it."
        ),
        session_id=str(session.id),
    )
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
            text=f"Confirmed the outcomes for {done} students.",
            session_id=str(session.id),
        )
    await db.commit()
    return {"type": "outcomes", "session_id": str(session.id)}


async def _acknowledge(db, teacher, body, agent):
    """Dealt with; the class board stays up, one name lighter."""
    alert = await db.get(Exception_, _need(body.exception_id, "An alert"))
    session_id = alert.session_id if alert is not None else None
    await teacher_router.acknowledge(body.exception_id, teacher, db)
    return {"type": "class", "session_id": str(session_id)} if session_id else None


async def _guide(db, teacher, body, agent):
    """Tell the agent how to teach this student, and the student too if chosen."""
    session = await teacher_session(_need(body.session_id, "A lesson"), teacher, db)
    student = await _student_in(db, session, _need(body.student_id, "A student"))
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
    await thread.event(
        db,
        teacher,
        text=(
            f"Sent {student.pseudonym} a note, and told the agent how to work with them."
            if body.show_to_student
            else f"Told the agent how to work with {student.pseudonym}."
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


async def _use_past_lessons(db, teacher, body, agent):
    lesson = await _owned_lesson(db, teacher, _need(body.lesson_id, "A lesson"))
    lesson = await thread.draft_to_work_on(db, lesson)
    lesson.use_past_lessons = body.value
    await db.commit()
    return {"type": "lesson", "lesson_id": str(lesson.id)}


async def _delete_lesson(db, teacher, body, agent):
    """A lesson never taught is deleted; one that has been taught is archived."""
    lesson = await _owned_lesson(db, teacher, _need(body.lesson_id, "A lesson"))
    versions = await _versions(db, lesson.plan_id)
    ids = [v.id for v in versions]
    # A run still going ends with the lesson; nothing should keep running with no lesson behind it.
    live = (
        await db.scalars(
            select(Session).where(
                Session.contract_id.in_(ids),
                Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            )
        )
    ).all()
    for session in live:
        await teacher_router.set_state(session.id, SessionStatus.CLOSED, teacher, db)
    taught = await db.scalar(select(func.count(Session.id)).where(Session.contract_id.in_(ids)))
    if taught:
        now = datetime.now(UTC)
        for v in versions:
            v.archived_at = now
    else:
        for v in versions:
            await db.delete(v)
    await thread.event(db, teacher, text=f"Removed “{lesson.title}”.", clears_focus=True)
    await db.commit()
    return {"type": "lessons"}


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
    "end": partial(_state, to=SessionStatus.CLOSED, said="Ended “{title}”."),
    "suggest_outcomes": _suggest_outcomes,
    "confirm_outcome": _confirm_outcome,
    "acknowledge": _acknowledge,
    "guide": _guide,
    "use_past_lessons": _use_past_lessons,
    "delete_material": _delete_material,
    "delete_lesson": _delete_lesson,
}
