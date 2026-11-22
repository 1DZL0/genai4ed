"""What a teacher asks the tutor to keep in mind about one of their students for a few days, in
words: "go gently with 7B-06 this week". The class agent passes it on with the days; the tutor
reads it in each of that teacher's lessons until then; the purge removes it after."""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Class, Enrolment, StudentNote, User

# The most days a note is kept, however long the teacher asked for.
LONGEST_DAYS = 30


def today() -> date:
    return datetime.now(UTC).date()


def day(when: date) -> str:
    """A day as the thread and the tutor read it: Friday 27 November."""
    return f"{when:%A} {when.day} {when:%B}"


async def find_student(db: AsyncSession, teacher_id: uuid.UUID, ref: str) -> User | None:
    """The student in one of this teacher's classes with that pseudonym, or None."""
    found = (
        await db.scalars(
            select(User)
            .join(Enrolment, Enrolment.student_id == User.id)
            .join(Class, Class.id == Enrolment.class_id)
            .where(
                Class.teacher_id == teacher_id, func.lower(User.pseudonym) == ref.strip().lower()
            )
            .distinct()
        )
    ).all()
    return found[0] if len(found) == 1 else None


async def keep(
    db: AsyncSession, *, teacher_id: uuid.UUID, student_id: uuid.UUID, text: str, days: int
) -> StudentNote | None:
    """Kept for `days` days, today included, in place of any note before; 0 takes it back."""
    note = await db.scalar(
        select(StudentNote).where(
            StudentNote.teacher_id == teacher_id, StudentNote.student_id == student_id
        )
    )
    if days <= 0:
        if note is not None:
            await db.delete(note)
            await db.flush()
        return None
    until = today() + timedelta(days=min(days, LONGEST_DAYS) - 1)
    if note is None:
        note = StudentNote(teacher_id=teacher_id, student_id=student_id, text=text, until=until)
        db.add(note)
    else:
        note.text, note.until = text, until
    await db.flush()
    return note


async def in_force(
    db: AsyncSession, *, teacher_id: uuid.UUID, student_id: uuid.UUID
) -> StudentNote | None:
    """This teacher's note on this student, while its days last."""
    return await db.scalar(
        select(StudentNote).where(
            StudentNote.teacher_id == teacher_id,
            StudentNote.student_id == student_id,
            StudentNote.until >= today(),
        )
    )


async def purge(db: AsyncSession, *, before: date) -> int:
    """Remove the notes whose last day is before `before`."""
    return (await db.execute(delete(StudentNote).where(StudentNote.until < before))).rowcount
