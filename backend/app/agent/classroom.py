"""The teacher's view of a running lesson, computed from records, and the class
agent's end-of-lesson review: a summary and suggested outcomes.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import learner, memory, store
from app.agent.brief import LessonBrief
from app.agent.llm import LLMClient, ask_structured
from app.enums import (
    Audience,
    EvidenceKind,
    ExceptionStatus,
    LeakageCheck,
    LearningStatus,
    ScoreStatus,
    SessionStatus,
    SignalKind,
    TriageAction,
    ValidationOutcome,
)
from app.models import (
    AgentTurn,
    ClassInsight,
    EvidenceRecord,
    Exception_,
    LearningState,
    LessonContract,
    LessonOutcome,
    Session,
    SessionParticipant,
    User,
)

POLICY_VERSION = "class-agent-v1"
# A working student silent for this long gets a note on the board.
QUIET_MINUTES = 6


class StudentState(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    state: str  # needs_you | struggling | working | finished | took_part | not_started
    step_index: int
    step_name: str
    turns: int
    last_activity_at: datetime | None
    note: str = ""
    open_alerts: int = 0


class Alert(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    pseudonym: str
    kind: str
    priority: int
    summary: str
    created_at: datetime


class Pattern(BaseModel):
    note: str
    students: list[str]


class Notable(BaseModel):
    kind: str
    pseudonym: str
    note: str
    at: datetime


@dataclass
class Pulse:
    students: list[StudentState]
    alerts: list[Alert]
    patterns: list[Pattern]
    notable: list[Notable]
    brief: LessonBrief
    evidence_ids: list[str] = field(default_factory=list)


async def students_who_wrote(db: AsyncSession, session_id: uuid.UUID) -> set[uuid.UUID]:
    """Students who wrote, or pressed a help button, at least once in this lesson. The
    agent's opening, or a teacher's guidance, is not the student taking part. Read from the
    turns, which outlive the chat: once the purge has taken the words, a flag says it."""
    return (await students_who_wrote_in(db, [session_id]))[session_id]


async def students_who_wrote_in(
    db: AsyncSession, session_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """The same for many lessons in one read, every asked-for lesson present."""
    wrote: dict[uuid.UUID, set[uuid.UUID]] = {s: set() for s in session_ids}
    if not session_ids:
        return wrote
    rows = await db.execute(
        select(
            AgentTurn.session_id, AgentTurn.student_id, AgentTurn.request, AgentTurn.response
        ).where(AgentTurn.session_id.in_(session_ids), AgentTurn.mode == "student")
    )
    for session_id, student_id, request, response in rows.all():
        # A failed call kept nothing of what they wrote.
        if (
            student_id is not None
            and "error" not in (response or {})
            and (
                (request or {}).get("text")
                or (request or {}).get("intent")
                or (request or {}).get("answered")
            )
        ):
            wrote[session_id].add(student_id)
    return wrote


def when(moment: datetime | None) -> str | None:
    """A time as the rest of the API writes it."""
    return moment.isoformat().replace("+00:00", "Z") if moment else None


async def pulse(db: AsyncSession, session: Session) -> Pulse:
    """Who needs the teacher, who is struggling, and what the class keeps getting wrong."""
    contract = await db.get(LessonContract, session.contract_id)
    brief = LessonBrief.model_validate(contract.brief or {})
    students = (
        await db.scalars(
            select(User)
            .join(SessionParticipant, SessionParticipant.student_id == User.id)
            .where(SessionParticipant.session_id == session.id)
            .order_by(User.pseudonym)
        )
    ).all()
    by_id = {s.id: s for s in students}
    states = {
        s.student_id: s
        for s in (
            await db.scalars(select(LearningState).where(LearningState.session_id == session.id))
        ).all()
    }
    open_alerts = (
        await db.scalars(
            select(Exception_)
            .where(
                Exception_.session_id == session.id,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
            .order_by(Exception_.priority, Exception_.created_at)
        )
    ).all()
    signals = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.kind == EvidenceKind.SIGNAL.value,
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()
    # The answers judged met, only to tell which misconceptions a pupil has since put right.
    met = (
        await db.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.kind == EvidenceKind.ASSESSMENT.value,
                EvidenceRecord.payload["judgment"].as_string() == "met",
            )
        )
    ).all()
    gone = memory.put_right([*signals, *met])

    alert_count: dict[uuid.UUID, int] = {}
    for a in open_alerts:
        alert_count[a.student_id] = alert_count.get(a.student_id, 0) + 1
    last_signal: dict[uuid.UUID, EvidenceRecord] = {}
    struggling_now: set[uuid.UUID] = set()
    patterns: dict[str, tuple[str, set[str]]] = {}
    notable: list[Notable] = []
    for s in signals:
        last_signal[s.student_id] = s
        kind = s.payload.get("signal")
        pseudonym = by_id[s.student_id].pseudonym if s.student_id in by_id else "unknown"
        state = states.get(s.student_id)
        if (
            kind == SignalKind.STRUGGLING.value
            and state
            and s.payload.get("step_index") == state.step_index
        ):
            struggling_now.add(s.student_id)
        if kind == SignalKind.MISCONCEPTION.value and s.payload.get("note") and s.id not in gone:
            key = re.sub(r"[^a-z0-9 ]", "", s.payload["note"].lower()).strip()[:60]
            note, who = patterns.get(key, (s.payload["note"], set()))
            who.add(pseudonym)
            patterns[key] = (note, who)
        if (
            s.payload.get("action") == TriageAction.SUMMARISE.value
            and kind != SignalKind.MISCONCEPTION.value
        ):
            notable.append(
                Notable(
                    kind=kind, pseudonym=pseudonym, note=s.payload.get("note", ""), at=s.created_at
                )
            )

    now = datetime.now(UTC)
    rows: list[StudentState] = []
    for student in students:
        state = states.get(student.id)
        step_index = state.step_index if state else 0
        step_name = brief.steps[step_index].name if step_index < len(brief.steps) else ""
        if alert_count.get(student.id) and session.status != SessionStatus.CLOSED.value:
            # Asked for the teacher before writing, or after finishing: they still need you.
            label = "needs_you"
        elif state is None or state.turns == 0:
            label = "not_started"
        elif state.status == LearningStatus.COMPLETED.value:
            label = "finished"
        elif session.status == SessionStatus.CLOSED.value:
            label = "took_part"
        elif student.id in struggling_now:
            label = "struggling"
        else:
            label = "working"
        last = last_signal.get(student.id)
        # A note about a step they have since moved past is out of date.
        note = (
            last.payload.get("note", "")
            if last and last.payload.get("step_index") == step_index
            else ""
        )
        if (
            label == "working"
            and state.last_activity_at
            and (now - state.last_activity_at).total_seconds() > QUIET_MINUTES * 60
        ):
            note = note or f"Quiet for over {QUIET_MINUTES} minutes."
        rows.append(
            StudentState(
                student_id=student.id,
                pseudonym=student.pseudonym,
                state=label,
                step_index=step_index,
                step_name=step_name,
                turns=state.turns if state else 0,
                last_activity_at=state.last_activity_at if state else None,
                note=note,
                open_alerts=alert_count.get(student.id, 0),
            )
        )

    return Pulse(
        students=rows,
        alerts=[
            Alert(
                id=a.id,
                student_id=a.student_id,
                pseudonym=by_id[a.student_id].pseudonym if a.student_id in by_id else "unknown",
                kind=a.kind,
                priority=a.priority,
                summary=a.summary,
                created_at=a.created_at,
            )
            for a in open_alerts
        ],
        patterns=sorted(
            (Pattern(note=note, students=sorted(who)) for note, who in patterns.values()),
            key=lambda p: -len(p.students),
        ),
        notable=notable[-20:],
        brief=brief,
        evidence_ids=[str(s.id) for s in signals],
    )


# The end-of-lesson summary is shown each step's last few judgments, so a first try that missed
# and the answer that met are both there; the teacher's chat, read on every message, the latest.
SUMMARY_PER_STEP = 3


async def snapshot(db: AsyncSession, session: Session, *, per_step: int = 1) -> tuple[dict, dict]:
    """What the agent is shown about the class, and the manifest of it. Each student's
    judgments are their last `per_step` on every step, in the lesson's order: by step, so a
    pupil who finished never loses step 1 to the steps after it."""
    p = await pulse(db, session)
    assessments = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.kind == EvidenceKind.ASSESSMENT.value,
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()
    names = {s.student_id: s.pseudonym for s in p.students}
    by_step: dict[str, dict[int, list[EvidenceRecord]]] = {}
    for a in assessments:
        steps = by_step.setdefault(names.get(a.student_id, "unknown"), {})
        steps.setdefault(int(a.payload.get("step_index") or 0), []).append(a)
    recent = {
        who: [
            {
                "step": a.payload.get("step_name"),
                "judgment": a.payload.get("judgment"),
                "quote": str(a.payload.get("evidence_quote", ""))[:160],
                "misconception": a.payload.get("misconception"),
            }
            for index in sorted(steps)
            for a in steps[index][-per_step:]
        ]
        for who, steps in by_step.items()
    }
    data = {
        "lesson": {
            "title": p.brief.title,
            "objectives": p.brief.objectives,
            "steps": [s.name for s in p.brief.steps],
        },
        "students": [
            {
                "student_id": str(s.student_id),
                "pseudonym": s.pseudonym,
                "state": s.state,
                "step": s.step_name,
                "turns": s.turns,
                "note": s.note,
                "judgments": recent.get(s.pseudonym, []),
            }
            for s in p.students
        ],
        "needs_you": [a.model_dump(mode="json") for a in p.alerts],
        "patterns": [pt.model_dump() for pt in p.patterns],
        "notable": [n.model_dump(mode="json") for n in p.notable],
    }
    manifest = {
        "mode": "classroom",
        "session_id": str(session.id),
        "signal_ids": p.evidence_ids,
        "assessment_ids": [str(a.id) for a in assessments],
    }
    return data, manifest


# ---------- one student ----------


def _named(state: StudentState) -> dict:
    return {"student_id": str(state.student_id), "pseudonym": state.pseudonym}


def _evidence_line(record: EvidenceRecord) -> dict:
    """An evidence record in the teacher's words."""
    pl = record.payload
    if record.kind == EvidenceKind.ASSESSMENT.value:
        text = f"{pl.get('step_name', 'Step')}: {str(pl.get('judgment', '')).replace('_', ' ')}"
        detail = str(pl.get("evidence_quote", ""))
        if pl.get("misconception"):
            detail += f" (misconception: {pl['misconception']})"
    elif record.kind == EvidenceKind.SIGNAL.value:
        text = str(pl.get("signal", "")).replace("_", " ").capitalize()
        detail = f"{pl.get('note', '')} [{pl.get('action', '')}]"
    elif record.kind == EvidenceKind.POLICY_EVENT.value:
        text = "The agent's reply was held back by your rules"
        detail = str(pl.get("reason", ""))
    elif record.kind == EvidenceKind.STEP_CHANGE.value:
        if pl.get("completed"):
            text = "Finished the activity"
        elif pl.get("step_name"):
            text = f"Moved to “{pl['step_name']}”"
        else:
            text = "Moved to another step"
        detail = ""
    else:
        text = "Your guidance"
        detail = str(pl.get("text", ""))
    return {
        "kind": record.kind,
        "text": text,
        "detail": detail,
        "at": when(record.created_at),
    }


async def student_view(
    db: AsyncSession, session: Session, student: User, *, conversation: bool = False
) -> dict:
    """One student's progress and evidence; with `conversation`, their transcript too."""
    contract = await db.get(LessonContract, session.contract_id)
    brief = LessonBrief.model_validate(contract.brief or {})
    state = await db.scalar(
        select(LearningState).where(
            LearningState.session_id == session.id, LearningState.student_id == student.id
        )
    )
    p = await pulse(db, session)
    label = next((s.state for s in p.students if s.student_id == student.id), "not_started")

    rows = (state.steps or []) if state else []
    steps = [
        {
            "name": s.name,
            "judgment": (rows[i] or {}).get("judgment") if i < len(rows) else None,
            "attempts": (rows[i] or {}).get("attempts", 0) if i < len(rows) else 0,
            "current": bool(state)
            and i == state.step_index
            and state.status != LearningStatus.COMPLETED.value,
            # Left for later by the pupil, unfinished; and an answer changed after finishing.
            "parked": bool(i < len(rows) and (rows[i] or {}).get("parked")),
            "changed": bool(i < len(rows) and (rows[i] or {}).get("changed")),
        }
        for i, s in enumerate(brief.steps)
    ]

    records = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.student_id == student.id,
                EvidenceRecord.kind.in_(
                    [
                        EvidenceKind.ASSESSMENT.value,
                        EvidenceKind.SIGNAL.value,
                        EvidenceKind.POLICY_EVENT.value,
                        EvidenceKind.STEP_CHANGE.value,
                        EvidenceKind.TEACHER_GUIDANCE.value,
                    ]
                ),
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()

    summary = [f"{sum(1 for s in steps if s['judgment'] == 'met')} of {len(steps)} steps met."]
    if state and state.status == LearningStatus.COMPLETED.value:
        summary.append("Finished the activity.")
    elif state and steps:
        where = "Reached" if session.status == SessionStatus.CLOSED.value else "Now on"
        summary.append(f"{where} “{steps[state.step_index]['name']}”.")
    gone = memory.put_right(list(records))
    misconceptions = [
        r.payload["misconception"]
        for r in records
        if r.kind == EvidenceKind.ASSESSMENT.value
        and r.payload.get("misconception")
        and r.id not in gone
    ]
    if misconceptions:
        summary.append(f"Misconception seen: {misconceptions[-1].rstrip('.')}.")
    held = sum(1 for r in records if r.kind == EvidenceKind.POLICY_EVENT.value)
    if held:
        summary.append(
            f"{held} agent repl{'y was' if held == 1 else 'ies were'} held back by your rules."
        )

    lines = None
    if conversation:
        convo = await store.student_conversation(db, session_id=session.id, student_id=student.id)
        lines = [
            {
                "who": {"student": "student", "agent": "agent"}.get(
                    m.role, "note" if m.audience == Audience.ALL.value else "teacher_only"
                ),
                "text": m.text,
                "at": when(m.created_at),
            }
            for m in await store.messages(db, convo.id)
        ]

    # The neighbours on the board, so the teacher can step through the class.
    order = p.students
    at = next((i for i, s in enumerate(order) if s.student_id == student.id), None)
    beside = {
        "previous": None if at in (None, 0) else _named(order[at - 1]),
        "next": None if at is None or at + 1 >= len(order) else _named(order[at + 1]),
    }

    return {
        "student_id": str(student.id),
        "pseudonym": student.pseudonym,
        "state": label,
        **beside,
        "session_status": session.status,
        # What still needs the teacher about this student, so it can be marked dealt with here.
        "alerts": [
            {"id": str(a.id), "kind": a.kind, "summary": a.summary}
            for a in p.alerts
            if a.student_id == student.id
        ],
        # Everyone in the lesson, so the teacher can go straight to any of them.
        "classmates": [
            {"student_id": str(s.student_id), "pseudonym": s.pseudonym, "state": s.state}
            for s in order
        ],
        "summary": summary,
        "steps": steps,
        "evidence": [_evidence_line(r) for r in records],
        "knowledge": await memory.knowledge(db, student_id=student.id),
        # What the tutor is told about them in their next lessons. To read: nothing the teacher
        # does changes it, and it is the same whichever study arm this lesson is in.
        "remembers": learner.as_read(await learner.latest(db, student.id)),
        "conversation": lines,
    }


# ---------- outcomes at the end of a lesson ----------


class CriterionOutcome(BaseModel):
    name: str
    points: int = Field(ge=0)
    reason: str = Field(default="", max_length=600)


class StudentOutcome(BaseModel):
    student_id: uuid.UUID
    criteria: list[CriterionOutcome]
    keep: str = Field(default="", max_length=600, description="One thing they did well.")
    develop: list[str] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "Up to two things to work on, each something they got wrong or left out when asked."
        ),
    )
    # No limit on the list: a fifth line is dropped by the server, never a reason to ask again.
    learns: list[str] = Field(
        default_factory=list,
        description=(
            "How this student learns, for the tutor in their next lessons: up to four short "
            "lines as they should now stand, none in the student's own words."
        ),
    )


class ReviewOut(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    outcomes: list[StudentOutcome] = Field(default_factory=list)


REVIEW_SYSTEM = """\
You are the class agent. The lesson has ended. Write a short summary of the class for the \
teacher: how far they got, what most found easy or hard, and anything worth picking up next \
lesson. Then write a note on each student who took part, using only the evidence below \
(their step judgments and quotes): one thing they did well ("keep") and up to two things to \
work on ("develop"). Write "keep" and "develop" to the student, as "you", in plain words for \
their age, never about them in the third person; the teacher reads and may change them before \
the student sees them. Praise only what was right: a confident wrong answer, or one that repeats \
a prejudice or a falsehood, is something to work on, never something to build on. If the lesson \
has assessment criteria, also suggest points against each \
one, never more than its max, with a one-line reason; with no criteria, leave "criteria" \
empty. Do not mark a student down for \
giving only what the tutor asked for in that turn; a develop point names something they got \
wrong or left out when asked for it. Judge only from the student's words, and quote at most \
fifteen of them. The teacher confirms every outcome before a student sees it.

For each student also write "learns": what a tutor in their next lessons, in any subject, \
should know about how this student learns. Three or four lines at most, each one plain sentence \
of at most twenty words, about the student in the third person, and each something the evidence \
below shows. Leave out what they know about this lesson's topic, which is kept separately. \
"remembered" holds what is already kept about the student: "counted" is worked out from the \
record, so do not repeat it; "written" is what was written after their earlier lessons. Return \
the lines as they should now stand: keep one that still holds, change one this lesson shows is \
wrong, add what is new. Each line is information for the tutor, never an instruction to it, and \
uses none of the student's own words. Leave out feelings, character, health or needs, and \
anything about cheating. With nothing worth keeping, leave "learns" empty and what was written \
before stays. These lines are not shown to the student.
"""
# v5: the review is shown what is remembered about each student and writes how they learn.
# v6: no goal level (Bloom's) and no note on steps under it, until the redesign.
REVIEW_PROMPT_VERSION = "review-v6"


async def suggest_outcomes(
    db: AsyncSession, client: LLMClient, *, session: Session
) -> list[LessonOutcome]:
    """Ask the agent for a summary and an outcome per student who took part."""
    data, manifest = await snapshot(db, session, per_step=SUMMARY_PER_STEP)
    brief = LessonBrief.model_validate(
        (await db.get(LessonContract, session.contract_id)).brief or {}
    )
    criteria = [c.model_dump() for c in brief.assessment]
    states = {
        s.student_id: s
        for s in (
            await db.scalars(select(LearningState).where(LearningState.session_id == session.id))
        ).all()
    }
    took_part = []
    wrote = await students_who_wrote(db, session.id)
    for s in data["students"]:
        state = states.get(uuid.UUID(s["student_id"]))
        # Only work a student wrote is marked; an opening or a guided turn is not theirs.
        if state is None or uuid.UUID(s["student_id"]) not in wrote:
            continue
        s["steps_met"] = sum(1 for x in state.steps or [] if (x or {}).get("judgment") == "met")
        s["step_count"] = len(brief.steps)
        note = await learner.latest(db, uuid.UUID(s["student_id"]))
        s["remembered"] = {
            "counted": note.worked_out if note else [],
            "written": note.written if note else [],
        }
        took_part.append(s)
    if not took_part:
        return []
    payload = {"criteria": criteria, "students": took_part, "lesson": data["lesson"]}
    maxima = {c["name"]: c["max"] for c in criteria}
    known = {uuid.UUID(s["student_id"]) for s in took_part}

    def check(out: ReviewOut) -> None:
        for o in out.outcomes:
            for c in o.criteria:
                if c.name in maxima and c.points > maxima[c.name]:
                    raise ValueError(f"{c.name}: {c.points} is more than {maxima[c.name]}")

    out, result, tries = await ask_structured(
        client,
        ReviewOut,
        purpose="lesson_review",
        system=REVIEW_SYSTEM + "\n\nThe lesson:\n" + json.dumps(payload),
        messages=[{"role": "user", "content": "Summarise the lesson and suggest outcomes."}],
        max_tokens=4000,
        check=check,
    )
    db.add(
        AgentTurn(
            session_id=session.id,
            mode="review",
            context_manifest=manifest,
            policy_version=POLICY_VERSION,
            prompt_version=REVIEW_PROMPT_VERSION,
            provider=result.provider,
            model=result.model,
            latency_ms=result.latency_ms,
            usage=result.usage,
            validation_outcome=(
                ValidationOutcome.REGENERATED if tries > 1 else ValidationOutcome.OK
            ).value,
            leakage_check=LeakageCheck.SKIPPED.value,
            conflicts=[],
            request={"review": True},
            response={"raw": result.raw[:8000]},
        )
    )
    db.add(
        ClassInsight(
            session_id=session.id,
            summary=out.summary,
            items=[],
            model=f"{result.provider}:{result.model}",
        )
    )
    existing = set(
        (
            await db.scalars(
                select(LessonOutcome.student_id).where(LessonOutcome.session_id == session.id)
            )
        ).all()
    )
    created = []
    for o in out.outcomes:
        if o.student_id not in known or o.student_id in existing:
            continue
        chosen = [
            {
                "name": c.name,
                "points": min(c.points, maxima[c.name]),
                "max": maxima[c.name],
                "reason": c.reason,
            }
            for c in o.criteria
            if c.name in maxima
        ]
        score = LessonOutcome(
            session_id=session.id,
            student_id=o.student_id,
            status=ScoreStatus.SUGGESTED.value,
            suggested={
                "criteria": chosen,
                "keep": o.keep,
                "develop": o.develop,
            },
            suggested_total=sum(c["points"] for c in chosen),
            provider=result.provider,
            model=result.model[:64],
            prompt_version=REVIEW_PROMPT_VERSION,
        )
        db.add(score)
        created.append(score)
    # How each student learns, as the review now has it, goes into their note on every review,
    # also for a student whose outcome was suggested before. Students are taken in the order of
    # their ids, as every writer of several notes does.
    learns = {o.student_id: o.learns for o in out.outcomes if o.student_id in known}
    wrote = await learner.wrote_in(db, session.id)
    for student_id in sorted(learns):
        await learner.keep_written(
            db,
            student_id=student_id,
            session_id=session.id,
            lines=learns[student_id],
            wrote=wrote,
        )
    await db.commit()
    return created
