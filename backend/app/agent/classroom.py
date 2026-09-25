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

from app.agent import memory, store
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
        if kind == SignalKind.MISCONCEPTION.value and s.payload.get("note"):
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
        if state is None or state.turns == 0:
            label = "not_started"
        elif state.status == LearningStatus.COMPLETED.value:
            label = "finished"
        elif session.status == SessionStatus.CLOSED.value:
            label = "took_part"
        elif alert_count.get(student.id):
            label = "needs_you"
        elif state.struggle_turns >= 2 or student.id in struggling_now:
            label = "struggling"
        else:
            label = "working"
        note = last_signal[student.id].payload.get("note", "") if student.id in last_signal else ""
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


async def snapshot(db: AsyncSession, session: Session) -> tuple[dict, dict]:
    """What the agent is shown about the class, and the manifest of it."""
    p = await pulse(db, session)
    assessments = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.kind == EvidenceKind.ASSESSMENT.value,
            )
            .order_by(EvidenceRecord.created_at.desc())
            .limit(120)
        )
    ).all()
    names = {s.student_id: s.pseudonym for s in p.students}
    recent: dict[str, list[dict]] = {}
    for a in reversed(assessments):
        recent.setdefault(names.get(a.student_id, "unknown"), []).append(
            {
                "step": a.payload.get("step_name"),
                "judgment": a.payload.get("judgment"),
                "quote": str(a.payload.get("evidence_quote", ""))[:160],
                "misconception": a.payload.get("misconception"),
            }
        )
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
                "recent_judgments": recent.get(s.pseudonym, [])[-4:],
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
        text = "Finished the activity" if pl.get("completed") else "Moved to another step"
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
            "current": bool(state) and i == state.step_index,
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
    misconceptions = [
        r.payload["misconception"]
        for r in records
        if r.kind == EvidenceKind.ASSESSMENT.value and r.payload.get("misconception")
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
        "summary": summary,
        "steps": steps,
        "evidence": [_evidence_line(r) for r in records],
        "knowledge": await memory.knowledge(db, student_id=student.id),
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
    keep: str = Field(default="", max_length=600)
    develop: list[str] = Field(default_factory=list, max_length=4)


class ReviewOut(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    outcomes: list[StudentOutcome] = Field(default_factory=list)


REVIEW_SYSTEM = """\
You are the class agent. The lesson has ended. Write a short summary for the teacher, \
then suggest an outcome for each student against the assessment criteria, using only \
the evidence below (their step judgments and quotes). Points must not exceed each \
criterion's max. Give a one-line reason per criterion, one thing they did well \
("keep") and up to two things to work on ("develop"). The teacher confirms every \
outcome before a student sees it.
"""


async def suggest_outcomes(
    db: AsyncSession, client: LLMClient, *, session: Session
) -> list[LessonOutcome]:
    """Ask the agent for a summary and an outcome per student who took part."""
    data, manifest = await snapshot(db, session)
    brief = LessonBrief.model_validate(
        (await db.get(LessonContract, session.contract_id)).brief or {}
    )
    criteria = [c.model_dump() for c in brief.assessment]
    if not criteria:
        return []
    states = {
        s.student_id: s
        for s in (
            await db.scalars(select(LearningState).where(LearningState.session_id == session.id))
        ).all()
    }
    took_part = []
    for s in data["students"]:
        state = states.get(uuid.UUID(s["student_id"]))
        if state is None or state.turns == 0:
            continue
        s["steps_met"] = sum(1 for x in state.steps or [] if (x or {}).get("judgment") == "met")
        s["step_count"] = len(brief.steps)
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
            prompt_version="review-v1",
            provider=result.provider,
            model=result.model,
            latency_ms=result.latency_ms,
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
            suggested={"criteria": chosen, "keep": o.keep, "develop": o.develop},
            suggested_total=sum(c["points"] for c in chosen),
            provider=result.provider,
            model=result.model[:64],
            prompt_version="review-v1",
        )
        db.add(score)
        created.append(score)
    await db.commit()
    return created
