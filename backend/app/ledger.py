"""The evidence ledger: append-only records of what the agent judged, noticed and was
stopped from doing, each stamped with the date it may be purged."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import EvidenceKind, RetentionClass
from app.models import EvidenceRecord


def purge_after(retention: RetentionClass) -> datetime:
    settings = get_settings()
    days = (
        settings.exploratory_chat_retention_days
        if retention is RetentionClass.EXPLORATORY_CHAT
        else settings.submitted_work_retention_days
    )
    return datetime.now(UTC) + timedelta(days=days)


async def append(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    student_id: uuid.UUID,
    kind: EvidenceKind,
    payload: dict | None = None,
    provenance: dict | None = None,
) -> EvidenceRecord:
    # Every evidence kind is kept as submitted work; only raw chat expires sooner.
    retention = RetentionClass.SUBMITTED_WORK
    record = EvidenceRecord(
        # Stamped here: Postgres now() is the same for every row in one transaction.
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
