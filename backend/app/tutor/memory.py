"""Durable memory as an evidence ledger (concept note S4).

Nothing here is stored. A recurring misconception is *recomputed* on every turn
from ordinary queries over the ledger, and it travels with the record ids that
support it and a confidence the teacher can see. That is the difference between
an inference the platform can show its working for and a permanent
characterisation of a fourteen-year-old, and the note asks for the former.

Retrieval is by objective tag and a SQL `order by`. No vector database, no
associative memory, no knowledge tracing - the note rules all three out.

`MemoryProvider` is also the seam the later crossover needs: `NullMemoryProvider`
is a tutor with no history, `LedgerMemoryProvider` is the same tutor with a
compact evidence card, and that is exactly the comparison S5 describes.
"""

import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import EvidenceKind
from app.models import EvidenceRecord

DEFAULT_WINDOW = 12


@dataclass(frozen=True)
class MisconceptionSignal:
    code: str
    occurrences: int
    considered: int
    supporting_record_ids: tuple[uuid.UUID, ...]

    @property
    def confidence(self) -> float:
        """Share of recent diagnoses that named this code.

        Deliberately a ratio anyone can check against the cited records rather
        than a fitted score nobody can argue with.
        """
        return round(self.occurrences / self.considered, 2) if self.considered else 0.0


@dataclass(frozen=True)
class EvidenceLine:
    record_id: uuid.UUID
    kind: str
    correct: bool | None
    detail: str


@dataclass(frozen=True)
class EvidenceCard:
    student_id: uuid.UUID
    objective_id: uuid.UUID | None
    lines: tuple[EvidenceLine, ...] = ()
    recurring: MisconceptionSignal | None = None

    def summary_text(self) -> str:
        """The compact form handed to the model. Prior answers only - never the
        teacher's expected answer."""
        if not self.lines:
            return "No previous work on this objective."
        parts = [
            f"- {line.detail}" + ("" if line.correct is None else f" ({_verdict(line.correct)})")
            for line in self.lines
        ]
        if self.recurring:
            parts.append(
                f"- Recurring: {self.recurring.code} "
                f"({self.recurring.occurrences}/{self.recurring.considered} recent diagnoses)"
            )
        return "\n".join(parts)


class MemoryProvider(Protocol):
    async def card(
        self,
        db: AsyncSession,
        student_id: uuid.UUID,
        objective_id: uuid.UUID | None,
        min_occurrences: int = 2,
    ) -> EvidenceCard: ...


class NullMemoryProvider:
    """A tutor with no access to the student's history.

    The control arm, and the safe default if evidence retrieval must ever be
    switched off for a class or a study condition.
    """

    async def card(
        self,
        db: AsyncSession,
        student_id: uuid.UUID,
        objective_id: uuid.UUID | None,
        min_occurrences: int = 2,
    ) -> EvidenceCard:
        return EvidenceCard(student_id=student_id, objective_id=objective_id)


class LedgerMemoryProvider:
    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        self._window = window

    async def card(
        self,
        db: AsyncSession,
        student_id: uuid.UUID,
        objective_id: uuid.UUID | None,
        min_occurrences: int = 2,
    ) -> EvidenceCard:
        query = (
            select(EvidenceRecord)
            .where(
                EvidenceRecord.student_id == student_id,
                EvidenceRecord.kind.in_([EvidenceKind.ATTEMPT.value, EvidenceKind.HINT.value]),
            )
            .order_by(EvidenceRecord.created_at.desc())
            .limit(self._window)
        )
        if objective_id is not None:
            query = query.where(EvidenceRecord.objective_id == objective_id)

        records = list(reversed((await db.scalars(query)).all()))

        lines = tuple(
            EvidenceLine(
                record_id=r.id,
                kind=r.kind,
                correct=r.correct,
                detail=_detail(r),
            )
            for r in records
        )
        return EvidenceCard(
            student_id=student_id,
            objective_id=objective_id,
            lines=lines,
            recurring=_recurring(records, min_occurrences),
        )


def _verdict(correct: bool) -> str:
    return "correct" if correct else "incorrect"


def _detail(record: EvidenceRecord) -> str:
    if record.kind == EvidenceKind.ATTEMPT.value:
        return f"answered {record.payload.get('answer', '')!r}"
    code = record.payload.get("misconception_code")
    rung = record.payload.get("rung", "help")
    return f"given {rung}" + (f", diagnosed {code}" if code else "")


def _recurring(records: list[EvidenceRecord], min_occurrences: int) -> MisconceptionSignal | None:
    diagnosed = [
        r
        for r in records
        if r.kind == EvidenceKind.HINT.value and r.payload.get("misconception_code")
    ]
    if not diagnosed:
        return None

    counts = Counter(r.payload["misconception_code"] for r in diagnosed)
    code, occurrences = counts.most_common(1)[0]
    if occurrences < min_occurrences:
        return None

    return MisconceptionSignal(
        code=code,
        occurrences=occurrences,
        considered=len(diagnosed),
        supporting_record_ids=tuple(
            r.id for r in diagnosed if r.payload["misconception_code"] == code
        ),
    )
