"""The learner note: what a student's next lessons are told about them. One note per student,
in two parts: how they learn, which goes into every lesson, and what they know, a subject at
a time. The researchers decide what goes in; a teacher can read it and cannot change it.

Two of its three parts are counted from the record, with no model asked: how much help the
student needs to get a step right and whether they finish, and what they know. They are
worked out again when a lesson ends and when one starts.

The third is written by the end-of-lesson review: a few lines on how the student learns. The
server keeps at most four short ones and drops any that copies what the student wrote.
"""

import re
import statistics
import textwrap
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import memory
from app.enums import EvidenceKind, LearningStatus, SessionStatus, SignalKind
from app.models import (
    AgentTurn,
    EvidenceRecord,
    LearnerNote,
    LearningState,
    LessonContract,
    Session,
    SessionParticipant,
    User,
)

PARTS = ("worked_out", "written", "knows")
# "Usually" is said from this many steps got right. With fewer, the line says what happened.
USUALLY_FROM = 3
# What they know in one subject: at most this many lines, each at most this long, with at most
# this many things still mixed up on a line.
KNOWS_LINES = 4
LINE_LENGTH = 200
MIXED_UP_ON_A_LINE = 3
# What the tutor's help on a step is counted as, in the lesson's own record of the step.
HELP = ("hints", "examples", "worked")
# What the review writes on how they learn: at most this many lines, each at most this long. A
# line with this many words in a row from what the student wrote is not kept.
WRITTEN_LINES = 4
WRITTEN_LENGTH = 140
COPIED_WORDS = 5


@dataclass(frozen=True)
class Step:
    """One step of a lesson as the record has it for one student."""

    # In the order they were made.
    judgments: tuple[str, ...]
    # The hints, worked examples and worked steps the tutor gave on it.
    help: int = 0
    # What was still mixed up when they left it.
    held: tuple[str, ...] = ()


@dataclass(frozen=True)
class Lesson:
    """One lesson as the record has it for one student: the steps they were judged on, or had
    a misconception noticed on."""

    subject: str
    topics: tuple[str, ...]
    steps: tuple[Step, ...]
    ended: bool
    finished: bool


async def latest(db: AsyncSession, student_id: uuid.UUID) -> LearnerNote | None:
    """The student's note as it stands, or None when nothing has been written about them."""
    return await db.scalar(
        select(LearnerNote)
        .where(LearnerNote.student_id == student_id)
        .order_by(LearnerNote.version.desc())
        .limit(1)
    )


def for_lesson(note: LearnerNote | None, subject: str) -> tuple[list[str], list[str]]:
    """The note as a lesson in `subject` is told it: how the student learns, which goes into
    every lesson, and what they know in this subject only. A lesson that names no subject is
    told nothing they know."""
    if note is None:
        return [], []
    key = memory.subject_key(subject)
    knows = [
        line
        for known in note.knows
        if key and memory.subject_key(known["subject"]) == key
        for line in known["lines"]
    ]
    return [*note.worked_out, *note.written], knows


def as_read(note: LearnerNote | None) -> dict | None:
    """The whole note as a person reads it: how the student learns, then what they know a
    subject at a time. Words only, so a screen has nothing to edit it by. None when nothing is
    kept about them."""
    if note is None or not (note.worked_out or note.written or note.knows):
        return None
    return {
        "learns": [*note.worked_out, *note.written],
        "knows": [{"subject": k["subject"], "lines": list(k["lines"])} for k in note.knows],
    }


async def write(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    worked_out: list[str] | None = None,
    written: list[str] | None = None,
    knows: list[dict] | None = None,
) -> LearnerNote | None:
    """The student's note with the given parts changed, as a new version; a part left out is
    carried over from the version before. Nothing is written when nothing changed, so a lesson
    that found nothing new leaves the note as it was. The caller commits."""
    # One writer at a time for a student, so two lessons ending together cannot both take the
    # same version number. The lock is the kind that lets rows pointing at the student still be
    # added, so a turn of theirs in another lesson does not wait for the note.
    await db.execute(select(User.id).where(User.id == student_id).with_for_update(key_share=True))
    before = await latest(db, student_id)
    given = {"worked_out": worked_out, "written": written, "knows": knows}
    parts = {
        name: (getattr(before, name) if before else []) if given[name] is None else given[name]
        for name in PARTS
    }
    if before is None and not any(parts.values()):
        return None
    if before is not None and all(getattr(before, name) == parts[name] for name in PARTS):
        return before
    note = LearnerNote(
        student_id=student_id,
        version=before.version + 1 if before else 1,
        session_id=session_id,
        **parts,
    )
    db.add(note)
    await db.flush()
    return note


async def refresh(
    db: AsyncSession, *, student_id: uuid.UUID, session_id: uuid.UUID | None = None
) -> LearnerNote | None:
    """The parts of the note that are counted from the record, worked out again and kept as a
    new version if they changed. `session_id` is the lesson that was ending or starting. The
    caller commits."""
    lessons = await _lessons(db, student_id)
    return await write(
        db,
        student_id=student_id,
        session_id=session_id,
        worked_out=how_they_learn(lessons),
        knows=what_they_know(lessons),
    )


async def refresh_lesson(db: AsyncSession, session_id: uuid.UUID) -> None:
    """The same for every student in a lesson. The caller commits."""
    students = await db.scalars(
        select(SessionParticipant.student_id)
        .where(SessionParticipant.session_id == session_id)
        # Always in one order, so two lessons that share students cannot wait on each other.
        .order_by(SessionParticipant.student_id)
    )
    for student_id in students.all():
        await refresh(db, student_id=student_id, session_id=session_id)


async def keep_written(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    session_id: uuid.UUID,
    lines: list[str],
    wrote: Iterable[str],
) -> LearnerNote | None:
    """The lines the end-of-lesson review wrote on how a student learns, kept as that part of
    their note. `wrote` is what the students wrote in the lesson (`wrote_in`). With no line
    worth keeping, what was written before stays: neither a review that said nothing nor one
    that only copied a student can wipe it. The caller commits."""
    kept = lines_to_keep(lines, wrote)
    if not kept:
        return None
    return await write(db, student_id=student_id, session_id=session_id, written=kept)


def lines_to_keep(lines: Iterable[str], wrote: Iterable[str]) -> list[str]:
    """The lines on how a student learns that are kept, out of those a model wrote: tidied, each
    said once, none with COPIED_WORDS words in a row from what a student wrote, then the first
    few, each cut to length. So what a student types cannot come back as a line in a note."""
    theirs = {run for text in wrote for run in _runs(text)}
    kept: list[str] = []
    said: set[str] = set()
    for line in lines:
        tidy = " ".join(line.split())
        if not tidy or tidy.casefold() in said or theirs.intersection(_runs(tidy)):
            continue
        said.add(tidy.casefold())
        kept.append(textwrap.shorten(tidy, WRITTEN_LENGTH, placeholder="…"))
    return kept[:WRITTEN_LINES]


def _runs(text: str) -> set[tuple[str, ...]]:
    """Every run of COPIED_WORDS words in a row in `text`, capitals and punctuation aside."""
    words = re.findall(r"\w+", text.casefold())
    return {tuple(words[i : i + COPIED_WORDS]) for i in range(len(words) - COPIED_WORDS + 1)}


async def wrote_in(db: AsyncSession, session_id: uuid.UUID) -> list[str]:
    """What the students wrote in the lesson, as far as it is still kept: what they typed, which
    the purge takes out of the turns after a few days, and the quotes their judgments were made
    on, which the record keeps and the review is shown. Every student's, not one's: the review
    reads the whole class at once, so a line about one student is checked against them all."""
    typed = await db.scalars(
        select(AgentTurn.request).where(
            AgentTurn.session_id == session_id, AgentTurn.mode == "student"
        )
    )
    quoted = await db.scalars(
        select(EvidenceRecord.payload).where(
            EvidenceRecord.session_id == session_id,
            EvidenceRecord.kind == EvidenceKind.ASSESSMENT.value,
        )
    )
    words = [(request or {}).get("text") for request in typed.all()]
    words += [(payload or {}).get("evidence_quote") for payload in quoted.all()]
    return [str(text) for text in words if text]


def how_they_learn(lessons: list[Lesson]) -> list[str]:
    """How much help the student needs to get a step right, and whether they finish their
    lessons. `lessons` are the latest first."""
    judged = [step for lesson in lessons for step in lesson.steps if step.judgments]
    if not judged:
        return []
    right = [step for step in judged if step.judgments[-1] == "met"]
    lines = [
        _help_needed(right)
        if right
        else f"Has not got a step right yet ({_counted(len(judged), 'step')} tried)."
    ]
    # A lesson still running is not one they did not finish.
    over = [
        lesson
        for lesson in lessons
        if lesson.ended and any(step.judgments for step in lesson.steps)
    ]
    if len(over) == 1:
        finished = "Finished" if over[0].finished else "Did not finish"
        lines.append(f"{finished} their one lesson so far.")
    elif over:
        finished = sum(lesson.finished for lesson in over)
        lines.append(f"Finished {finished} of their {len(over)} lessons.")
    return lines


def _help_needed(right: list[Step]) -> str:
    """The middle one of the steps got right: the try it was got right on, and the help given
    on it. With an even number the lower middle is taken, so the line never says more help
    than half the steps took. Being asked for the why after a right answer is not another try."""
    tries = statistics.median_low(step.judgments.index("met") + 1 for step in right)
    helped = statistics.median_low(step.help for step in right)
    usually = len(right) >= USUALLY_FROM
    on = "on the first try" if tries == 1 else f"on try {tries}"
    counted = f"(from {_counted(len(right), 'step')})"
    if helped:
        times = {1: "once", 2: "twice"}.get(helped, f"{helped} times")
        needs = "Usually needs" if usually else "Needed"
        return f"{needs} help {times} before getting a step right, {on} {counted}."
    return f"{'Usually gets' if usually else 'Got'} a step right {on}, without help {counted}."


def what_they_know(lessons: list[Lesson]) -> list[dict]:
    """What the record shows the student knows, a subject at a time and a topic a line: the
    steps they got right out of those judged, and what is still mixed up. `lessons` are the
    latest first, and so are the subjects and the lines."""
    subjects: dict[str, tuple[str, list[Lesson]]] = {}
    for lesson in lessons:
        # The subject goes by the word the latest lesson used for it.
        key = memory.subject_key(lesson.subject)
        subjects.setdefault(key, (lesson.subject, []))[1].append(lesson)
    known = [{"subject": name, "lines": _lines(taught)} for name, taught in subjects.values()]
    return [subject for subject in known if subject["lines"]]


def _lines(lessons: list[Lesson]) -> list[str]:
    """One subject's lines. Topics taught in exactly the same lessons are one line, and a thing
    mixed up is said once, on the first line it belongs to."""
    taught_in: dict[str, list[int]] = {}
    for at, lesson in enumerate(lessons):
        for topic in lesson.topics:
            taught_in.setdefault(topic, []).append(at)
    together: dict[tuple[int, ...], list[str]] = {}
    for topic, where in taught_in.items():
        together.setdefault(tuple(where), []).append(topic)
    lines: list[str] = []
    said: set[str] = set()
    for where, topics in together.items():
        steps = [step for at in where for step in lessons[at].steps]
        judged = [step for step in steps if step.judgments]
        mixed_up = []
        for words in (words for step in steps for words in step.held):
            if words.casefold() not in said and len(mixed_up) < MIXED_UP_ON_A_LINE:
                said.add(words.casefold())
                mixed_up.append(words)
        found = []
        if judged:
            right = sum(step.judgments[-1] == "met" for step in judged)
            found.append(f"{right} of {_counted(len(judged), 'step')} right")
        if mixed_up:
            found.append("Still mixed up: " + "; ".join(mixed_up))
        if found:
            line = f"{', '.join(topics)}: {'. '.join(found)}."
            lines.append(textwrap.shorten(line, LINE_LENGTH, placeholder="…"))
    return lines[:KNOWS_LINES]


def _counted(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


async def _lessons(db: AsyncSession, student_id: uuid.UUID) -> list[Lesson]:
    """The student's lessons as the record has them, the latest first."""
    rows = [
        r
        for r in await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.student_id == student_id,
                EvidenceRecord.kind.in_([EvidenceKind.ASSESSMENT.value, EvidenceKind.SIGNAL.value]),
            )
            .order_by(EvidenceRecord.created_at.desc())
        )
        if r.kind == EvidenceKind.ASSESSMENT.value
        or r.payload.get("signal") == SignalKind.MISCONCEPTION.value
    ]
    if not rows:
        return []
    gone = memory.put_right(rows)
    # Each lesson's records a step at a time, every list the latest first.
    by_lesson: dict[uuid.UUID, dict[object, list[EvidenceRecord]]] = {}
    for r in rows:
        by_lesson.setdefault(r.session_id, {}).setdefault(r.payload.get("step_index"), []).append(r)
    taught = {
        session_id: (status, brief.get("title") or title, brief.get("subject") or subject or "")
        for session_id, status, title, subject, brief in await db.execute(
            select(
                Session.id,
                Session.status,
                LessonContract.title,
                LessonContract.subject,
                LessonContract.brief,
            )
            .join(LessonContract, Session.contract_id == LessonContract.id)
            .where(Session.id.in_(list(by_lesson)))
        )
    }
    states = {
        state.session_id: state
        for state in await db.scalars(
            select(LearningState).where(
                LearningState.student_id == student_id,
                LearningState.session_id.in_(list(by_lesson)),
            )
        )
    }
    return [
        _lesson(*taught[session_id], steps, states.get(session_id), gone)
        for session_id, steps in by_lesson.items()
    ]


def _lesson(
    status: str,
    title: str,
    subject: str,
    steps: dict[object, list[EvidenceRecord]],
    state: LearningState | None,
    gone: set[uuid.UUID],
) -> Lesson:
    kept = state.steps if state else []
    topics = dict.fromkeys(
        tag
        for records in steps.values()
        for r in records
        for t in r.payload.get("topics", [])
        if (tag := str(t).strip().lower())
    )
    return Lesson(
        subject=subject,
        # A lesson with no topics is known by its title.
        topics=tuple(topics) or (title,),
        steps=tuple(
            Step(
                judgments=tuple(
                    r.payload.get("judgment")
                    for r in reversed(records)
                    if r.kind == EvidenceKind.ASSESSMENT.value
                ),
                help=sum(kept[index].get(kind, 0) for kind in HELP)
                if isinstance(index, int) and 0 <= index < len(kept)
                else 0,
                held=tuple(memory.held(records, gone)),
            )
            for index, records in steps.items()
        ),
        ended=status == SessionStatus.CLOSED.value,
        finished=state is not None and state.status == LearningStatus.COMPLETED.value,
    )
