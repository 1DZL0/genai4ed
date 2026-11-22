"""What a teacher has set about memory, and the deleting of it. The settings are one teacher's
and hold for every lesson of theirs: whether the tutor is told anything from a student's earlier
lessons, how far back, whether the lines a model wrote are among them, and whether the end of
the last lesson is repeated word for word. Hiding removes nothing. Deleting removes what is
remembered of the teacher's students and marks the moment, so that nothing from before it is
counted or recalled again; the lessons themselves stay in the record.
"""

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Class, Enrolment, LearnerNote, MemorySettings, MemoryStart


class Settings(BaseModel):
    """A teacher's memory settings. As they start, memory is as it was before there were any."""

    remember: bool = True
    forget_after_days: int | None = Field(default=None, ge=1, le=365)
    written_lines: bool = True
    recent_lines: int = Field(default=0, ge=0, le=20)
    # Not memory. Kept with these because it was built beside them (see app.agent.harder). The
    # Settings page no longer shows it, so it stays off until the tutor work replaces it.
    harder_questions: bool = False
    # Not memory either: whether the tutor may pitch each step for the student in front of it
    # (see scaffold.PITCH). Off, every step is asked as the lesson has it.
    adapt_to_student: bool = False


async def of(db: AsyncSession, teacher_id: uuid.UUID) -> Settings:
    """The teacher's settings, or the ones everyone starts with when they have set nothing."""
    row = await db.get(MemorySettings, teacher_id)
    return Settings.model_validate(row, from_attributes=True) if row else Settings()


async def save(db: AsyncSession, teacher_id: uuid.UUID, settings: Settings) -> None:
    """The caller commits."""
    row = await db.get(MemorySettings, teacher_id)
    if row is None:
        db.add(MemorySettings(teacher_id=teacher_id, **settings.model_dump()))
        return
    for name, value in settings.model_dump().items():
        setattr(row, name, value)


async def start_of(db: AsyncSession, student_id: uuid.UUID) -> datetime | None:
    """When what is remembered of the student was last deleted, or None when it never was."""
    return await db.scalar(select(MemoryStart.at).where(MemoryStart.student_id == student_id))


def window(settings: Settings, now: datetime | None = None) -> datetime | None:
    """The moment the days set reach back to, or None when no days are set."""
    if settings.forget_after_days is None:
        return None
    return (now or datetime.now(UTC)) - timedelta(days=settings.forget_after_days)


def latest_of(*moments: datetime | None) -> datetime | None:
    """The latest of the moments there are, or None when there are none."""
    return max((m for m in moments if m is not None), default=None)


def _students(teacher_id: uuid.UUID):
    """The students in the teacher's classes."""
    return (
        select(Enrolment.student_id)
        .join(Class, Enrolment.class_id == Class.id)
        .where(Class.teacher_id == teacher_id)
    )


async def remembered(db: AsyncSession, teacher_id: uuid.UUID) -> int:
    """How many of the teacher's students have something remembered about them."""
    return await db.scalar(
        select(func.count(func.distinct(LearnerNote.student_id))).where(
            LearnerNote.student_id.in_(_students(teacher_id))
        )
    )


async def clear(db: AsyncSession, teacher_id: uuid.UUID) -> None:
    """What is remembered of the teacher's students is deleted, every version of it, and the
    moment is kept for each of them. The caller commits."""
    students = sorted(set((await db.scalars(_students(teacher_id))).all()))
    if not students:
        return
    # The database's clock, the one every record's time is from.
    marked = insert(MemoryStart).values(
        [{"student_id": s, "at": func.now(), "by": teacher_id} for s in students]
    )
    await db.execute(
        marked.on_conflict_do_update(
            index_elements=[MemoryStart.student_id],
            set_={"at": marked.excluded.at, "by": marked.excluded.by},
        )
    )
    await db.execute(delete(LearnerNote).where(LearnerNote.student_id.in_(students)))
