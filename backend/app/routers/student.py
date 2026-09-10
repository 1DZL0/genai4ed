"""The student's side of a session.

Text-first, and narrow on purpose: see the task, submit an attempt, ask for the
teacher. Nothing here returns another student's work, the expected answer, or
the permitted rung.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth import CurrentStudent, DbSession, open_student_session, student_session
from app.enums import EXCEPTION_PRIORITY, EvidenceKind, ExceptionKind
from app.events import broker
from app.ledger import append, attempt_count
from app.models import ContractItem, Exception_, LessonContract
from app.schemas import AttemptCreate, AttemptResult
from app.tutor.service import TutorService, get_tutor_service

router = APIRouter(prefix="/api/sessions", tags=["student"])

Service = Annotated[TutorService, Depends(get_tutor_service)]

# Shown in the student interface. The note requires transcript access to be
# disclosed clearly rather than discovered later.
DISCLOSURE = "Your teacher can read this conversation."


class ItemOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    prompt: str
    attempts: int


class StudentSessionOut(BaseModel):
    session_id: uuid.UUID
    status: str
    title: str
    material_notes: str | None
    disclosure: str
    items: list[ItemOut]


async def _contract(db, session) -> LessonContract:
    contract = await db.get(LessonContract, session.contract_id)
    if contract is None:  # pragma: no cover - foreign key makes this unreachable
        raise HTTPException(status_code=404, detail="Contract not found.")
    return contract


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

    return StudentSessionOut(
        session_id=session.id,
        status=session.status,
        title=contract.title,
        material_notes=(contract.material or {}).get("notes"),
        disclosure=DISCLOSURE,
        items=[
            ItemOut(
                id=i.id,
                ordinal=i.ordinal,
                prompt=i.prompt,
                attempts=await attempt_count(db, student.id, i.id),
            )
            for i in items
        ],
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
    session = await student_session(session_id, student, db)

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
        summary=f"{student.pseudonym} asked for you.",
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
