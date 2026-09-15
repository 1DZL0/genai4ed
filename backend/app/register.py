"""Where every student in a lesson has got to, question by question.

Shared by the live console and the review of a finished lesson, so both show
exactly the same thing. One read of the lesson's attempts and hints, grouped in
memory, rather than a query per student per question on every poll.
"""

import uuid
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import EvidenceKind, ExceptionStatus, ItemKind, Rung, ScoreStatus, rung_index
from app.models import (
    Class,
    ContractItem,
    EvidenceRecord,
    Exception_,
    LessonContract,
    RubricScore,
    Session,
    SessionParticipant,
    User,
)

KNOWN_RUNGS = frozenset(r.value for r in Rung)


class RegisterCell(BaseModel):
    """One student on one task."""

    item_id: uuid.UUID
    kind: str = "short_answer"
    # Short answers: tries. Written responses: times they asked the tutor.
    attempts: int
    # Short answers: answered correctly. Written responses: handed in.
    solved: bool
    # The highest rung of help the tutor actually gave on this task.
    rung: str | None
    # Written responses only.
    words: int = 0
    submitted: bool = False
    score: int | None = None
    score_out_of: int | None = None
    score_confirmed: bool = False


class StudentProgress(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    attempted: int
    correct: int
    attempts: int
    needs_you: bool
    # Every time this student reached the teacher's queue in the lesson, dealt with or not.
    times_needed_you: int
    cells: list[RegisterCell]


@dataclass
class Register:
    contract: LessonContract
    klass: Class | None
    items: list[ContractItem]
    students: list[User]
    progress: list[StudentProgress]
    open_exceptions: list[Exception_]


async def build_register(db: AsyncSession, session: Session) -> Register:
    contract = await db.get(LessonContract, session.contract_id)
    klass = await db.get(Class, session.class_id)
    items = list(
        (
            await db.scalars(
                select(ContractItem)
                .where(ContractItem.contract_id == contract.id)
                .order_by(ContractItem.ordinal)
            )
        ).all()
    )
    students = list(
        (
            await db.scalars(
                select(User)
                .join(SessionParticipant, SessionParticipant.student_id == User.id)
                .where(SessionParticipant.session_id == session.id)
                .order_by(User.pseudonym)
            )
        ).all()
    )
    records = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.kind.in_(
                    [
                        EvidenceKind.ATTEMPT.value,
                        EvidenceKind.HINT.value,
                        EvidenceKind.TUTOR_REQUEST.value,
                        EvidenceKind.DRAFT.value,
                        EvidenceKind.SUBMISSION.value,
                    ]
                ),
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()
    by_cell: dict[tuple[uuid.UUID, uuid.UUID | None], list[EvidenceRecord]] = {}
    for r in records:
        by_cell.setdefault((r.student_id, r.item_id), []).append(r)
    scores = {
        (s.student_id, s.item_id): s
        for s in (
            await db.scalars(select(RubricScore).where(RubricScore.session_id == session.id))
        ).all()
    }

    exceptions = list(
        (
            await db.scalars(
                select(Exception_)
                .where(Exception_.session_id == session.id)
                .order_by(Exception_.priority, Exception_.created_at)
            )
        ).all()
    )
    open_exceptions = [e for e in exceptions if e.status == ExceptionStatus.OPEN.value]
    waiting = {e.student_id for e in open_exceptions}

    progress: list[StudentProgress] = []
    for student in students:
        cells: list[RegisterCell] = []
        for item in items:
            rows = by_cell.get((student.id, item.id), [])
            hint_rungs = [
                Rung(r.payload["rung"])
                for r in rows
                if r.kind == EvidenceKind.HINT.value and r.payload.get("rung") in KNOWN_RUNGS
            ]
            highest = max(hint_rungs, key=rung_index).value if hint_rungs else None
            if item.kind == ItemKind.WRITTEN_RESPONSE.value:
                texts = [
                    r
                    for r in rows
                    if r.kind in (EvidenceKind.DRAFT.value, EvidenceKind.SUBMISSION.value)
                ]
                score = scores.get((student.id, item.id))
                confirmed = score is not None and score.status == ScoreStatus.CONFIRMED.value
                cells.append(
                    RegisterCell(
                        item_id=item.id,
                        kind=item.kind,
                        attempts=sum(1 for r in rows if r.kind == EvidenceKind.TUTOR_REQUEST.value),
                        solved=any(r.kind == EvidenceKind.SUBMISSION.value for r in rows),
                        rung=highest,
                        words=int(texts[-1].payload.get("words", 0)) if texts else 0,
                        submitted=any(r.kind == EvidenceKind.SUBMISSION.value for r in rows),
                        score=(
                            (score.confirmed_total if confirmed else score.suggested_total)
                            if score
                            else None
                        ),
                        score_out_of=(
                            sum(int(c["max"]) for c in (item.rubric or {}).get("criteria", []))
                            or None
                        ),
                        score_confirmed=confirmed,
                    )
                )
                continue
            attempts = [r for r in rows if r.kind == EvidenceKind.ATTEMPT.value]
            cells.append(
                RegisterCell(
                    item_id=item.id,
                    attempts=len(attempts),
                    solved=any(a.correct for a in attempts),
                    rung=highest,
                )
            )
        progress.append(
            StudentProgress(
                student_id=student.id,
                pseudonym=student.pseudonym,
                attempted=sum(1 for c in cells if c.attempts),
                correct=sum(1 for c in cells if c.solved),
                attempts=sum(c.attempts for c in cells),
                needs_you=student.id in waiting,
                times_needed_you=sum(1 for e in exceptions if e.student_id == student.id),
                cells=cells,
            )
        )
    return Register(contract, klass, items, students, progress, open_exceptions)
