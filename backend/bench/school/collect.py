"""Collecting the records. Once the pupils and the teacher have played the lessons, what the
platform kept of them is read from its database into plain data (`RunData`), beside the driver's
own logs. The checks work from this alone: no model judges anything.

Only the run's own records are read: those of its lessons (the sessions named in the logs and in
the lessons' facts) and of its pupils (the cast). Nothing here writes, flushes or commits, and
every record is read afresh from the database, whatever the caller's session already holds.
Every id is text and every time ISO text, so the whole of it can be written out as JSON.

A tutor turn carries the agent line its reply wrote (the tutor's message with the turn's id)
and what the pupil said in it (the turn's own request), both from the platform's records, never
from the log. A pupil's request that writes no new line (Ask my teacher, a tap on a reply, a
page read after signing back in) shows the line before it again: a Sent is a turn's only when it
is the move that wrote that line.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.student_mode import INTENTS
from app.enums import EvidenceKind, MessageRole
from app.models import (
    AgentTurn,
    EvidenceRecord,
    Exception_,
    LearnerNote,
    LearnerNoteLine,
    LearningState,
    LessonContract,
    LessonOutcome,
    Message,
    Session,
    StudentNote,
    TeacherAccessLog,
    User,
)
from app.research_view import _reply
from bench.school.driver import LessonLog, Sent
from bench.school.teacher import Drafted

# Where a turn's manifest lists the records of earlier lessons it was shown: today's name, and
# the one turns had before the learner note's lines were kept.
EVIDENCE_IDS = ("retrieved_ids", "knowledge_evidence_ids")


@dataclass
class Turn:
    """One reply of the tutor's to a pupil, as the platform recorded it (`AgentTurn`, mode
    "student"), the pupil by pseudonym:
    - `manifest`: what the tutor was shown; `reply`: the reply as the model sent it, as JSON;
    - `conflicts`: the rules it broke; `outcome`: "ok" (it went out), "regenerated" or
      "withheld"; `leak`: the leak check, "passed", "failed" or "skipped";
    - `said`: what the pupil said in that turn, as their page shows it: their words, or the
      words of the help button they pressed; "" for a turn that answered nothing of theirs (the
      opening, a move between steps, the teacher's guidance);
    - `reply_text`, `agent_line_id`: the words and id of the agent line it wrote, as the pupil
      saw it ("" and None when the model gave no answer);
    - `at`: when it was recorded, on the database's clock: the start of the transaction that
      wrote it. The platform hands its connection back while the model writes, so that
      transaction begins once the model has answered: `at` is after the pupil's request and
      the model's reply, not when the request was sent;
    - `request`: the request as the platform kept it (the pupil's words and button, the
      teacher's guidance, the step); `usage`: the tokens the model reported; `helped`: the
      pupil's tap on its line (True: it helped, False: not really, None: no tap). These three
      are for the checks on the teacher's guidance and the pupils' taps, and the report's cost;
    - `call`, `changed`: the tutor's pitch call and the things it changed, as kept with its
      line (`Message.data`), which is what a steered pupil was steered by. A held-back reply's
      line keeps none, whatever the draft said (that is in `reply`)."""

    id: str
    session_id: str
    pupil: str
    model: str
    prompt_version: str
    manifest: dict
    reply: dict
    conflicts: list[str]
    outcome: str
    leak: str
    latency_ms: int
    said: str
    reply_text: str
    agent_line_id: str | None
    at: str
    request: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    helped: bool | None = None
    call: str | None = None
    changed: list[str] = field(default_factory=list)


@dataclass
class LessonFacts:
    """One lesson of the run as the runner knows it: its key, the session it ran as ("" when it
    never ran), its subject, the pupils' age, how many steps it has, its rules and brief as the
    platform keeps them, its teacher's name, and how drafting it went (None when it was not
    drafted)."""

    key: str
    session_id: str
    subject: str
    age: int | None
    steps: int
    rules: dict
    brief: dict
    teacher: str
    drafted: Drafted | None


@dataclass
class RunData:
    """Everything the checks and the report read about a run.

    From the runner and the driver: the lessons; every message the pupils sent, every lesson's
    events then the runner's probes (`extra_events`), the class view's timings and the errors,
    each in log order; the teacher's replies; and the cast, every pupil's pseudonym to who they
    are (a pupil in several lessons as the latest describes them).

    From the platform's records, all of the run's lessons and pupils, oldest first:
    - `turns`: the tutor's turns (see `Turn`);
    - `alerts`: the teacher's queue (`Exception_`): {"id", "session_id", "pupil", "kind",
      "status", "summary", "payload", "at", "acknowledged_at"};
    - `access`: what the teacher did that touched a pupil's record, in the run's lessons
      (`TeacherAccessLog`): {"teacher", "session_id", "pupil", "action", "detail", "at"}, the
      pupil None for an action on the whole class;
    - `outcomes` (`LessonOutcome`): {"session_id", "pupil", "status", "suggested",
      "confirmed", "confirmed_at"};
    - `notes`, what a teacher asked the tutor to keep in mind about a pupil (`StudentNote`):
      {"teacher", "pupil", "text", "until", "at"}, `until` the last day, as an ISO date;
    - `note_lines`: each pupil's pseudonym to every distinct learner note line written for them
      (see `note_lines_of`), with the lines captured before a teacher deleted what is
      remembered (`captured_note_lines`) merged in the same way;
    - `evidence_subject`: each record id in the turns' manifests (`EVIDENCE_IDS`) to the
      subject of the lesson the record came from;
    - `guidance`: the teacher's guidance (`teacher_guidance` evidence): {"id", "session_id",
      "pupil", "payload", "at"};
    - `states`: where each pupil got to in each lesson (`LearningState`): {"pupil",
      "session_id", "status", "step_index"}."""

    lessons: list[LessonFacts]
    turns: list[Turn]
    sent: list[Sent]
    events: list[dict]
    alerts: list[dict]
    access: list[dict]
    outcomes: list[dict]
    notes: list[dict]
    note_lines: dict[str, list[dict]]
    evidence_subject: dict[str, str]
    guidance: list[dict]
    states: list[dict]
    teacher_replies: list[str]
    view_seconds: list[float]
    errors: list[str]
    cast: dict[str, dict]


async def collect(
    db: AsyncSession,
    logs: list[LessonLog],
    lessons: list[LessonFacts],
    teacher_replies: list[str],
    extra_events: Sequence[dict] = (),
    captured_note_lines: dict[str, list[dict]] | None = None,
) -> RunData:
    """What the platform kept of the run's lessons and pupils, read with `db`, beside the logs.
    `extra_events` are the runner's probes, added after the lessons' own events. A lesson that
    never ran (no session) is passed on with the others and has no records.

    `captured_note_lines` are lines `note_lines_of` read before a teacher deleted what is
    remembered of their pupils, which took the lines out of the database. They are merged with
    what the database still holds, each line once at its earliest time, so the run's data has
    every line ever written; a pupil there who is not in the cast is kept too."""
    sessions = _ids([lesson.session_id for lesson in lessons] + [log.session_id for log in logs])
    cast = {pupil: who for log in logs for pupil, who in log.cast.items()}
    pupil_ids = list(await db.scalars(select(User.id).where(User.pseudonym.in_(list(cast)))))

    turns = await _fresh(
        db,
        select(AgentTurn)
        .where(AgentTurn.session_id.in_(sessions), AgentTurn.mode == "student")
        .order_by(AgentTurn.created_at, AgentTurn.id),
    )
    agent_lines = await _agent_lines(db, [t.id for t in turns])
    alerts = await _fresh(
        db,
        select(Exception_)
        .where(Exception_.session_id.in_(sessions))
        .order_by(Exception_.created_at, Exception_.id),
    )
    access = await _fresh(
        db,
        select(TeacherAccessLog)
        .where(TeacherAccessLog.session_id.in_(sessions))
        .order_by(TeacherAccessLog.created_at, TeacherAccessLog.id),
    )
    outcomes = await _fresh(
        db,
        select(LessonOutcome)
        .where(LessonOutcome.session_id.in_(sessions))
        .order_by(LessonOutcome.created_at, LessonOutcome.id),
    )
    notes = await _fresh(
        db,
        select(StudentNote)
        .where(StudentNote.student_id.in_(pupil_ids))
        .order_by(StudentNote.created_at, StudentNote.id),
    )
    guidance = await _fresh(
        db,
        select(EvidenceRecord)
        .where(
            EvidenceRecord.session_id.in_(sessions),
            EvidenceRecord.kind == EvidenceKind.TEACHER_GUIDANCE.value,
        )
        .order_by(EvidenceRecord.created_at, EvidenceRecord.id),
    )
    states = await _fresh(
        db,
        select(LearningState)
        .where(LearningState.session_id.in_(sessions))
        .order_by(LearningState.created_at, LearningState.id),
    )
    name = await _names(
        db,
        [r.student_id for r in (*turns, *alerts, *access, *outcomes, *notes, *guidance, *states)]
        + [r.teacher_id for r in (*access, *notes)],
    )
    note_lines = await note_lines_of(db, list(cast))
    for pupil, kept in (captured_note_lines or {}).items():
        note_lines[pupil] = _distinct([*kept, *note_lines.get(pupil, [])])

    return RunData(
        lessons=list(lessons),
        turns=[_turn(t, agent_lines.get(t.id), name) for t in turns],
        sent=[s for log in logs for s in log.sent],
        events=[e for log in logs for e in log.events] + list(extra_events),
        alerts=[
            {
                "id": str(a.id),
                "session_id": str(a.session_id),
                "pupil": name.get(a.student_id),
                "kind": a.kind,
                "status": a.status,
                "summary": a.summary,
                "payload": a.payload,
                "at": _iso(a.created_at),
                "acknowledged_at": _iso(a.acknowledged_at),
            }
            for a in alerts
        ],
        access=[
            {
                "teacher": name.get(r.teacher_id),
                "session_id": str(r.session_id),
                "pupil": name.get(r.student_id),
                "action": r.action,
                "detail": r.detail,
                "at": _iso(r.created_at),
            }
            for r in access
        ],
        outcomes=[
            {
                "session_id": str(o.session_id),
                "pupil": name.get(o.student_id),
                "status": o.status,
                "suggested": o.suggested,
                "confirmed": o.confirmed,
                "confirmed_at": _iso(o.confirmed_at),
            }
            for o in outcomes
        ],
        notes=[
            {
                "teacher": name.get(n.teacher_id),
                "pupil": name.get(n.student_id),
                "text": n.text,
                "until": n.until.isoformat(),
                "at": _iso(n.created_at),
            }
            for n in notes
        ],
        note_lines=note_lines,
        evidence_subject=await _evidence_subject(db, turns),
        guidance=[
            {
                "id": str(g.id),
                "session_id": str(g.session_id),
                "pupil": name.get(g.student_id),
                "payload": g.payload,
                "at": _iso(g.created_at),
            }
            for g in guidance
        ],
        states=[
            {
                "pupil": name.get(s.student_id),
                "session_id": str(s.session_id),
                "status": s.status,
                "step_index": s.step_index,
            }
            for s in states
        ],
        teacher_replies=list(teacher_replies),
        view_seconds=[seconds for log in logs for seconds in log.view_seconds],
        errors=[error for log in logs for error in log.errors],
        cast=cast,
    )


async def pitch_call_of(db: AsyncSession, line_id: str) -> str | None:
    """The tutor's own call on how it pitched the question its line `line_id` asks
    (`Message.data["pitch_call"]`), for the driver's `read_call`: "as written", "stretched",
    "more support", "stayed" or "let go". None when the line made no call, is not the tutor's,
    or is not there."""
    line = _id(line_id)
    if line is None:
        return None
    data = await db.scalar(
        select(Message.data).where(Message.id == line, Message.role == MessageRole.AGENT.value)
    )
    return _call(data)


def _call(data: dict | None) -> str | None:
    """The tutor's pitch call as kept with its line, or None when the line keeps none."""
    call = (data or {}).get("pitch_call")
    return call if isinstance(call, str) else None


def _turn(turn: AgentTurn, line: Message | None, name: dict[uuid.UUID, str]) -> Turn:
    request = dict(turn.request or {})
    kept = line.data if line is not None else {}
    return Turn(
        id=str(turn.id),
        session_id=str(turn.session_id),
        pupil=name.get(turn.student_id, ""),
        model=turn.model,
        prompt_version=turn.prompt_version,
        manifest=dict(turn.context_manifest or {}),
        reply=_reply(turn),
        conflicts=list(turn.conflicts or []),
        outcome=turn.validation_outcome,
        leak=turn.leakage_check,
        latency_ms=turn.latency_ms,
        said=_said(request),
        reply_text=line.text if line is not None else "",
        agent_line_id=str(line.id) if line is not None else None,
        at=_iso(turn.created_at),
        request=request,
        usage=dict(turn.usage or {}),
        helped=kept.get("helped"),
        call=_call(kept),
        changed=list(kept.get("pitch_changed") or []),
    )


def _said(request: dict) -> str:
    """What the pupil said in a turn, as the platform stored it on their page: their words, or
    the words of the help button they pressed. "" for a turn with nothing from them."""
    text = request.get("text")
    if text is None:
        return ""
    return text.strip() or INTENTS.get(request.get("intent") or "", "")


async def _agent_lines(db: AsyncSession, turn_ids: list[uuid.UUID]) -> dict[uuid.UUID, Message]:
    """The agent line each turn wrote: the tutor's message carrying the turn's id. A reply held
    back also writes a note for the teacher with that id, which is not the line."""
    lines: dict[uuid.UUID, Message] = {}
    said = await _fresh(
        db,
        select(Message)
        .where(Message.turn_id.in_(turn_ids), Message.role == MessageRole.AGENT.value)
        .order_by(Message.created_at, Message.id),
    )
    for line in said:
        lines.setdefault(line.turn_id, line)
    return lines


async def note_lines_of(db: AsyncSession, pseudonyms: list[str]) -> dict[str, list[dict]]:
    """Every distinct learner note line written for each of these pupils, by pseudonym, as
    {"sentence", "at", "source", "category", "session_id"}: once per sentence and who wrote it
    (`source`, "counted" or "review"), at the time it was first written, in time order. Its
    `session_id` is the lesson whose end or review made the note version that first held it,
    or None. A pupil with no lines has an empty list. Read only.

    `collect` reads the lines this way. The runner calls it too, to keep a group's lines just
    before its teacher deletes what is remembered, which takes them out of the database."""
    found: dict[str, list[dict]] = {pupil: [] for pupil in pseudonyms}
    rows = await db.execute(
        select(
            User.pseudonym,
            LearnerNoteLine.sentence,
            LearnerNoteLine.created_at,
            LearnerNoteLine.source,
            LearnerNoteLine.category,
            LearnerNote.session_id,
        )
        .join(LearnerNote, LearnerNote.id == LearnerNoteLine.note_id)
        .join(User, User.id == LearnerNote.student_id)
        .where(User.pseudonym.in_(list(found)))
        .order_by(LearnerNoteLine.created_at, LearnerNote.version, LearnerNoteLine.position)
    )
    for pupil, sentence, at, source, category, session_id in rows:
        found[pupil].append(
            {
                "sentence": sentence,
                "at": _iso(at),
                "source": source,
                "category": category,
                "session_id": str(session_id) if session_id is not None else None,
            }
        )
    return {pupil: _distinct(lines) for pupil, lines in found.items()}


def _distinct(lines: Iterable[dict]) -> list[dict]:
    """Each line once per (sentence, source), as it was at the earliest time it was written,
    in time order. Lines written at the same time keep the order they came in: a version's
    lines in the order a lesson reads them."""
    first: dict[tuple[str, str], dict] = {}
    for line in sorted(lines, key=lambda line: datetime.fromisoformat(line["at"])):
        first.setdefault((line["sentence"], line["source"]), line)
    return list(first.values())


async def _evidence_subject(db: AsyncSession, turns: list[AgentTurn]) -> dict[str, str]:
    """Each record id in the turns' manifests, as the manifest writes it, to the subject of the
    lesson the record came from: its brief's subject, else the one the lesson was saved under.
    An id that names no record is left out."""
    named = {
        str(raw): rid
        for t in turns
        for key in EVIDENCE_IDS
        for raw in t.context_manifest.get(key) or []
        if (rid := _id(raw)) is not None
    }
    rows = await db.execute(
        select(EvidenceRecord.id, LessonContract.brief, LessonContract.subject)
        .join(Session, Session.id == EvidenceRecord.session_id)
        .join(LessonContract, LessonContract.id == Session.contract_id)
        .where(EvidenceRecord.id.in_(list(set(named.values()))))
    )
    subject = {rid: (brief or {}).get("subject") or saved for rid, brief, saved in rows}
    return {raw: subject[rid] for raw, rid in sorted(named.items()) if rid in subject}


async def _fresh(db: AsyncSession, query) -> list:
    """Every record the query finds, as the database has it now, even where the caller's
    session holds an older copy (an agent line read during the lesson, before the pupil tapped
    it)."""
    return list(await db.scalars(query.execution_options(populate_existing=True)))


async def _names(db: AsyncSession, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    """The pseudonyms of the users with these ids."""
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.pseudonym).where(User.id.in_(list(wanted))))
    return {user_id: pseudonym for user_id, pseudonym in rows}


def _id(value: object) -> uuid.UUID | None:
    """`value` as an id, or None when it is not one."""
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _ids(values: Iterable[object]) -> list[uuid.UUID]:
    """The values that are ids, each once, in order. Anything else, such as the empty session
    of a lesson that never ran, is left out."""
    return list(dict.fromkeys(i for v in values if (i := _id(v)) is not None))


def _iso(moment: datetime | None) -> str | None:
    """A time from the database as ISO text, in UTC."""
    return moment.astimezone(UTC).isoformat() if moment is not None else None
