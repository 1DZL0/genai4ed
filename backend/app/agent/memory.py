"""A student's record across lessons: what is recalled for the agent, and what
the teacher is shown. Both are read from the evidence ledger each time; nothing
is stored as a profile.
"""

import re
import textwrap
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import harder, store
from app.enums import Audience, ConversationKind, EvidenceKind, MessageRole, SignalKind
from app.models import Conversation, EvidenceRecord, LessonContract, Session

# The steps of earlier lessons the agent is told about, the latest first.
RETRIEVE_LIMIT = 8
# A step's question is repeated beside its name, cut to this many characters.
QUESTION_LENGTH = 120
# A thing said in the last lesson is repeated whole up to this many characters.
SAID_LENGTH = 300
SAID_BY = {MessageRole.STUDENT.value: "Student", MessageRole.AGENT.value: "Tutor"}
# Two notes on one step are one finding when this share of the shorter one's words are in the
# other. The two wordings of one mistake that were both kept on 8 November share 0.73.
SAME_FINDING = 2 / 3
# The other names a subject goes by. A teacher's own word for it is kept on the lesson; this is
# only for telling that two lessons are in one subject.
SUBJECT_NAMES = {
    "math": "mathematics",
    "maths": "mathematics",
    "pe": "physical education",
    "re": "religious education",
    "dt": "design and technology",
    "d&t": "design and technology",
    "cs": "computer science",
    "ict": "information and communication technology",
}


def subject_key(name: str) -> str:
    """One name for a subject however it was written: "Maths", "math" and "Mathematics" are
    one subject. "" when none was given."""
    key = " ".join(name.lower().split()).rstrip(".")
    return SUBJECT_NAMES.get(key, key)


@dataclass(frozen=True)
class Recalled:
    """One step of an earlier lesson as the agent is told it, and the records it was read from."""

    summary: str
    record_ids: tuple[uuid.UUID, ...]


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
    subject: str,
    topics: list[str],
    exclude_session_id: uuid.UUID,
    since: datetime | None = None,
) -> list[Recalled]:
    """What this student's earlier lessons in this subject, or on one of these topics, found:
    a sentence or two for each step they worked on, the latest first, saying how the step
    ended, in how many tries, and what was still mixed up when they left it. With `since`,
    only what was found after that moment."""
    wanted = {t.strip().lower() for t in topics if t.strip()}
    subject = subject_key(subject)
    if not wanted and not subject:
        return []
    found = select(EvidenceRecord).where(
        EvidenceRecord.student_id == student_id,
        EvidenceRecord.session_id != exclude_session_id,
        EvidenceRecord.kind.in_(
            [
                EvidenceKind.ASSESSMENT.value,
                EvidenceKind.SIGNAL.value,
                EvidenceKind.HARDER_QUESTION.value,
            ]
        ),
    )
    if since is not None:
        found = found.where(EvidenceRecord.created_at > since)
    rows = (await db.scalars(found.order_by(EvidenceRecord.created_at.desc()).limit(200))).all()
    gone = put_right(list(rows))
    lessons = {
        session_id: (brief.get("title") or title, brief, brief.get("subject") or taught_as)
        for session_id, title, taught_as, brief in await db.execute(
            select(Session.id, LessonContract.title, LessonContract.subject, LessonContract.brief)
            .join(LessonContract, Session.contract_id == LessonContract.id)
            .where(Session.id.in_({r.session_id for r in rows}))
        )
    }
    # Each step's records, latest first, and the steps in the order they were last worked on.
    steps: dict[tuple, list[EvidenceRecord]] = {}
    for r in rows:
        tags = {str(t).lower() for t in r.payload.get("topics", [])}
        same_subject = subject and subject == subject_key(lessons[r.session_id][2])
        if not (same_subject or tags & wanted):
            continue
        if (
            r.kind == EvidenceKind.SIGNAL.value
            and r.payload.get("signal") != SignalKind.MISCONCEPTION.value
        ):
            continue
        steps.setdefault((r.session_id, r.payload.get("step_index")), []).append(r)
    told = [
        (session_id, index, records, found)
        for (session_id, index), records in steps.items()
        if (found := _found(records, gone))
    ][:RETRIEVE_LIMIT]
    return [
        Recalled(
            f"{_where(*lessons[session_id][:2], index, records)}: {found}",
            tuple(r.id for r in records),
        )
        for session_id, index, records, found in told
    ]


async def last_said(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    subject: str,
    exclude_session_id: uuid.UUID,
    lines: int,
    since: datetime | None = None,
) -> list[str]:
    """The end of the student's last lesson in this subject, word for word: from their
    `lines`-th line from the end, with the tutor's replies between. Only what they could both
    see. Empty when no words are asked for, the lesson names no subject, or they have had no
    lesson in it. With `since`, only what was said after that moment."""
    subject = subject_key(subject)
    if lines <= 0 or not subject:
        return []
    earlier = await db.execute(
        select(Conversation.id, LessonContract.subject, LessonContract.brief)
        .join(Session, Conversation.session_id == Session.id)
        .join(LessonContract, Session.contract_id == LessonContract.id)
        .where(
            Conversation.kind == ConversationKind.STUDENT.value,
            Conversation.student_id == student_id,
            Conversation.session_id != exclude_session_id,
        )
        .order_by(Conversation.created_at.desc())
    )
    last = next(
        (
            conversation_id
            for conversation_id, taught_as, brief in earlier
            if subject_key((brief or {}).get("subject") or taught_as or "") == subject
        ),
        None,
    )
    if last is None:
        return []
    said = [
        m
        for m in await store.messages(db, last, said_only=True)
        if m.role in SAID_BY
        and m.audience == Audience.ALL.value
        and (since is None or m.created_at > since)
    ]
    theirs = [at for at, m in enumerate(said) if m.role == MessageRole.STUDENT.value]
    if not theirs:
        return []
    return [
        f"{SAID_BY[m.role]}: “{textwrap.shorten(m.text, SAID_LENGTH, placeholder='…')}”"
        for m in said[theirs[-lines:][0] :]
    ]


def _where(title: str, brief: dict, index, records: list[EvidenceRecord]) -> str:
    """The lesson and the step, named so they mean something in another lesson: the step's
    question goes beside its name."""
    listed = brief.get("steps") or []
    if isinstance(index, int) and 0 <= index < len(listed):
        question = textwrap.shorten(listed[index]["goal"], QUESTION_LENGTH, placeholder="…")
        return f"In “{title}”, “{listed[index]['name']}” ({question})"
    name = next((r.payload["step_name"] for r in records if r.payload.get("step_name")), "")
    return f"In “{title}”, “{name}”" if name else f"In “{title}”"


def _found(records: list[EvidenceRecord], gone: set[uuid.UUID]) -> str:
    """What one step's records show, in sentences, or "" when they show nothing to tell.
    `records` are latest first."""
    judgments = [
        r.payload.get("judgment") for r in records if r.kind == EvidenceKind.ASSESSMENT.value
    ]
    mixed_up = held(records, gone)
    said = []
    if judgments:
        said.append(_outcome(judgments[::-1]))
    # Their one try at the tutor's own harder question, which is no part of the step's outcome.
    extra = next((r for r in records if r.kind == EvidenceKind.HARDER_QUESTION.value), None)
    if extra:
        tried = harder.went(extra.payload.get("judgment"))
        said.append(f"Then a harder question of the tutor's own: {tried}")
    if mixed_up:
        said.append("Still mixed up: " + "; ".join(mixed_up))
    return "".join(f"{s}. " for s in said).rstrip()


def _outcome(judgments: list[str]) -> str:
    """The judgments on one step, in the order they were made, as plain words: where the step
    stands at the last one, and the tries it took. Being asked for the why after a right answer
    is judged again, and is not another try."""
    if judgments[-1] == "met":
        first = judgments.index("met") + 1
        return "right first time" if first == 1 else f"right on try {first}"
    tries = "1 try" if len(judgments) == 1 else f"{len(judgments)} tries"
    if judgments[-1] == "partial":
        return f"partly right after {tries}"
    if judgments[-1] == "not_met":
        return f"not right yet after {tries}"
    return f"not clear yet after {tries}"


def held(records: list[EvidenceRecord], gone: set[uuid.UUID]) -> list[str]:
    """The misconceptions in one step's records that were not put right, each said once. A
    judgment that names one raises a signal for it in the same turn, in the same words or the
    agent's own: that is one finding, said in the judgment's words. One named again on a later
    try in other words is one finding too, said in the first wording in `records`, which every
    caller hands over the latest first."""
    judged_turns = {
        r.payload.get("turn_id")
        for r in records
        if r.kind == EvidenceKind.ASSESSMENT.value and r.payload.get("misconception")
    }
    kept: list[str] = []
    for r in records:
        if r.id in gone or r.kind == EvidenceKind.HARDER_QUESTION.value:
            continue
        if r.kind == EvidenceKind.ASSESSMENT.value:
            words = r.payload.get("misconception")
        elif r.payload.get("turn_id") in judged_turns:
            continue
        else:
            words = r.payload.get("note")
        words = (words or "").strip().rstrip(".")
        if words and not any(_same_finding(words, said) for said in kept):
            kept.append(words)
    return kept


def _same_finding(one: str, other: str) -> bool:
    """Whether two notes on one step say the same thing in other words: the tutor names a
    mistake again on the next wrong try, rarely in the words it used before. They do when
    SAME_FINDING of the shorter one's words, small words aside, are in the other."""
    a, b = _telling_words(one), _telling_words(other)
    if not a or not b:
        return one.casefold() == other.casefold()
    return len(a & b) >= SAME_FINDING * min(len(a), len(b))


def _telling_words(text: str) -> set[str]:
    """The words that say what a note is about: the numbers and the words of four letters or
    more, capitals aside."""
    return {w for w in re.findall(r"\w+", text.casefold()) if len(w) > 3 or w.isdigit()}


async def knowledge(db: AsyncSession, *, student_id: uuid.UUID) -> list[dict]:
    """What the assessments show this student knows, topic by topic, citing the records. For
    the teacher's card on the student; the tutor is told what the learner note says."""
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
