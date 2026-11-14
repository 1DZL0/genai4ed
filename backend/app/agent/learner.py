"""The learner note: what a student's next lessons are told about them. One note per student,
in two parts: how they learn, which goes into every lesson, and what they know, a subject at
a time. The researchers decide what goes in; a teacher can read it and cannot change it.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LearnerNote, User

PARTS = ("worked_out", "written", "knows")


async def latest(db: AsyncSession, student_id: uuid.UUID) -> LearnerNote | None:
    """The student's note as it stands, or None when nothing has been written about them."""
    return await db.scalar(
        select(LearnerNote)
        .where(LearnerNote.student_id == student_id)
        .order_by(LearnerNote.version.desc())
        .limit(1)
    )


async def write(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    worked_out: list[str] | None = None,
    written: list[str] | None = None,
    knows: list[dict] | None = None,
) -> LearnerNote | None:
    """The student's note with the given parts changed, as a new version; a part left out is
    carried over from the version before. Nothing is written when nothing changed, so a lesson
    that found nothing new leaves the note as it was. The caller commits."""
    # One writer at a time for a student, so two lessons ending together cannot both take the
    # same version number.
    await db.execute(select(User.id).where(User.id == student_id).with_for_update())
    before = await latest(db, student_id)
    given = {"worked_out": worked_out, "written": written, "knows": knows}
    parts = {
        name: (getattr(before, name) if before else []) if given[name] is None else given[name]
        for name in PARTS
    }
    if before is None and not any(parts.values()):
        return None
    if before is not None and all(getattr(before, name) == parts[name] for name in PARTS):
        return before
    note = LearnerNote(
        student_id=student_id,
        version=before.version + 1 if before else 1,
        session_id=session_id,
        **parts,
    )
    db.add(note)
    await db.flush()
    return note
