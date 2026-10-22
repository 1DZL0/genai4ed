"""The teacher's lessons as records: versions, drafts, what they have and what is running.

A lesson is a plan with versions; the current version is the open draft, else the newest
approved one. Nothing here talks to the model.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.brief import LessonBrief
from app.enums import ContractStatus, SessionStatus
from app.models import Class, Enrolment, LessonContract, Material, Session, User


async def empty_draft_of(db: AsyncSession, teacher: User) -> LessonContract | None:
    """The teacher's newest draft that nothing has been written into yet, if any."""
    return next((c for c in await latest_versions(db, teacher) if is_empty_draft(c)), None)


def is_empty_draft(lesson: LessonContract | None) -> bool:
    """A draft nobody has written into yet, such as the one an approach tile makes."""
    if lesson is None or lesson.status != ContractStatus.DRAFT.value:
        return False
    brief = LessonBrief.model_validate(lesson.brief or {})
    return not brief.title.strip() and not brief.steps


async def current_version(db: AsyncSession, plan_id: uuid.UUID) -> LessonContract | None:
    """The version a change is made to: the open draft, else the newest approved one, else the
    newest. Never an archived (removed) one."""
    versions = (
        await db.scalars(
            select(LessonContract)
            .where(LessonContract.plan_id == plan_id, LessonContract.archived_at.is_(None))
            .order_by(LessonContract.version.desc())
        )
    ).all()
    for status in (ContractStatus.DRAFT.value, ContractStatus.ACTIVE.value):
        found = next((v for v in versions if v.status == status), None)
        if found is not None:
            return found
    return versions[0] if versions else None


async def latest_versions(db: AsyncSession, teacher: User) -> list[LessonContract]:
    """The latest version of each of the teacher's lessons, newest first."""
    rows = (
        await db.scalars(
            select(LessonContract)
            .where(LessonContract.teacher_id == teacher.id, LessonContract.archived_at.is_(None))
            .order_by(LessonContract.plan_id, LessonContract.version.desc())
        )
    ).all()
    latest: dict[uuid.UUID, LessonContract] = {}
    for row in rows:
        latest.setdefault(row.plan_id, row)
    return sorted(latest.values(), key=lambda c: c.created_at, reverse=True)


async def live_sessions(db: AsyncSession, teacher: User) -> list[Session]:
    """The teacher's open or paused lessons, newest first."""
    return list(
        (
            await db.scalars(
                select(Session)
                .join(Class, Class.id == Session.class_id)
                .where(
                    Class.teacher_id == teacher.id,
                    Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
                )
                .order_by(Session.created_at.desc())
            )
        ).all()
    )


async def classes_of(db: AsyncSession, teacher: User) -> list[tuple[Class, int]]:
    classes = (
        await db.scalars(select(Class).where(Class.teacher_id == teacher.id).order_by(Class.label))
    ).all()
    out = []
    for klass in classes:
        size = await db.scalar(
            select(func.count(Enrolment.id)).where(Enrolment.class_id == klass.id)
        )
        out.append((klass, size or 0))
    return out


async def materials_of(db: AsyncSession, plan_id: uuid.UUID) -> list[Material]:
    return list(
        (
            await db.scalars(
                select(Material).where(Material.plan_id == plan_id).order_by(Material.created_at)
            )
        ).all()
    )


async def draft_to_work_on(db: AsyncSession, contract: LessonContract) -> LessonContract:
    """The draft the teacher's next words change: this one, the plan's open draft,
    or a new draft copied from this version."""
    if contract.status == ContractStatus.DRAFT.value:
        return contract
    versions = (
        await db.scalars(
            select(LessonContract)
            .where(LessonContract.plan_id == contract.plan_id)
            .order_by(LessonContract.version)
        )
    ).all()
    draft = next((v for v in versions if v.status == ContractStatus.DRAFT.value), None)
    if draft is not None:
        return draft
    draft = LessonContract(
        plan_id=contract.plan_id,
        teacher_id=contract.teacher_id,
        title=contract.title,
        subject=contract.subject,
        status=ContractStatus.DRAFT.value,
        version=versions[-1].version + 1,
        brief=dict(contract.brief or {}),
        use_past_lessons=contract.use_past_lessons,
        unit=contract.unit,
        approach=contract.approach,
    )
    db.add(draft)
    await db.flush()
    return draft


def new_lesson(db: AsyncSession, teacher: User) -> LessonContract:
    contract = LessonContract(
        plan_id=uuid.uuid4(),
        teacher_id=teacher.id,
        title="New lesson",
        subject="",
        status=ContractStatus.DRAFT.value,
        version=1,
        brief={},
    )
    db.add(contract)
    return contract
