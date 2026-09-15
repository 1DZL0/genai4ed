"""A student's record across lessons, and the one way the agent reaches into it.

Three separate questions, kept separate on purpose:

1. What is stored - everything, in the evidence ledger, whatever this module does.
2. What is retrieved - `retrieve`: a small, relevant slice of earlier lessons,
   matched by topic, newest first. It always runs and is always logged in the
   turn's context manifest, so it can be studied.
3. What changes the teaching - only if the lesson's `use_past_lessons` is on
   does the retrieved slice go into the agent's context.

No vector store and no learner profile yet: the concept note asks for evidence
with citations, not a characterisation of a child. `retrieve` is the seam where
semantic retrieval would go.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import EvidenceKind, SignalKind
from app.models import EvidenceRecord

RETRIEVE_LIMIT = 8


@dataclass(frozen=True)
class Recalled:
    record_id: uuid.UUID
    session_id: uuid.UUID
    kind: str
    summary: str


async def retrieve(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    topics: list[str],
    exclude_session_id: uuid.UUID,
    limit: int = RETRIEVE_LIMIT,
) -> list[Recalled]:
    """Judgments and misconceptions from this student's earlier lessons on these topics."""
    wanted = {t.strip().lower() for t in topics if t.strip()}
    if not wanted:
        return []
    rows = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.student_id == student_id,
                EvidenceRecord.session_id != exclude_session_id,
                EvidenceRecord.kind.in_([EvidenceKind.ASSESSMENT.value, EvidenceKind.SIGNAL.value]),
            )
            .order_by(EvidenceRecord.created_at.desc())
            .limit(200)
        )
    ).all()
    found: list[Recalled] = []
    for r in rows:
        tags = {str(t).lower() for t in r.payload.get("topics", [])}
        if not tags & wanted:
            continue
        if r.kind == EvidenceKind.SIGNAL.value:
            if r.payload.get("signal") != SignalKind.MISCONCEPTION.value:
                continue
            summary = f"Earlier misconception: {r.payload.get('note', '')}"
        else:
            summary = (
                f"Earlier, on “{r.payload.get('step_name', '')}”: "
                f"{r.payload.get('judgment', '')}"
                + (f" ({r.payload['misconception']})" if r.payload.get("misconception") else "")
            )
        found.append(Recalled(r.id, r.session_id, r.kind, summary))
        if len(found) >= limit:
            break
    return found
