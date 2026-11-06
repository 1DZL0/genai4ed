"""The teacher's lessons as records: versions, drafts, what they have and what is running.

A lesson is a plan with versions; the current version is the open draft, else the newest
approved one. Runs whose time is up are closed here: there is no timer, every path that
reads a session closes it first if its deadline has passed, and `closed_at` records the
deadline itself. Nothing here talks to the model.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
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


# When a lesson's time runs out the pupils' boxes close and the teacher is asked to end it or
# add minutes. Only a lesson nobody decided on for this long is ended by the clock itself.
GRACE_AFTER_TIME_UP = timedelta(hours=2)


def time_is_up(session: Session, now: datetime | None = None) -> bool:
    """A running lesson past its deadline: the pupils wait, the teacher decides."""
    return (
        session.status == SessionStatus.OPEN.value
        and session.closes_at is not None
        and session.closes_at <= (now or datetime.now(UTC))
    )


async def close_expired(db: AsyncSession, session_id: uuid.UUID | None = None) -> None:
    """Close every session that ran out of time long enough ago that nobody is deciding on
    it (see GRACE_AFTER_TIME_UP), or just `session_id`, and say so in the teacher's thread,
    so a lesson the clock ended is never a mystery."""
    # The thread writes events; it imports this module, so the import lives here.
    from app.agent import thread

    # One conditional update, not a read then a write: every pupil's poll runs this sweep, and
    # requests that meet the same expired lesson at once must close it, and tell the teacher,
    # once. Only the rows this statement changed come back.
    closing = (
        update(Session)
        .where(
            # A scheduled lesson has no deadline until it starts.
            Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            Session.closes_at <= datetime.now(UTC) - GRACE_AFTER_TIME_UP,
        )
        .values(status=SessionStatus.CLOSED.value, closed_at=Session.closes_at)
        .returning(Session)
        .execution_options(synchronize_session=False)
    )
    if session_id is not None:
        closing = closing.where(Session.id == session_id)
    sessions = (await db.scalars(closing, execution_options={"populate_existing": True})).all()
    if not sessions:
        return
    for session in sessions:
        klass = await db.get(Class, session.class_id)
        teacher = await db.get(User, klass.teacher_id) if klass else None
        contract = await db.get(LessonContract, session.contract_id)
        if teacher is not None:
            title = contract.title if contract else "The lesson"
            await thread.event(
                db,
                teacher,
                text=(
                    f"“{title}” ended on its own, two hours after its time ran out with nobody "
                    "ending it or adding time. Press Write the summary for how the class did "
                    "and a note on each student."
                ),
                session_id=str(session.id),
            )
    await db.commit()


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
