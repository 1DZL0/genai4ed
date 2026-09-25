"""The study: the condition each student is assigned per lesson, and the fixed help ladder.

Assignment is a pure function of the seed, the student and how many study lessons
they have had, so it can be re-derived from the export and needs no table of its own.
"""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import SessionParticipant

# One rung per answer the student has given on the step; the first is always an attempt.
LADDER = (
    "attempt",
    "diagnostic_question",
    "conceptual_cue",
    "targeted_hint",
    "analogous_example",
    "partial_step",
    "full_solution",
)

RUNG_WORDS = {
    "attempt": "ask for their own attempt, and give no help yet",
    "diagnostic_question": "a question that finds out where their thinking goes wrong",
    "conceptual_cue": "point to the idea that matters, without applying it for them",
    "targeted_hint": "a hint aimed at the exact place they are stuck",
    "analogous_example": "a worked example of a similar problem, never this one",
    "partial_step": "do one step of this problem with them, and leave the rest",
    "full_solution": "the full solution, explained",
}


def permitted_rung(attempts_on_step: int, *, full_allowed: bool) -> str:
    """The one form of help allowed now; stops short of the solution unless the rules allow it."""
    top = len(LADDER) - 1 if full_allowed else LADDER.index("partial_step")
    return LADDER[min(max(attempts_on_step, 0), top)]


def condition_for(student_id: uuid.UUID, ordinal: int) -> dict:
    """Condition for this student's `ordinal`-th study lesson (from 0); memory flips each time."""
    settings = get_settings()
    digest = hashlib.sha256(f"{settings.study_seed}:{student_id}".encode()).digest()
    return {
        "memory": (digest[0] + ordinal) % 2 == 0,
        "policy": settings.study_policy,
        "supervisor": settings.study_supervisor,
        "lesson_in_study": ordinal + 1,
    }


async def condition(db: AsyncSession, *, session_id: uuid.UUID, student_id: uuid.UUID) -> dict:
    """This student's condition in this lesson, assigned on first use. Empty outside a study."""
    rows = (
        await db.scalars(
            select(SessionParticipant).where(SessionParticipant.student_id == student_id)
        )
    ).all()
    here = next((r for r in rows if r.session_id == session_id), None)
    if here is None:
        return {}
    if not here.condition and get_settings().study_active:
        here.condition = condition_for(student_id, sum(1 for r in rows if r.condition))
        await db.flush()
    return here.condition or {}
