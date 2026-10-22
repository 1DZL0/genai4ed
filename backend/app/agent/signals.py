"""Alerts that time answers: struggling clears when the student moves on, off task when they
answer right; and who else in the class slipped on a step."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import EvidenceKind, ExceptionKind, ExceptionStatus, SignalKind
from app.models import EvidenceRecord, Exception_, User


async def students_with_misconception(
    db: AsyncSession, session_id: uuid.UUID, step_index: int
) -> list[str]:
    """Pseudonyms of the students who have shown a misconception on this step."""
    rows = await db.execute(
        select(func.distinct(User.pseudonym))
        .select_from(EvidenceRecord)
        .join(User, User.id == EvidenceRecord.student_id)
        .where(
            EvidenceRecord.session_id == session_id,
            EvidenceRecord.kind == EvidenceKind.SIGNAL.value,
            EvidenceRecord.payload["signal"].as_string() == SignalKind.MISCONCEPTION.value,
            EvidenceRecord.payload["step_index"].as_integer() == step_index,
        )
        .order_by(User.pseudonym)
    )
    return [r[0] for r in rows]


async def let_go(
    db, session, student, kind: ExceptionKind, *, because: str, before_step: int | None = None
) -> None:
    """Close an open alert of this kind for this student: what they did next answered it. The
    record keeps the alert, marked as cleared without the teacher, so the board can let it go
    and the research view can still count it. With `before_step`, only alerts about an
    earlier step (or about no step) go."""
    for alert in (
        await db.scalars(
            select(Exception_).where(
                Exception_.session_id == session.id,
                Exception_.student_id == student.id,
                Exception_.kind == kind.value,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
    ).all():
        about = alert.payload.get("step_index")
        if before_step is not None and isinstance(about, int) and about >= before_step:
            continue
        alert.status = ExceptionStatus.RESOLVED.value
        alert.payload = {
            **alert.payload,
            "cleared_because": because,
            "cleared_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
