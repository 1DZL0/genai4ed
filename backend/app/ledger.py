"""The evidence ledger.

Append-only: rows are written and read, never updated. Everything the note
asks to be recorded goes here - objective and item ids, submitted answers,
correctness, attempts, hints, teacher feedback and interventions - each with
its provenance and its retention class.

Retention is a column, not a promise. Raw exploratory chat expires sooner than
submitted work, and `app.retention` acts on `purge_after`.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import EvidenceKind, RetentionClass
from app.grading import GradeResult
from app.models import EvidenceRecord

# Hints and attempts are part of submitted work; free exploration is not.
RETENTION_BY_KIND: dict[EvidenceKind, RetentionClass] = {
    EvidenceKind.ATTEMPT: RetentionClass.SUBMITTED_WORK,
    EvidenceKind.GRADING_RESULT: RetentionClass.SUBMITTED_WORK,
    EvidenceKind.HINT: RetentionClass.SUBMITTED_WORK,
    EvidenceKind.TEACHER_FEEDBACK: RetentionClass.SUBMITTED_WORK,
    EvidenceKind.TEACHER_INTERVENTION: RetentionClass.SUBMITTED_WORK,
    EvidenceKind.EXPLORATORY_TURN: RetentionClass.EXPLORATORY_CHAT,
    # A written response: what the student hands in is submitted work; the
    # drafts on the way there and their questions to the tutor are not.
    EvidenceKind.SUBMISSION: RetentionClass.SUBMITTED_WORK,
    EvidenceKind.DRAFT: RetentionClass.EXPLORATORY_CHAT,
    EvidenceKind.TUTOR_REQUEST: RetentionClass.EXPLORATORY_CHAT,
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
    item_id: uuid.UUID | None = None,
    objective_id: uuid.UUID | None = None,
    correct: bool | None = None,
    attempt_index: int | None = None,
    payload: dict | None = None,
    provenance: dict | None = None,
) -> EvidenceRecord:
    retention = RETENTION_BY_KIND[kind]
    record = EvidenceRecord(
        session_id=session_id,
        student_id=student_id,
        item_id=item_id,
        objective_id=objective_id,
        kind=kind.value,
        correct=correct,
        attempt_index=attempt_index,
        payload=payload or {},
        provenance=provenance or {},
        retention_class=retention.value,
        purge_after=purge_after(retention),
    )
    db.add(record)
    await db.flush()
    return record


async def attempt_count(db: AsyncSession, student_id: uuid.UUID, item_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count(EvidenceRecord.id)).where(
                EvidenceRecord.student_id == student_id,
                EvidenceRecord.item_id == item_id,
                EvidenceRecord.kind == EvidenceKind.ATTEMPT.value,
            )
        )
    ) or 0


async def incorrect_count(db: AsyncSession, student_id: uuid.UUID, item_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count(EvidenceRecord.id)).where(
                EvidenceRecord.student_id == student_id,
                EvidenceRecord.item_id == item_id,
                EvidenceRecord.kind == EvidenceKind.ATTEMPT.value,
                EvidenceRecord.correct.is_(False),
            )
        )
    ) or 0


def attempt_payload(answer: str, grade: GradeResult) -> dict:
    """What is kept about one submission: the student's own words, and the
    canonical form that was actually compared."""
    return {
        "answer": answer,
        "normalised": grade.normalised,
        "expected_normalised": grade.expected_normalised,
    }
