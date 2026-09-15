"""Lesson plans (concept note S2, "Prepare").

The teacher supplies objectives, exercises, expected answers, the permitted
hint sequence, the exception thresholds and the lesson's phases; the platform
stores them and enforces them. Nothing here generates teaching material.

A plan is written as a draft and then deliberately approved. That is a real
step, not ceremony: approval is the moment a teacher says these limits are the
ones her class will be held to, and it is recorded with her id and the time.

Plans are reusable and versioned. Every version of a plan shares a `plan_id`.
Editing an approved plan makes a new draft version instead of changing the
approved one, because lessons already taught must keep pointing at exactly the
limits their class was held to. For the same reason a plan that has been used
is archived rather than deleted: its lessons and students' work stay intact.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select, update

from app.auth import CurrentTeacher, DbSession
from app.enums import LADDER, ContractStatus, ItemKind, Rung
from app.models import Class, ContractItem, LessonContract, Objective, Session, User
from app.timeline import DEFAULT_TIMELINE, Phase, Timeline, timeline_of, total_minutes
from app.tutor.policy import AssistanceLadder

router = APIRouter(prefix="/api/teacher/plans", tags=["lesson plans"])


class MisconceptionIn(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1, max_length=200)


class CriterionIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    max: int = Field(ge=1, le=20)
    description: str = Field(default="", max_length=400)


class RubricIn(BaseModel):
    criteria: list[CriterionIn] = Field(min_length=1, max_length=8)


class ItemIn(BaseModel):
    kind: ItemKind = ItemKind.SHORT_ANSWER
    prompt: str = Field(min_length=1, max_length=2000)
    # Short answers are marked against this; written responses have none.
    expected_answer: str | None = Field(default=None, max_length=200)
    # Written responses are marked against this.
    rubric: RubricIn | None = None
    hint_templates: dict[str, str] = Field(default_factory=dict)
    misconception_vocabulary: list[MisconceptionIn] = Field(default_factory=list)

    @field_validator("hint_templates")
    @classmethod
    def _rungs_must_be_real(cls, value: dict[str, str]) -> dict[str, str]:
        for key in value:
            Rung(key)  # raises for anything not on the ladder
        return value

    @model_validator(mode="after")
    def _marked_by_something(self) -> "ItemIn":
        if self.kind is ItemKind.SHORT_ANSWER and not (self.expected_answer or "").strip():
            raise ValueError("A short-answer task needs its expected answer.")
        if self.kind is ItemKind.WRITTEN_RESPONSE and self.rubric is None:
            raise ValueError("A written-response task needs a rubric to mark it against.")
        return self


class PlanIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=64)
    objective_code: str = Field(min_length=1, max_length=64)
    objective_title: str = Field(min_length=1, max_length=255)
    max_rung: Rung
    allow_full_solution: bool = False
    repeated_incorrect: int = Field(default=3, ge=1, le=20)
    repeated_misconception: int = Field(default=2, ge=1, le=20)
    confidence_floor: float = Field(default=0.45, ge=0.0, le=1.0)
    notes: str = ""
    timeline: list[Phase] = Field(default_factory=lambda: [Phase(**p) for p in DEFAULT_TIMELINE])
    items: list[ItemIn] = Field(min_length=1)

    @field_validator("timeline")
    @classmethod
    def _timeline_is_teachable(cls, phases: list[Phase]) -> list[Phase]:
        Timeline(phases=phases)
        return phases


class PlanSummary(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    title: str
    subject: str
    status: str
    version: int
    items: int
    max_rung: str
    allow_full_solution: bool
    minutes: int
    # The version a class can be taught with right now, even while a newer draft is open.
    approved_version_id: uuid.UUID | None
    approved_version: int | None
    used_with: list[str]
    archived: bool


class PlanDetail(PlanSummary):
    objective_code: str
    objective_title: str
    notes: str
    repeated_incorrect: int
    repeated_misconception: int
    confidence_floor: float
    timeline: list[Phase]
    item_list: list[ItemIn]


# ---------- helpers ----------


async def _owned(plan_version_id: uuid.UUID, teacher: User, db) -> LessonContract:
    contract = await db.get(LessonContract, plan_version_id)
    if contract is None or contract.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="Lesson plan not found.")
    return contract


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


async def _used_with(db, plan_id: uuid.UUID) -> list[str]:
    labels = (
        await db.scalars(
            select(Class.label)
            .join(Session, Session.class_id == Class.id)
            .join(LessonContract, LessonContract.id == Session.contract_id)
            .where(LessonContract.plan_id == plan_id)
            .distinct()
            .order_by(Class.label)
        )
    ).all()
    return list(labels)


async def _item_count(db, contract_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count(ContractItem.id)).where(ContractItem.contract_id == contract_id)
        )
    ) or 0


async def _summary(db, contract: LessonContract) -> PlanSummary:
    versions = await _versions(db, contract.plan_id)
    approved = next(
        (v for v in reversed(versions) if v.status == ContractStatus.ACTIVE.value), None
    )
    return PlanSummary(
        id=contract.id,
        plan_id=contract.plan_id,
        title=contract.title,
        subject=contract.subject,
        status=contract.status,
        version=contract.version,
        items=await _item_count(db, contract.id),
        max_rung=contract.assistance_ladder["max_rung"],
        allow_full_solution=contract.assistance_ladder["allow_full_solution"],
        minutes=total_minutes(contract.timeline),
        approved_version_id=approved.id if approved else None,
        approved_version=approved.version if approved else None,
        used_with=await _used_with(db, contract.plan_id),
        archived=contract.archived_at is not None,
    )


def _ladder(body: PlanIn) -> dict:
    ladder = {
        "rungs": [r.value for r in LADDER[: LADDER.index(body.max_rung) + 1]],
        "max_rung": body.max_rung.value,
        "allow_full_solution": body.allow_full_solution,
    }
    # Validated when saved, so a contradictory ladder is refused while the
    # teacher is still looking at the form rather than at the first attempt.
    try:
        AssistanceLadder.from_contract(ladder)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ladder


async def _apply(db, contract: LessonContract, body: PlanIn) -> None:
    """Write the form onto a draft version, replacing its questions."""
    objective = await db.scalar(select(Objective).where(Objective.code == body.objective_code))
    if objective is None:
        objective = Objective(code=body.objective_code, title=body.objective_title)
        db.add(objective)
        await db.flush()

    contract.title = body.title
    contract.subject = body.subject
    contract.assistance_ladder = _ladder(body)
    contract.exception_thresholds = {
        "repeated_incorrect": body.repeated_incorrect,
        "repeated_misconception": body.repeated_misconception,
        "confidence_floor": body.confidence_floor,
    }
    contract.material = {"notes": body.notes, "images": []}
    contract.timeline = [p.model_dump() for p in body.timeline]
    await db.flush()

    # A draft has never run, so nothing refers to its questions yet.
    await db.execute(delete(ContractItem).where(ContractItem.contract_id == contract.id))
    for ordinal, item in enumerate(body.items, start=1):
        db.add(
            ContractItem(
                contract_id=contract.id,
                objective_id=objective.id,
                ordinal=ordinal,
                kind=item.kind.value,
                prompt=item.prompt,
                expected_answer=(
                    item.expected_answer if item.kind is ItemKind.SHORT_ANSWER else None
                ),
                rubric=(
                    item.rubric.model_dump()
                    if item.kind is ItemKind.WRITTEN_RESPONSE and item.rubric
                    else None
                ),
                hint_templates=item.hint_templates,
                misconception_vocabulary=[m.model_dump() for m in item.misconception_vocabulary],
            )
        )


async def _copy(
    db, source: LessonContract, *, plan_id: uuid.UUID, version: int, title: str
) -> LessonContract:
    copy = LessonContract(
        plan_id=plan_id,
        teacher_id=source.teacher_id,
        title=title,
        subject=source.subject,
        status=ContractStatus.DRAFT.value,
        version=version,
        assistance_ladder=dict(source.assistance_ladder),
        exception_thresholds=dict(source.exception_thresholds),
        material=dict(source.material or {}),
        timeline=timeline_of(source.timeline),
    )
    db.add(copy)
    await db.flush()
    items = (
        await db.scalars(
            select(ContractItem)
            .where(ContractItem.contract_id == source.id)
            .order_by(ContractItem.ordinal)
        )
    ).all()
    for item in items:
        db.add(
            ContractItem(
                contract_id=copy.id,
                objective_id=item.objective_id,
                ordinal=item.ordinal,
                kind=item.kind,
                prompt=item.prompt,
                expected_answer=item.expected_answer,
                rubric=item.rubric,
                hint_templates=dict(item.hint_templates or {}),
                misconception_vocabulary=list(item.misconception_vocabulary or []),
            )
        )
    await db.flush()
    return copy


def _require_draft(contract: LessonContract) -> None:
    if contract.status != ContractStatus.DRAFT.value:
        raise HTTPException(
            status_code=409,
            detail="This version is approved. Edit it as a new version instead.",
        )


# ---------- endpoints ----------


@router.post("", response_model=PlanSummary, status_code=status.HTTP_201_CREATED)
async def create_plan(body: PlanIn, teacher: CurrentTeacher, db: DbSession) -> PlanSummary:
    """Write a new plan as draft version 1. It governs nobody until approved."""
    contract = LessonContract(
        plan_id=uuid.uuid4(),
        teacher_id=teacher.id,
        title=body.title,
        subject=body.subject,
        status=ContractStatus.DRAFT.value,
        version=1,
        assistance_ladder={},
        exception_thresholds={},
        material={},
        timeline=[],
    )
    db.add(contract)
    await db.flush()
    await _apply(db, contract, body)
    await db.commit()
    return await _summary(db, contract)


@router.get("", response_model=list[PlanSummary])
async def list_plans(
    teacher: CurrentTeacher,
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = None,
) -> list[PlanSummary]:
    """The library: the newest version of each plan that hasn't been deleted."""
    rows = (
        await db.scalars(
            select(LessonContract)
            .where(LessonContract.teacher_id == teacher.id, LessonContract.archived_at.is_(None))
            .order_by(LessonContract.plan_id, LessonContract.version.desc())
        )
    ).all()
    latest: dict[uuid.UUID, LessonContract] = {}
    for contract in rows:
        latest.setdefault(contract.plan_id, contract)

    out = []
    for contract in sorted(latest.values(), key=lambda c: c.created_at, reverse=True):
        summary = await _summary(db, contract)
        if status_filter == "draft" and summary.status != ContractStatus.DRAFT.value:
            continue
        if status_filter == "approved" and summary.approved_version_id is None:
            continue
        if q and q.lower() not in f"{summary.title} {summary.subject}".lower():
            continue
        out.append(summary)
    return out


@router.get("/{plan_version_id}", response_model=PlanDetail)
async def read_plan(
    plan_version_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> PlanDetail:
    contract = await _owned(plan_version_id, teacher, db)
    items = (
        await db.scalars(
            select(ContractItem)
            .where(ContractItem.contract_id == contract.id)
            .order_by(ContractItem.ordinal)
        )
    ).all()
    objective = await db.get(Objective, items[0].objective_id) if items else None
    thresholds = contract.exception_thresholds or {}
    summary = await _summary(db, contract)
    return PlanDetail(
        **summary.model_dump(),
        objective_code=objective.code if objective else "",
        objective_title=objective.title if objective else "",
        notes=(contract.material or {}).get("notes", ""),
        repeated_incorrect=int(thresholds.get("repeated_incorrect", 3)),
        repeated_misconception=int(thresholds.get("repeated_misconception", 2)),
        confidence_floor=float(thresholds.get("confidence_floor", 0.45)),
        timeline=[Phase(**p) for p in timeline_of(contract.timeline)],
        item_list=[
            ItemIn(
                kind=ItemKind(i.kind),
                prompt=i.prompt,
                expected_answer=i.expected_answer,
                rubric=i.rubric,
                hint_templates=i.hint_templates or {},
                misconception_vocabulary=i.misconception_vocabulary or [],
            )
            for i in items
        ],
    )


@router.put("/{plan_version_id}", response_model=PlanSummary)
async def update_draft(
    plan_version_id: uuid.UUID, body: PlanIn, teacher: CurrentTeacher, db: DbSession
) -> PlanSummary:
    contract = await _owned(plan_version_id, teacher, db)
    _require_draft(contract)
    await _apply(db, contract, body)
    await db.commit()
    return await _summary(db, contract)


@router.post("/{plan_version_id}/versions", response_model=PlanSummary, status_code=201)
async def new_version(
    plan_version_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> PlanSummary:
    """Start editing an approved plan as its next version.

    If a newer draft of the plan is already open, that draft is returned rather
    than a second one being made.
    """
    source = await _owned(plan_version_id, teacher, db)
    versions = await _versions(db, source.plan_id)
    open_draft = next((v for v in versions if v.status == ContractStatus.DRAFT.value), None)
    if open_draft is not None:
        return await _summary(db, open_draft)
    copy = await _copy(
        db, source, plan_id=source.plan_id, version=versions[-1].version + 1, title=source.title
    )
    await db.commit()
    return await _summary(db, copy)


@router.post("/{plan_version_id}/approve", response_model=PlanSummary)
async def approve(
    plan_version_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> PlanSummary:
    """The teacher's approval, recorded against her and the moment.

    Approving a newer version retires the older approved one for new lessons;
    lessons already taught keep pointing at the version they used.
    """
    contract = await _owned(plan_version_id, teacher, db)
    if contract.status == ContractStatus.CLOSED.value:
        raise HTTPException(
            status_code=409, detail="A newer version of this plan replaced this one."
        )
    await db.execute(
        update(LessonContract)
        .where(
            LessonContract.plan_id == contract.plan_id,
            LessonContract.id != contract.id,
            LessonContract.status == ContractStatus.ACTIVE.value,
        )
        .values(status=ContractStatus.CLOSED.value)
    )
    contract.status = ContractStatus.ACTIVE.value
    contract.activated_at = datetime.now(UTC)
    contract.activated_by = teacher.id
    await db.commit()
    return await _summary(db, contract)


@router.post("/{plan_version_id}/duplicate", response_model=PlanSummary, status_code=201)
async def duplicate(
    plan_version_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> PlanSummary:
    source = await _owned(plan_version_id, teacher, db)
    copy = await _copy(db, source, plan_id=uuid.uuid4(), version=1, title=f"Copy of {source.title}")
    await db.commit()
    return await _summary(db, copy)


class DeleteOut(BaseModel):
    outcome: str  # "deleted" | "archived"
    plan_id: uuid.UUID


@router.delete("/{plan_version_id}", response_model=DeleteOut)
async def delete_plan(
    plan_version_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> DeleteOut:
    """Remove a plan from the library.

    * A draft that is a newer version of a plan: only that draft is discarded.
    * A plan no class has ever used: deleted for good.
    * A plan that has been used: archived, so its lessons and work are kept.
    """
    contract = await _owned(plan_version_id, teacher, db)
    versions = await _versions(db, contract.plan_id)

    if contract.status == ContractStatus.DRAFT.value and len(versions) > 1:
        await db.delete(contract)
        await db.commit()
        return DeleteOut(outcome="deleted", plan_id=contract.plan_id)

    used = await db.scalar(
        select(func.count(Session.id)).where(Session.contract_id.in_([v.id for v in versions]))
    )
    if used:
        now = datetime.now(UTC)
        for v in versions:
            v.archived_at = now
        await db.commit()
        return DeleteOut(outcome="archived", plan_id=contract.plan_id)

    for v in versions:
        await db.delete(v)
    await db.commit()
    return DeleteOut(outcome="deleted", plan_id=contract.plan_id)


@router.post("/{plan_version_id}/restore", response_model=PlanSummary)
async def restore(
    plan_version_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> PlanSummary:
    """Undo an archive."""
    contract = await _owned(plan_version_id, teacher, db)
    for v in await _versions(db, contract.plan_id):
        v.archived_at = None
    await db.commit()
    return await _summary(db, contract)
