"""A student's record across lessons: what is recalled for the agent, and what
the teacher is shown. Both are read from the evidence ledger each time; nothing
is stored as a profile.
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


def put_right(records: list[EvidenceRecord]) -> set[uuid.UUID]:
    """The misconceptions in `records` (named in an assessment, or raised as a signal) that the
    same pupil has since put right: a later answer on the same step, in the same lesson, judged
    met. A slip corrected in the next turn is not a misconception they hold."""
    met: dict[tuple, list] = {}
    for r in records:
        if r.kind == EvidenceKind.ASSESSMENT.value and r.payload.get("judgment") == "met":
            key = (r.session_id, r.student_id, r.payload.get("step_index"))
            met.setdefault(key, []).append(r.created_at)
    gone = set()
    for r in records:
        named = (r.kind == EvidenceKind.ASSESSMENT.value and r.payload.get("misconception")) or (
            r.kind == EvidenceKind.SIGNAL.value
            and r.payload.get("signal") == SignalKind.MISCONCEPTION.value
        )
        key = (r.session_id, r.student_id, r.payload.get("step_index"))
        if named and any(at > r.created_at for at in met.get(key, [])):
            gone.add(r.id)
    return gone


async def retrieve(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    topics: list[str],
    exclude_session_id: uuid.UUID,
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
    gone = put_right(list(rows))
    found: list[Recalled] = []
    for r in rows:
        tags = {str(t).lower() for t in r.payload.get("topics", [])}
        if not tags & wanted:
            continue
        if r.kind == EvidenceKind.SIGNAL.value:
            if r.payload.get("signal") != SignalKind.MISCONCEPTION.value or r.id in gone:
                continue
            summary = f"Earlier misconception: {r.payload.get('note', '')}"
        else:
            held = r.payload.get("misconception") if r.id not in gone else None
            summary = (
                f"Earlier, on “{r.payload.get('step_name', '')}”: "
                f"{r.payload.get('judgment', '')}" + (f" ({held})" if held else "")
            )
        found.append(Recalled(r.id, r.session_id, r.kind, summary))
        if len(found) >= RETRIEVE_LIMIT:
            break
    return found


async def knowledge(
    db: AsyncSession, *, student_id: uuid.UUID, exclude_session_id: uuid.UUID | None = None
) -> list[dict]:
    """What the assessments show this student knows, topic by topic, citing the records."""
    rows = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.student_id == student_id,
                EvidenceRecord.kind == EvidenceKind.ASSESSMENT.value,
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()
    gone = put_right(list(rows))
    topics: dict[str, dict] = {}
    for r in rows:
        if r.session_id == exclude_session_id:
            continue
        for tag in r.payload.get("topics", []):
            t = topics.setdefault(
                str(tag).lower(),
                {
                    "topic": str(tag).lower(),
                    "judged": 0,
                    "met": 0,
                    "misconceptions": [],
                    "last_seen": None,
                    "evidence_ids": [],
                },
            )
            t["judged"] += 1
            t["met"] += r.payload.get("judgment") == "met"
            note = r.payload.get("misconception")
            if note and r.id not in gone and note not in t["misconceptions"]:
                t["misconceptions"].append(note)
            t["last_seen"] = r.created_at.isoformat()
            t["evidence_ids"].append(str(r.id))
    # Tags that cite exactly the same records are one row, not several.
    merged: dict[tuple, dict] = {}
    for t in topics.values():
        key = tuple(t["evidence_ids"])
        if key in merged:
            merged[key]["topic"] += ", " + t["topic"]
        else:
            merged[key] = t
    return sorted(merged.values(), key=lambda t: t["last_seen"], reverse=True)
