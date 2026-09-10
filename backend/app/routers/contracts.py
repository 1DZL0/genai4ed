"""Lesson contract authoring (concept note S2, "Prepare").

The teacher supplies objectives, exercises, expected answers, the permitted
hint sequence and the exception thresholds; the platform stores them and
enforces them. Nothing here generates teaching material - the note is explicit
that the way to keep scope under control is teacher-provided exercises, rubrics
and hint templates.

A contract is authored as a draft and then deliberately activated. That is a
real step, not ceremony: activation is the moment a teacher says these limits
are the ones her class will be held to, and it is recorded with her id and the
time.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.auth import CurrentTeacher, DbSession
from app.enums import LADDER, ContractStatus, Role, Rung, SessionStatus
from app.models import (
    Class,
    ContractItem,
    Enrolment,
    LessonContract,
    Objective,
    Session,
    SessionParticipant,
    User,
)
from app.tutor.policy import AssistanceLadder

router = APIRouter(prefix="/api/teacher/contracts", tags=["authoring"])

DEFAULT_SESSION_MINUTES = 50


class MisconceptionIn(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1, max_length=200)


class ItemIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    expected_answer: str = Field(min_length=1, max_length=200)
    hint_templates: dict[str, str] = Field(default_factory=dict)
    misconception_vocabulary: list[MisconceptionIn] = Field(default_factory=list)

    @field_validator("hint_templates")
    @classmethod
    def _rungs_must_be_real(cls, value: dict[str, str]) -> dict[str, str]:
        for key in value:
            Rung(key)  # raises for anything not on the ladder
        return value


class ContractIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=64)
    objective_code: str = Field(min_length=1, max_length=64)
    objective_title: str = Field(min_length=1, max_length=255)
    class_id: uuid.UUID
    max_rung: Rung
    allow_full_solution: bool = False
    repeated_incorrect: int = Field(default=3, ge=1, le=20)
    repeated_misconception: int = Field(default=2, ge=1, le=20)
    confidence_floor: float = Field(default=0.45, ge=0.0, le=1.0)
    notes: str = ""
    items: list[ItemIn] = Field(min_length=1)


class ContractOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    version: int
    items: int
    max_rung: str
    allow_full_solution: bool


class SessionOut(BaseModel):
    session_id: uuid.UUID
    closes_at: datetime
    students: int


def _summarise(contract: LessonContract, items: int) -> ContractOut:
    return ContractOut(
        id=contract.id,
        title=contract.title,
        status=contract.status,
        version=contract.version,
        items=items,
        max_rung=contract.assistance_ladder["max_rung"],
        allow_full_solution=contract.assistance_ladder["allow_full_solution"],
    )


async def _owned_contract(
    contract_id: uuid.UUID, teacher: User, db: DbSession
) -> LessonContract:
    contract = await db.get(LessonContract, contract_id)
    if contract is None or contract.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="Contract not found.")
    return contract


@router.post("", response_model=ContractOut, status_code=status.HTTP_201_CREATED)
async def create_contract(
    body: ContractIn, teacher: CurrentTeacher, db: DbSession
) -> ContractOut:
    """Author a draft. It governs nobody until it is activated."""
    klass = await db.get(Class, body.class_id)
    if klass is None or klass.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="Class not found.")

    rungs = [r.value for r in LADDER[: LADDER.index(body.max_rung) + 1]]
    ladder = {
        "rungs": rungs,
        "max_rung": body.max_rung.value,
        "allow_full_solution": body.allow_full_solution,
    }
    # Validated here rather than at the first attempt, so a contradictory
    # ladder is refused while the teacher is still looking at the form.
    try:
        AssistanceLadder.from_contract(ladder)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    objective = await db.scalar(select(Objective).where(Objective.code == body.objective_code))
    if objective is None:
        objective = Objective(code=body.objective_code, title=body.objective_title)
        db.add(objective)
        await db.flush()

    contract = LessonContract(
        teacher_id=teacher.id,
        class_id=klass.id,
        title=body.title,
        subject=body.subject,
        status=ContractStatus.DRAFT.value,
        version=1,
        assistance_ladder=ladder,
        exception_thresholds={
            "repeated_incorrect": body.repeated_incorrect,
            "repeated_misconception": body.repeated_misconception,
            "confidence_floor": body.confidence_floor,
        },
        material={"notes": body.notes, "images": []},
    )
    db.add(contract)
    await db.flush()

    for ordinal, item in enumerate(body.items, start=1):
        db.add(
            ContractItem(
                contract_id=contract.id,
                objective_id=objective.id,
                ordinal=ordinal,
                prompt=item.prompt,
                expected_answer=item.expected_answer,
                rubric=None,
                hint_templates=item.hint_templates,
                misconception_vocabulary=[m.model_dump() for m in item.misconception_vocabulary],
            )
        )

    await db.commit()
    return _summarise(contract, len(body.items))


@router.get("", response_model=list[ContractOut])
async def list_contracts(teacher: CurrentTeacher, db: DbSession) -> list[ContractOut]:
    contracts = (
        await db.scalars(
            select(LessonContract)
            .where(LessonContract.teacher_id == teacher.id)
            .order_by(LessonContract.created_at.desc())
        )
    ).all()
    out = []
    for contract in contracts:
        items = len(
            (
                await db.scalars(
                    select(ContractItem.id).where(ContractItem.contract_id == contract.id)
                )
            ).all()
        )
        out.append(_summarise(contract, items))
    return out


@router.post("/{contract_id}/activate", response_model=ContractOut)
async def activate(contract_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> ContractOut:
    """The teacher's approval, recorded against her and the moment."""
    contract = await _owned_contract(contract_id, teacher, db)
    if contract.status == ContractStatus.CLOSED.value:
        raise HTTPException(status_code=409, detail="This contract has been closed.")

    contract.status = ContractStatus.ACTIVE.value
    contract.activated_at = datetime.now(UTC)
    contract.activated_by = teacher.id
    await db.commit()

    items = len(
        (
            await db.scalars(
                select(ContractItem.id).where(ContractItem.contract_id == contract.id)
            )
        ).all()
    )
    return _summarise(contract, items)


@router.post("/{contract_id}/sessions", response_model=SessionOut, status_code=201)
async def open_session(
    contract_id: uuid.UUID,
    teacher: CurrentTeacher,
    db: DbSession,
    minutes: int = DEFAULT_SESSION_MINUTES,
) -> SessionOut:
    """Open a timed session and admit the class.

    Membership is written now rather than on arrival, because it is the
    isolation boundary: a student who is not a participant cannot reach the
    session at all.
    """
    contract = await _owned_contract(contract_id, teacher, db)
    if contract.status != ContractStatus.ACTIVE.value:
        raise HTTPException(
            status_code=409,
            detail="Activate the contract before opening a session for it.",
        )
    if not 1 <= minutes <= 240:
        raise HTTPException(status_code=422, detail="A session runs between 1 and 240 minutes.")

    now = datetime.now(UTC)
    session = Session(
        contract_id=contract.id,
        class_id=contract.class_id,
        status=SessionStatus.OPEN.value,
        opened_at=now,
        closes_at=now + timedelta(minutes=minutes),
    )
    db.add(session)
    await db.flush()

    students = (
        await db.scalars(
            select(User)
            .join(Enrolment, Enrolment.student_id == User.id)
            .where(Enrolment.class_id == contract.class_id, User.role == Role.STUDENT.value)
        )
    ).all()
    db.add_all(
        [SessionParticipant(session_id=session.id, student_id=s.id) for s in students]
    )
    await db.commit()

    return SessionOut(session_id=session.id, closes_at=session.closes_at, students=len(students))
