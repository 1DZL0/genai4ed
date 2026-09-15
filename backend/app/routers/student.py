"""The student's side of a session.

Text-first, and narrow on purpose: see the task, submit an attempt, ask for the
teacher. Nothing here returns another student's work, the expected answer, or
the permitted rung.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth import (
    CurrentStudent,
    DbSession,
    open_student_session,
    student_session,
    unclosed_student_session,
)
from app.enums import EXCEPTION_PRIORITY, EvidenceKind, ExceptionKind, SessionStatus
from app.events import broker
from app.ledger import append
from app.lifecycle import close_expired
from app.models import (
    ContractItem,
    EvidenceRecord,
    Exception_,
    LessonContract,
    Session,
    SessionParticipant,
)
from app.schemas import AttemptCreate, AttemptResult
from app.tutor.service import TutorService, get_tutor_service

router = APIRouter(prefix="/api/sessions", tags=["student"])

Service = Annotated[TutorService, Depends(get_tutor_service)]

# Shown in the student interface. The note requires transcript access to be
# disclosed clearly rather than discovered later.
DISCLOSURE = "Your teacher can read this conversation."


class HistoryLine(BaseModel):
    """One line of the student's own work, as they saw it happen.

    Built field by field on purpose: the stored attempt payload also carries
    the canonical expected answer, which must never reach the student.
    """

    kind: Literal["attempt", "hint", "teacher"]
    text: str
    correct: bool | None = None
    at: datetime


class ItemOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    prompt: str
    attempts: int
    solved: bool
    history: list[HistoryLine]


class StudentSessionOut(BaseModel):
    session_id: uuid.UUID
    status: str
    closes_at: datetime
    title: str
    subject: str
    material_notes: str | None
    disclosure: str
    items: list[ItemOut]
    # Messages from the teacher that are not about one question.
    teacher_messages: list[HistoryLine]


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
    closes_at: datetime
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
                    ]
                ),
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()

    history: dict[uuid.UUID | None, list[HistoryLine]] = {}
    for r in records:
        if r.kind == EvidenceKind.ATTEMPT.value:
            line = HistoryLine(
                kind="attempt",
                text=str(r.payload.get("answer", "")),
                correct=r.correct,
                at=r.created_at,
            )
        elif r.kind == EvidenceKind.HINT.value:
            line = HistoryLine(kind="hint", text=str(r.payload.get("message", "")), at=r.created_at)
        else:
            line = HistoryLine(kind="teacher", text=str(r.payload.get("text", "")), at=r.created_at)
        history.setdefault(r.item_id, []).append(line)

    return StudentSessionOut(
        session_id=session.id,
        status=session.status,
        closes_at=session.closes_at,
        title=contract.title,
        subject=contract.subject,
        material_notes=(contract.material or {}).get("notes"),
        disclosure=DISCLOSURE,
        items=[
            ItemOut(
                id=i.id,
                ordinal=i.ordinal,
                prompt=i.prompt,
                attempts=sum(1 for h in history.get(i.id, []) if h.kind == "attempt"),
                solved=any(h.correct for h in history.get(i.id, []) if h.kind == "attempt"),
                history=history.get(i.id, []),
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

    return await service.handle_attempt(
        db, session=session, contract=contract, student=student, item=item, answer=body.answer
    )


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
