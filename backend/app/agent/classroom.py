"""The teacher's view of a lesson, and the class agent's part in it.

`pulse` turns the evidence into the few things a teacher can act on: who needs
them, who is struggling, what the class keeps getting wrong. It is computed
from records, not written by a model, so it can't misreport.

The agent adds what a count can't: answers to the teacher's questions about the
class, a summary of the lesson, and suggested outcomes the teacher confirms.
Its context here is the whole class - this is the teacher's side.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import store
from app.agent.brief import LessonBrief
from app.agent.llm import LLMClient, ask_structured
from app.enums import (
    EvidenceKind,
    ExceptionStatus,
    LeakageCheck,
    LearningStatus,
    MessageRole,
    ScoreStatus,
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
    Message,
    Session,
    SessionParticipant,
    User,
)

POLICY_VERSION = "class-agent-v1"
# No reply from a student for this long, while the lesson runs, is worth a glance.
QUIET_MINUTES = 6


class StudentState(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    state: str  # needs_you | struggling | working | finished | not_started
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


def _pattern_key(note: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", note.lower()).strip()[:60]


async def pulse(db: AsyncSession, session: Session) -> Pulse:
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
            key = _pattern_key(s.payload["note"])
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
        if alert_count.get(student.id):
            label = "needs_you"
        elif state is None or state.turns == 0:
            label = "not_started"
        elif state.status == LearningStatus.COMPLETED.value:
            label = "finished"
        elif state.struggle_turns >= 2 or student.id in struggling_now:
            label = "struggling"
        else:
            label = "working"
        note = ""
        if student.id in last_signal:
            note = last_signal[student.id].payload.get("note", "")
        if (
            label == "working"
            and state
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


CLASS_SYSTEM = """\
You are the class agent, reporting to the teacher about a lesson you are teaching \
to each of their students. Answer the teacher's question using only the class data \
below. Be brief and concrete: name students by pseudonym, say what you saw, and \
suggest what the teacher could do. Say so when the data doesn't show something. \
Describe behaviour as observations, never as judgments about a child.
"""


class ClassAnswerOut(BaseModel):
    reply: str = Field(min_length=1, max_length=3000)
    cited_students: list[str] = Field(default_factory=list, max_length=40)


class InsightItem(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    students: list[str] = Field(default_factory=list, max_length=40)


class InsightOut(BaseModel):
    summary: str = Field(min_length=1, max_length=1500)
    items: list[InsightItem] = Field(default_factory=list, max_length=8)


def _audit(conversation_id, session_id, manifest, client, result, tries, request, mode="classroom"):
    return AgentTurn(
        session_id=session_id,
        conversation_id=conversation_id,
        mode=mode,
        context_manifest=manifest,
        policy_version=POLICY_VERSION,
        prompt_version=f"{mode}-v1",
        provider=result.provider if result else client.name,
        model=result.model if result else client.model,
        latency_ms=result.latency_ms if result else 0,
        validation_outcome=(
            ValidationOutcome.REGENERATED if tries > 1 else ValidationOutcome.OK
        ).value,
        leakage_check=LeakageCheck.SKIPPED.value,
        conflicts=[],
        request=request,
        response={"raw": (result.raw if result else "")[:8000]},
    )


async def ask_about_class(
    db: AsyncSession, client: LLMClient, *, session: Session, teacher: User, text: str
) -> Message:
    conversation = await store.classroom_conversation(
        db, teacher_id=teacher.id, session_id=session.id
    )
    await store.add_message(db, conversation, role=MessageRole.TEACHER, text=text)
    data, manifest = await snapshot(db, session)
    history = [
        {"role": "user" if m.role == MessageRole.TEACHER.value else "assistant", "content": m.text}
        for m in await store.messages(db, conversation.id, limit=20)
        if m.role in (MessageRole.TEACHER.value, MessageRole.AGENT.value)
    ]
    out, result, tries = await ask_structured(
        client,
        ClassAnswerOut,
        purpose="class_answer",
        system=CLASS_SYSTEM + "\n\nThe class right now:\n" + json.dumps(data),
        messages=history,
        max_tokens=1200,
    )
    turn = _audit(conversation.id, session.id, manifest, client, result, tries, {"text": text})
    db.add(turn)
    await db.flush()
    reply = await store.add_message(
        db,
        conversation,
        role=MessageRole.AGENT,
        text=out.reply,
        data={"cited_students": out.cited_students},
        turn_id=turn.id,
    )
    await db.commit()
    return reply


INSIGHT_SYSTEM = """\
You are the class agent. Summarise this lesson so far for the teacher in one or two \
sentences, then up to five short points about what matters most: students who need \
attention, misconceptions shared across the class, questions left unresolved, \
students moving unusually fast. Use only the data below. Name students by pseudonym.
"""


async def refresh_insight(db: AsyncSession, client: LLMClient, *, session: Session) -> ClassInsight:
    data, manifest = await snapshot(db, session)
    out, result, tries = await ask_structured(
        client,
        InsightOut,
        purpose="class_insight",
        system=INSIGHT_SYSTEM + "\n\nThe class right now:\n" + json.dumps(data),
        messages=[{"role": "user", "content": "Summarise the class for me now."}],
        max_tokens=1200,
    )
    db.add(_audit(None, session.id, manifest, client, result, tries, {"insight": True}))
    insight = ClassInsight(
        session_id=session.id,
        summary=out.summary,
        items=[i.model_dump() for i in out.items],
        model=f"{result.provider}:{result.model}",
    )
    db.add(insight)
    await db.commit()
    return insight


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
    # A student who never took part has nothing to judge; the teacher sees them
    # listed without an outcome instead of a score of nothing.
    took_part = []
    for s in data["students"]:
        state = states.get(uuid.UUID(s["student_id"]))
        if state is None or state.turns == 0:
            continue
        steps = state.steps or []
        s["steps_met"] = sum(1 for x in steps if (x or {}).get("judgment") == "met")
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
    db.add(_audit(None, session.id, manifest, client, result, tries, {"review": True}, "review"))
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
