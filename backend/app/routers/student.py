"""The student's side of a session.

Text-first, and narrow on purpose: see the task, submit an attempt, ask for the
teacher. Nothing here returns another student's work, the expected answer, or
the permitted rung.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import (
    CurrentStudent,
    DbSession,
    open_student_session,
    student_session,
    unclosed_student_session,
)
from app.enums import (
    EXCEPTION_PRIORITY,
    EvidenceKind,
    ExceptionKind,
    ItemKind,
    ScoreStatus,
    SessionStatus,
    TutorAsk,
)
from app.events import broker
from app.ledger import append
from app.lifecycle import close_expired
from app.models import (
    ContractItem,
    EvidenceRecord,
    Exception_,
    LessonContract,
    RubricScore,
    Session,
    SessionParticipant,
    User,
)
from app.schemas import AttemptCreate, AttemptResult
from app.timeline import timeline_of
from app.tutor.service import TutorService, get_tutor_service
from app.tutor.writing import WritingError, WritingService, get_writing_service

router = APIRouter(prefix="/api/sessions", tags=["student"])

Service = Annotated[TutorService, Depends(get_tutor_service)]
Writing = Annotated[WritingService, Depends(get_writing_service)]

# Shown in the student interface. The note requires transcript access to be
# disclosed clearly rather than discovered later.
DISCLOSURE = "Your teacher can read this conversation."


class HistoryLine(BaseModel):
    """One line of the student's own work, as they saw it happen.

    Built field by field on purpose: the stored attempt payload also carries
    the canonical expected answer, which must never reach the student.
    """

    # "ask" is the student's own request to the tutor on a written response.
    kind: Literal["attempt", "hint", "teacher", "ask"]
    text: str
    correct: bool | None = None
    at: datetime


class ConfirmedScore(BaseModel):
    """Only ever a score the teacher has confirmed."""

    total: int
    out_of: int
    criteria: list[dict]
    keep: str
    develop: list[str]
    comment: str | None


class ItemOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    kind: str
    prompt: str
    attempts: int
    solved: bool
    history: list[HistoryLine]
    # Written responses: the latest text, whether it is handed in, and the score
    # once the teacher has confirmed it. The rubric is shown so students know
    # what they are marked on.
    text: str = ""
    submitted: bool = False
    score: ConfirmedScore | None = None
    rubric: list[dict] = []


class StudentSessionOut(BaseModel):
    session_id: uuid.UUID
    status: str
    closes_at: datetime | None
    title: str
    subject: str
    material_notes: str | None
    disclosure: str
    phase_name: str | None
    tutors_on: bool
    items: list[ItemOut]
    # Messages from the teacher that are not about one question.
    teacher_messages: list[HistoryLine]


ASK_WORDS = {
    TutorAsk.STUCK.value: "I'm stuck",
    TutorAsk.LANGUAGE.value: "Can you check my language?",
    TutorAsk.FEEDBACK.value: "What do you think of my paragraph?",
}


async def _contract(db, session) -> LessonContract:
    contract = await db.get(LessonContract, session.contract_id)
    if contract is None:  # pragma: no cover - foreign key makes this unreachable
        raise HTTPException(status_code=404, detail="Contract not found.")
    return contract


class SessionSummary(BaseModel):
    session_id: uuid.UUID
    title: str
    subject: str
    status: str
    closes_at: datetime | None
    items: int


@router.get("", response_model=list[SessionSummary])
async def my_sessions(student: CurrentStudent, db: DbSession) -> list[SessionSummary]:
    """The sessions this student has been admitted to.

    Without this a student has no way in: session ids are UUIDs precisely so
    they cannot be guessed, so the platform has to tell them their own.
    """
    await close_expired(db)
    rows = (
        await db.execute(
            select(Session, LessonContract)
            .join(SessionParticipant, SessionParticipant.session_id == Session.id)
            .join(LessonContract, LessonContract.id == Session.contract_id)
            .where(
                SessionParticipant.student_id == student.id,
                Session.status != SessionStatus.CLOSED.value,
            )
            .order_by(Session.opened_at.desc())
        )
    ).all()

    out: list[SessionSummary] = []
    for session, contract in rows:
        items = len(
            (
                await db.scalars(
                    select(ContractItem.id).where(ContractItem.contract_id == contract.id)
                )
            ).all()
        )
        out.append(
            SessionSummary(
                session_id=session.id,
                title=contract.title,
                subject=contract.subject,
                status=session.status,
                closes_at=session.closes_at,
                items=items,
            )
        )
    return out


@router.get("/{session_id}", response_model=StudentSessionOut)
async def read_session(
    session_id: uuid.UUID, student: CurrentStudent, db: DbSession
) -> StudentSessionOut:
    session = await student_session(session_id, student, db)
    return await build_student_view(db, session, student)


async def build_student_view(db, session: Session, student: User) -> StudentSessionOut:
    """Exactly what one student sees in one lesson. Shared with the demo
    walkthrough's read-only preview, so the preview can't drift from the real page."""
    contract = await _contract(db, session)
    items = (
        await db.scalars(
            select(ContractItem)
            .where(ContractItem.contract_id == contract.id)
            .order_by(ContractItem.ordinal)
        )
    ).all()

    # Only this student's records in this session: the isolation boundary
    # above already guarantees the session, and the filter keeps it to them.
    records = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.student_id == student.id,
                EvidenceRecord.kind.in_(
                    [
                        EvidenceKind.ATTEMPT.value,
                        EvidenceKind.HINT.value,
                        EvidenceKind.TEACHER_FEEDBACK.value,
                        EvidenceKind.TUTOR_REQUEST.value,
                        EvidenceKind.DRAFT.value,
                        EvidenceKind.SUBMISSION.value,
                    ]
                ),
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()

    history: dict[uuid.UUID | None, list[HistoryLine]] = {}
    latest_text: dict[uuid.UUID | None, str] = {}
    submitted: set[uuid.UUID | None] = set()
    for r in records:
        if r.kind in (EvidenceKind.DRAFT.value, EvidenceKind.SUBMISSION.value):
            latest_text[r.item_id] = str(r.payload.get("text", ""))
            if r.kind == EvidenceKind.SUBMISSION.value:
                submitted.add(r.item_id)
            continue
        if r.kind == EvidenceKind.ATTEMPT.value:
            line = HistoryLine(
                kind="attempt",
                text=str(r.payload.get("answer", "")),
                correct=r.correct,
                at=r.created_at,
            )
        elif r.kind == EvidenceKind.HINT.value:
            line = HistoryLine(kind="hint", text=str(r.payload.get("message", "")), at=r.created_at)
        elif r.kind == EvidenceKind.TUTOR_REQUEST.value:
            ask = str(r.payload.get("ask", ""))
            said = str(r.payload.get("question") or ASK_WORDS.get(ask, ask))
            line = HistoryLine(kind="ask", text=said, at=r.created_at)
        else:
            line = HistoryLine(kind="teacher", text=str(r.payload.get("text", "")), at=r.created_at)
        history.setdefault(r.item_id, []).append(line)

    # Scores reach a student only once the teacher has confirmed them.
    confirmed = {
        s.item_id: s
        for s in (
            await db.scalars(
                select(RubricScore).where(
                    RubricScore.session_id == session.id,
                    RubricScore.student_id == student.id,
                    RubricScore.status == ScoreStatus.CONFIRMED.value,
                )
            )
        ).all()
    }

    def score_for(item: ContractItem) -> ConfirmedScore | None:
        s = confirmed.get(item.id)
        if s is None or s.confirmed is None:
            return None
        return ConfirmedScore(
            total=s.confirmed_total or 0,
            out_of=sum(int(c["max"]) for c in s.confirmed["criteria"]),
            criteria=[
                {"name": c["name"], "points": c["points"], "max": c["max"]}
                for c in s.confirmed["criteria"]
            ],
            keep=s.confirmed.get("keep", ""),
            develop=list(s.confirmed.get("develop", [])),
            comment=s.comment,
        )

    phases = timeline_of(contract.timeline)
    live = session.status in (SessionStatus.OPEN.value, SessionStatus.PAUSED.value)
    phase = phases[session.phase_index] if live and session.phase_index < len(phases) else None

    return StudentSessionOut(
        session_id=session.id,
        status=session.status,
        closes_at=session.closes_at,
        title=contract.title,
        subject=contract.subject,
        material_notes=(contract.material or {}).get("notes"),
        disclosure=DISCLOSURE,
        phase_name=phase["name"] if phase else None,
        tutors_on=bool(phase and phase["tutors_on"]),
        items=[
            ItemOut(
                id=i.id,
                ordinal=i.ordinal,
                kind=i.kind,
                prompt=i.prompt,
                attempts=sum(1 for h in history.get(i.id, []) if h.kind == "attempt"),
                solved=any(h.correct for h in history.get(i.id, []) if h.kind == "attempt"),
                history=history.get(i.id, []),
                text=latest_text.get(i.id, ""),
                submitted=i.id in submitted,
                score=score_for(i),
                rubric=[
                    {"name": c["name"], "max": c["max"], "description": c.get("description", "")}
                    for c in (i.rubric or {}).get("criteria", [])
                ],
            )
            for i in items
        ],
        teacher_messages=history.get(None, []),
    )


@router.post("/{session_id}/attempts", response_model=AttemptResult)
async def submit_attempt(
    session_id: uuid.UUID,
    body: AttemptCreate,
    student: CurrentStudent,
    db: DbSession,
    service: Service,
) -> AttemptResult:
    session = await open_student_session(session_id, student, db)
    contract = await _contract(db, session)

    item = await db.get(ContractItem, body.item_id)
    if item is None or item.contract_id != contract.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")
    if item.kind != ItemKind.SHORT_ANSWER.value:
        raise HTTPException(
            status_code=422, detail="This task is written, not answered in one line."
        )

    return await service.handle_attempt(
        db, session=session, contract=contract, student=student, item=item, answer=body.answer
    )


# ---------- written responses ----------


class DraftIn(BaseModel):
    text: str = Field(max_length=6000)


class AskIn(BaseModel):
    ask: TutorAsk
    text: str = Field(default="", max_length=6000)
    question: str = Field(default="", max_length=500)


class HelpOut(BaseModel):
    message: str
    withheld: bool
    teacher_notified: bool


class SubmitOut(BaseModel):
    submitted: bool
    # Never the score itself: that waits for the teacher.
    waiting_for_teacher: bool


async def _written_item(
    db, session: Session, item_id: uuid.UUID
) -> tuple[LessonContract, ContractItem]:
    contract = await _contract(db, session)
    item = await db.get(ContractItem, item_id)
    if item is None or item.contract_id != contract.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if item.kind != ItemKind.WRITTEN_RESPONSE.value:
        raise HTTPException(status_code=422, detail="This task is answered in one line.")
    return contract, item


def _raise(error: WritingError) -> None:
    raise HTTPException(status_code=error.status, detail=error.detail) from error


@router.put("/{session_id}/items/{item_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
async def save_draft(
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    body: DraftIn,
    student: CurrentStudent,
    db: DbSession,
    writing: Writing,
) -> None:
    """Autosave. Allowed while the lesson is open, whatever the phase, so
    nothing is lost when the teacher moves the class on mid-sentence."""
    session = await unclosed_student_session(session_id, student, db)
    _, item = await _written_item(db, session, item_id)
    try:
        await writing.save_draft(db, session=session, student=student, item=item, text=body.text)
    except WritingError as error:
        _raise(error)


@router.post("/{session_id}/items/{item_id}/ask", response_model=HelpOut)
async def ask_tutor(
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    body: AskIn,
    student: CurrentStudent,
    db: DbSession,
    writing: Writing,
) -> HelpOut:
    session = await open_student_session(session_id, student, db)
    contract, item = await _written_item(db, session, item_id)
    try:
        reply = await writing.ask(
            db,
            session=session,
            contract=contract,
            student=student,
            item=item,
            ask=body.ask,
            text=body.text,
            question=body.question,
        )
    except WritingError as error:
        _raise(error)
    return HelpOut(
        message=reply.message, withheld=reply.withheld, teacher_notified=reply.teacher_notified
    )


@router.post("/{session_id}/items/{item_id}/submit", response_model=SubmitOut)
async def submit_written(
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    body: DraftIn,
    student: CurrentStudent,
    db: DbSession,
    writing: Writing,
) -> SubmitOut:
    session = await unclosed_student_session(session_id, student, db)
    _, item = await _written_item(db, session, item_id)
    try:
        await writing.submit(db, session=session, student=student, item=item, text=body.text)
    except WritingError as error:
        _raise(error)
    return SubmitOut(submitted=True, waiting_for_teacher=True)


@router.post("/{session_id}/request-teacher", status_code=status.HTTP_202_ACCEPTED)
async def request_teacher(
    session_id: uuid.UUID, student: CurrentStudent, db: DbSession
) -> dict[str, str]:
    """The student's own escalation.

    It outranks everything the platform inferred about itself, and no model is
    consulted about whether the request is warranted.
    """
    session = await unclosed_student_session(session_id, student, db)

    record = await append(
        db,
        session_id=session.id,
        student_id=student.id,
        kind=EvidenceKind.EXPLORATORY_TURN,
        payload={"event": "requested_teacher"},
        provenance={"source": "student"},
    )
    exc = Exception_(
        session_id=session.id,
        student_id=student.id,
        kind=ExceptionKind.TEACHER_REQUESTED.value,
        priority=EXCEPTION_PRIORITY[ExceptionKind.TEACHER_REQUESTED],
        summary="Pressed “Ask my teacher for help”.",
        supporting_record_ids=[str(record.id)],
        payload={},
    )
    db.add(exc)
    await db.commit()

    await broker.publish(
        session.id,
        {
            "type": "exception",
            "kind": ExceptionKind.TEACHER_REQUESTED.value,
            "priority": EXCEPTION_PRIORITY[ExceptionKind.TEACHER_REQUESTED],
            "student": student.pseudonym,
            "summary": exc.summary,
        },
    )
    return {"status": "your teacher has been told"}
