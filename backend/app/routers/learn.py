"""A student's lesson: a conversation with the class agent, which runs the teacher's activity."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent import store
from app.agent.brief import LessonBrief
from app.agent.llm import LLMClient, get_llm_client
from app.agent.student_mode import (
    AgentUnavailable,
    StudentAgent,
    learning_state,
)
from app.auth import (
    CurrentStudent,
    DbSession,
    open_student_session,
    student_session,
    unclosed_student_session,
)
from app.enums import (
    EXCEPTION_PRIORITY,
    Audience,
    EvidenceKind,
    ExceptionKind,
    ExceptionStatus,
    LearningStatus,
    MessageRole,
    ScoreStatus,
    SessionStatus,
    SignalKind,
)
from app.events import broker
from app.ledger import append
from app.lifecycle import close_expired
from app.models import (
    Exception_,
    LessonContract,
    LessonOutcome,
    Session,
    SessionParticipant,
)

router = APIRouter(prefix="/api/learn", tags=["learn"])

Agent = Annotated[LLMClient, Depends(get_llm_client)]

DISCLOSURE = "Your teacher can read this conversation and sees how you're getting on."

# One reply at a time per student, so a message is never judged against a state about to change.
_in_flight: set[tuple[uuid.UUID, uuid.UUID]] = set()


class StepOut(BaseModel):
    name: str
    state: Literal["done", "current", "todo"]


class LineOut(BaseModel):
    id: uuid.UUID
    who: Literal["student", "agent", "note"]
    text: str
    at: datetime


class ResultOut(BaseModel):
    """Built from the teacher's confirmed record only; a suggestion never reaches a student."""

    total: int
    out_of: int
    criteria: list[dict]
    comment: str | None


class LearnOut(BaseModel):
    session_id: uuid.UUID
    status: str
    closes_at: datetime | None
    title: str
    subject: str
    steps: list[StepOut]
    step_index: int
    completed: bool
    task: str | None
    lines: list[LineOut]
    can_talk: bool
    disclosure: str
    result: ResultOut | None = None


class LessonCardOut(BaseModel):
    session_id: uuid.UUID
    title: str
    subject: str
    status: str
    closes_at: datetime | None
    steps: int
    completed: bool
    result: ResultOut | None = None


async def _result(db, session_id: uuid.UUID, student_id: uuid.UUID) -> ResultOut | None:
    outcome = await db.scalar(
        select(LessonOutcome).where(
            LessonOutcome.session_id == session_id,
            LessonOutcome.student_id == student_id,
            LessonOutcome.status == ScoreStatus.CONFIRMED.value,
        )
    )
    if outcome is None or not outcome.confirmed:
        return None
    criteria = outcome.confirmed.get("criteria", [])
    return ResultOut(
        total=outcome.confirmed_total or 0,
        out_of=sum(int(c.get("max", 0)) for c in criteria),
        criteria=[
            {"name": c.get("name", ""), "points": c.get("points", 0), "max": c.get("max", 0)}
            for c in criteria
        ],
        comment=outcome.comment,
    )


class SayIn(BaseModel):
    text: str = Field(default="", max_length=2000)
    intent: Literal["dont_understand", "another_way", "example", "why_wrong"] | None = None


async def _view(db, session: Session, student) -> LearnOut:
    contract = await db.get(LessonContract, session.contract_id)
    brief = LessonBrief.model_validate(contract.brief or {})
    state = await learning_state(
        db, session_id=session.id, student_id=student.id, steps=len(brief.steps)
    )
    conversation = await store.student_conversation(
        db, session_id=session.id, student_id=student.id
    )
    lines: list[LineOut] = []
    for m in await store.messages(db, conversation.id):
        if m.audience != Audience.ALL.value:
            continue
        who = m.role if m.role in ("student", "agent") else "note"
        lines.append(LineOut(id=m.id, who=who, text=m.text, at=m.created_at))

    completed = state.status == LearningStatus.COMPLETED.value
    steps = [
        StepOut(
            name=s.name,
            state="done"
            if completed or i < state.step_index
            else "current"
            if i == state.step_index
            else "todo",
        )
        for i, s in enumerate(brief.steps)
    ]
    task = None
    if 0 <= state.step_index < len(state.steps or []):
        task = (state.steps[state.step_index] or {}).get("task")
    await db.commit()
    return LearnOut(
        session_id=session.id,
        status=session.status,
        closes_at=session.closes_at,
        title=brief.title or contract.title,
        subject=brief.subject or contract.subject,
        steps=steps,
        step_index=state.step_index,
        completed=completed,
        task=None if completed else task,
        lines=lines,
        can_talk=session.status == SessionStatus.OPEN.value,
        disclosure=DISCLOSURE,
        result=(
            await _result(db, session.id, student.id)
            if session.status == SessionStatus.CLOSED.value
            else None
        ),
    )


@router.get("", response_model=list[LessonCardOut])
async def my_lessons(student: CurrentStudent, db: DbSession) -> list[LessonCardOut]:
    await close_expired(db)
    rows = (
        await db.execute(
            select(Session, LessonContract)
            .join(SessionParticipant, SessionParticipant.session_id == Session.id)
            .join(LessonContract, LessonContract.id == Session.contract_id)
            .where(
                SessionParticipant.student_id == student.id,
                Session.status.in_(
                    [
                        SessionStatus.OPEN.value,
                        SessionStatus.PAUSED.value,
                        SessionStatus.CLOSED.value,
                    ]
                ),
            )
            .order_by(Session.opened_at.desc())
        )
    ).all()
    cards = []
    for session, contract in rows:
        brief = LessonBrief.model_validate(contract.brief or {})
        state = await learning_state(
            db, session_id=session.id, student_id=student.id, steps=len(brief.steps)
        )
        closed = session.status == SessionStatus.CLOSED.value
        if closed and state.turns == 0:
            continue  # a lesson they never opened is not one to look back on
        cards.append(
            LessonCardOut(
                session_id=session.id,
                title=brief.title or contract.title,
                subject=brief.subject or contract.subject,
                status=session.status,
                closes_at=session.closes_at,
                steps=len(brief.steps),
                completed=state.status == LearningStatus.COMPLETED.value,
                result=await _result(db, session.id, student.id) if closed else None,
            )
        )
    # Open lessons first, then closed ones, most recent first.
    cards.sort(key=lambda c: c.status == SessionStatus.CLOSED.value)
    await db.commit()
    return cards


@router.get("/{session_id}", response_model=LearnOut)
async def read_lesson(session_id: uuid.UUID, student: CurrentStudent, db: DbSession) -> LearnOut:
    return await _view(db, await student_session(session_id, student, db), student)


async def _turn(db, agent: LLMClient, session: Session, student, text, intent) -> None:
    key = (session.id, student.id)
    # No await between the check and the add, so this is atomic on the event loop.
    if key in _in_flight:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The agent is still answering your last message.",
        )
    _in_flight.add(key)
    try:
        contract = await db.get(LessonContract, session.contract_id)
        if not LessonBrief.model_validate(contract.brief or {}).steps:
            raise HTTPException(status_code=409, detail="This lesson has no activity yet.")
        await StudentAgent(agent).respond(
            db, session=session, contract=contract, student=student, text=text, intent=intent
        )
    except AgentUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="The agent couldn't answer just now. Try sending that again.",
        ) from exc
    finally:
        _in_flight.discard(key)


@router.post("/{session_id}/start", response_model=LearnOut)
async def start(
    session_id: uuid.UUID, student: CurrentStudent, db: DbSession, agent: Agent
) -> LearnOut:
    """The agent's opening, the first time the student opens the lesson."""
    session = await open_student_session(session_id, student, db)
    conversation = await store.student_conversation(
        db, session_id=session.id, student_id=student.id
    )
    if not await store.messages(db, conversation.id, limit=1):
        await _turn(db, agent, session, student, None, None)
    return await _view(db, session, student)


@router.post("/{session_id}/messages", response_model=LearnOut)
async def say(
    session_id: uuid.UUID, body: SayIn, student: CurrentStudent, db: DbSession, agent: Agent
) -> LearnOut:
    session = await open_student_session(session_id, student, db)
    text = body.text.strip()
    if not text and body.intent is None:
        raise HTTPException(status_code=422, detail="Write something to the agent.")
    await _turn(db, agent, session, student, text, body.intent)
    return await _view(db, session, student)


@router.post("/{session_id}/request-teacher", response_model=LearnOut)
async def request_teacher(
    session_id: uuid.UUID, student: CurrentStudent, db: DbSession
) -> LearnOut:
    """The student's own call for the teacher; it always reaches them, no model is asked."""
    session = await unclosed_student_session(session_id, student, db)
    record = await append(
        db,
        session_id=session.id,
        student_id=student.id,
        kind=EvidenceKind.SIGNAL,
        payload={
            "signal": SignalKind.ASKED_FOR_TEACHER.value,
            "severity": "high",
            "note": "Pressed “Ask my teacher”.",
            "action": "alert",
        },
        provenance={"source": "student"},
    )
    open_already = await db.scalar(
        select(Exception_.id).where(
            Exception_.session_id == session.id,
            Exception_.student_id == student.id,
            Exception_.kind == ExceptionKind.TEACHER_REQUESTED.value,
            Exception_.status == ExceptionStatus.OPEN.value,
        )
    )
    if open_already is None:
        db.add(
            Exception_(
                session_id=session.id,
                student_id=student.id,
                kind=ExceptionKind.TEACHER_REQUESTED.value,
                priority=EXCEPTION_PRIORITY[ExceptionKind.TEACHER_REQUESTED],
                summary="Pressed “Ask my teacher”.",
                supporting_record_ids=[str(record.id)],
                payload={},
            )
        )
    conversation = await store.student_conversation(
        db, session_id=session.id, student_id=student.id
    )
    await store.add_message(
        db,
        conversation,
        role=MessageRole.EVENT,
        text="You asked for your teacher. They've been told.",
    )
    await db.commit()
    await broker.publish(
        session.id,
        {
            "type": "exception",
            "kind": ExceptionKind.TEACHER_REQUESTED.value,
            "student": student.pseudonym,
        },
    )
    return await _view(db, session, student)
