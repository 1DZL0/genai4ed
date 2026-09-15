"""The evidence ledger.

Append-only: rows are written and read, never updated. What the class agent
judged, noticed and was stopped from doing, where each student moved in the
activity, and what the teacher told the agent - each with its provenance and
its retention class.

Retention is a column, not a promise. Raw chat (in `messages`) expires sooner
than the record of the lesson.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import EvidenceKind, RetentionClass
from app.models import EvidenceRecord

RETENTION_BY_KIND: dict[EvidenceKind, RetentionClass] = {
    EvidenceKind.ASSESSMENT: RetentionClass.SUBMITTED_WORK,
    EvidenceKind.SIGNAL: RetentionClass.SUBMITTED_WORK,
    EvidenceKind.POLICY_EVENT: RetentionClass.SUBMITTED_WORK,
    EvidenceKind.STEP_CHANGE: RetentionClass.SUBMITTED_WORK,
    EvidenceKind.TEACHER_GUIDANCE: RetentionClass.SUBMITTED_WORK,
}


def purge_after(retention: RetentionClass, now: datetime | None = None) -> datetime:
    settings = get_settings()
    days = (
        settings.exploratory_chat_retention_days
        if retention is RetentionClass.EXPLORATORY_CHAT
        else settings.submitted_work_retention_days
    )
    return (now or datetime.now(UTC)) + timedelta(days=days)


async def append(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    student_id: uuid.UUID,
    kind: EvidenceKind,
    payload: dict | None = None,
    provenance: dict | None = None,
) -> EvidenceRecord:
    retention = RETENTION_BY_KIND[kind]
    record = EvidenceRecord(
        # Stamped here, not by the database: Postgres's now() is the same for
        # every row in a transaction, and one turn can record several things.
        created_at=datetime.now(UTC),
        session_id=session_id,
        student_id=student_id,
        kind=kind.value,
        payload=payload or {},
        provenance=provenance or {},
        retention_class=retention.value,
        purge_after=purge_after(retention),
    )
    db.add(record)
    await db.flush()
    return record
