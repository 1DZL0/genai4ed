"""The teacher's whole interface: one thread with the class agent, one card on
screen rebuilt from records on every read, and buttons for everything that
changes state, which the teacher may also ask the agent for in words.

This module holds the routes and the dispatch; the buttons themselves are in
`thread_lessons` (about a lesson) and `thread_class` (about a class in a lesson),
with what they share in `thread_common`.
"""

import uuid
from datetime import datetime
from functools import partial
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select

from app.agent import cards, classroom, lessons, store, thread
from app.agent.brief import LessonBrief
from app.agent.lessons import close_expired
from app.agent.llm import LLMClient, get_llm_client
from app.agent.materials import UnsupportedMaterial, extract
from app.auth import CurrentTeacher, DbSession
from app.config import get_settings
from app.enums import (
    ContractStatus,
    MessageRole,
    SessionStatus,
)
from app.models import (
    Class,
    LessonContract,
    Material,
    Message,
    Session,
    User,
)
from app.routers.thread_class import (
    acknowledge,
    change_state,
    confirm_outcome,
    guide,
    show_class,
    show_outcomes,
    show_student,
    show_transcript,
    suggest_outcomes,
)
from app.routers.thread_common import (
    current_focus,
    owned_lesson,
)
from app.routers.thread_lessons import (
    approve,
    clear_thread,
    copy_with_approach,
    delete_lesson,
    delete_material,
    follow_up,
    preview_lesson,
    run,
    set_approach,
    set_unit,
    show_lesson,
    show_lessons,
    start_approach,
    start_new_lesson,
)

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
    # The rule values the quick choices under the box read back, so the row and the card agree.
    help: dict
    worked_step_after: int
    hints_allowed: bool
    answer_after: int | None
    depth: int


def _focus_out(lesson: LessonContract) -> FocusOut:
    brief = LessonBrief.model_validate(lesson.brief or {})
    rules = brief.rules
    return FocusOut(
        lesson_id=lesson.id,
        title=brief.title or lesson.title,
        status=lesson.status,
        help=rules.labels(),
        worked_step_after=rules.partial_after_attempts,
        hints_allowed=rules.hints_allowed,
        answer_after=rules.full_answer_after_attempts,
        depth=rules.depth,
    )


class ThreadOut(BaseModel):
    messages: list[MessageOut]
    strip: list[dict]
    lessons: int
    focus: FocusOut | None = None
    # The one card on screen, built from records every time.
    showing: dict | None = None


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
    card = await cards.build_card(db, teacher, showing)
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
        strip=await cards.strip(db, teacher),
        lessons=count or 0,
        showing=card,
        focus=_focus_out(focus.lesson) if focus.lesson is not None else None,
    )


@router.get("", response_model=ThreadOut)
async def read_thread(teacher: CurrentTeacher, db: DbSession) -> ThreadOut:
    return await _thread(db, teacher)


class MessageIn(BaseModel):
    text: str = Field(default="", max_length=6000)
    material_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    # What the teacher pressed in the quick choices, as the sentence the panel composes. It
    # travels with the message rather than in it, so the box holds only their own words.
    choices: str = Field(default="", max_length=1500)

    @field_validator("text", "choices")
    @classmethod
    def _storable(cls, value: str) -> str:
        # The database can't store a NUL character, and nobody means to type one.
        return value.replace("\x00", "")

    @model_validator(mode="after")
    def _said_or_pressed_something(self) -> "MessageIn":
        if not self.text.strip() and not self.choices.strip() and not self.material_ids:
            raise ValueError("Write something to the agent, or press some choices.")
        return self


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
            choices=body.choices.strip(),
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
            card = await guide(
                db, teacher, await _guide_button(db, teacher, reply.data["guide"]), agent
            )
        except HTTPException as exc:
            await thread.event(db, teacher, text=f"Couldn't pass that on: {exc.detail}")
            await db.commit()
    return card


async def _guide_button(db, teacher: User, guide: dict) -> "ActionIn":
    """The Guide press for the student the teacher named, in the lesson running now."""
    focus = await current_focus(db, teacher)
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
    focus = await current_focus(db, teacher)
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
        lesson = await owned_lesson(db, teacher, lesson_id)
    else:
        lesson = (await current_focus(db, teacher)).lesson
    if lesson is None:
        lesson = lessons.new_lesson(db, teacher)
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


@router.get("/lessons", response_model=dict)
async def lessons_list(teacher: CurrentTeacher, db: DbSession) -> dict:
    """Every lesson, for the picker. Nothing is written to the thread."""
    return await cards.lessons_card(db, teacher)


@router.post("/actions", response_model=ThreadOut)
async def act(body: ActionIn, teacher: CurrentTeacher, db: DbSession, agent: Agent) -> ThreadOut:
    handler = _HANDLERS[body.action]
    return await _thread(db, teacher, await handler(db, teacher, body, agent))


_HANDLERS = {
    "show_lesson": show_lesson,
    "show_lessons": show_lessons,
    "show_class": show_class,
    "show_student": show_student,
    "show_transcript": show_transcript,
    "show_outcomes": show_outcomes,
    "focus_lesson": show_lesson,
    "new_lesson": start_new_lesson,
    "follow_up": follow_up,
    "clear": clear_thread,
    "approve": approve,
    "run": run,
    "pause": partial(change_state, to=SessionStatus.PAUSED, said=""),
    "resume": partial(change_state, to=SessionStatus.OPEN, said=""),
    "end": partial(
        change_state,
        to=SessionStatus.CLOSED,
        said="Ended “{title}”. Press Write the summary for how the class did and a note on "
        "each student.",
    ),
    "suggest_outcomes": suggest_outcomes,
    "confirm_outcome": confirm_outcome,
    "acknowledge": acknowledge,
    "guide": guide,
    "delete_material": delete_material,
    "delete_lesson": delete_lesson,
    "set_unit": set_unit,
    "set_approach": set_approach,
    "start_approach": start_approach,
    "copy_with_approach": copy_with_approach,
    "preview_lesson": preview_lesson,
}
