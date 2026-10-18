"""The researcher's three pages, read from the records: the whole study, one lesson, one
student's conversation. Counts and plain words first; the raw record one press away.

Nothing here writes. Students appear by pseudonym. What a turn "did" is read from the reply
the model sent and what the server checked, never re-judged."""

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.brief import LessonBrief
from app.agent.classroom import when
from app.config import get_settings
from app.enums import (
    Audience,
    ConversationKind,
    EvidenceKind,
    ExceptionStatus,
    LearningStatus,
    MessageRole,
    TeacherAction,
)
from app.models import (
    AgentTurn,
    Class,
    Conversation,
    EvidenceRecord,
    Exception_,
    LearningState,
    LessonContract,
    LessonOutcome,
    Message,
    Session,
    SessionParticipant,
    TeacherAccessLog,
    User,
)

CONDITION_WORDS = {True: "Remembers the student", False: "Fresh each lesson", None: "No study"}


def condition_word(condition: dict | None) -> str:
    return CONDITION_WORDS[condition.get("memory") if condition else None]


APPROACH_WORDS = {"direct": "Direct instruction", "inquiry": "Guided inquiry", None: "Not set"}


def approach_word(approach: str | None) -> str:
    return APPROACH_WORDS.get(approach, approach or "Not set")


def _reply(turn: AgentTurn) -> dict:
    """The model's reply as it sent it, when it was JSON."""
    try:
        parsed = json.loads(turn.response.get("raw", ""))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def facts(turn: AgentTurn) -> dict:
    """What one student turn did, in the words the pages use."""
    reply = _reply(turn)
    withheld = turn.validation_outcome == "withheld"
    disclosure = reply.get("disclosure") or "none"
    assessment = reply.get("assessment")
    return {
        "step_index": turn.request.get("step_index"),
        "disclosure": disclosure,
        "allowed": turn.context_manifest.get("allowed_disclosure"),
        "hint": not withheld and disclosure == "hint",
        "worked_step": not withheld and disclosure == "partial",
        "answer": not withheld and disclosure == "full",
        # A reply that stated the answer and went out as it was.
        "leaked": turn.leakage_check == "failed" and turn.validation_outcome == "ok",
        "judgment": assessment.get("judgment") if isinstance(assessment, dict) else None,
        "step_done": bool(reply.get("step_done")),
        "signals": [
            {"kind": s.get("kind"), "told": bool(s.get("tell_teacher"))}
            for s in reply.get("signals") or []
            if isinstance(s, dict)
        ],
        "conflicts": list(turn.conflicts or []),
        "outcome": turn.validation_outcome,
        "retried_because": turn.request.get("retry_reason"),
        "guided": bool(turn.request.get("guidance")),
        "latency_ms": turn.latency_ms,
    }


def _tally(turns: list[AgentTurn], alerts: list[Exception_]) -> dict:
    found = [facts(t) for t in turns]
    timed = [t.latency_ms for t in turns if t.latency_ms > 0]
    return {
        "turns": len(turns),
        "mean_latency_ms": round(sum(timed) / len(timed)) if timed else 0,
        "hints": sum(f["hint"] for f in found),
        "worked_steps": sum(f["worked_step"] for f in found),
        "answers_given": sum(f["leaked"] for f in found),
        "checks_failed": sum(bool(f["conflicts"]) for f in found),
        "checks_fixed": sum(bool(f["conflicts"]) and f["outcome"] == "regenerated" for f in found),
        "held_back": sum(f["outcome"] == "withheld" for f in found),
        "alerts": len(alerts),
        "alerts_dealt_with": sum(a.status != ExceptionStatus.OPEN.value for a in alerts),
    }


@dataclass
class Run:
    """One lesson run and everything the pages need about it."""

    session: Session
    contract: LessonContract | None
    brief: LessonBrief
    teacher: str
    class_label: str
    participants: list[SessionParticipant]
    turns: list[AgentTurn]
    states: dict[uuid.UUID, LearningState]
    outcomes: dict[uuid.UUID, LessonOutcome]
    alerts: list[Exception_]
    names: dict[uuid.UUID, str]

    @property
    def title(self) -> str:
        return self.brief.title or (self.contract.title if self.contract else "")

    @property
    def mark_max(self) -> int:
        return sum(c.max for c in self.brief.assessment)

    def finished(self, student_id: uuid.UUID) -> bool:
        state = self.states.get(student_id)
        return bool(state and state.status == LearningStatus.COMPLETED.value)


async def _run(db: AsyncSession, session: Session) -> Run:
    contract = await db.get(LessonContract, session.contract_id)
    brief = LessonBrief.model_validate(contract.brief or {}) if contract else LessonBrief()
    teacher = await db.get(User, contract.teacher_id) if contract else None
    klass = await db.get(Class, session.class_id)
    participants = list(
        (
            await db.scalars(
                select(SessionParticipant).where(SessionParticipant.session_id == session.id)
            )
        ).all()
    )
    turns = list(
        (
            await db.scalars(
                select(AgentTurn)
                .where(AgentTurn.session_id == session.id, AgentTurn.mode == "student")
                .order_by(AgentTurn.created_at)
            )
        ).all()
    )
    states = {
        s.student_id: s
        for s in (
            await db.scalars(select(LearningState).where(LearningState.session_id == session.id))
        ).all()
    }
    outcomes = {
        o.student_id: o
        for o in (
            await db.scalars(select(LessonOutcome).where(LessonOutcome.session_id == session.id))
        ).all()
    }
    alerts = list(
        (
            await db.scalars(
                select(Exception_)
                .where(Exception_.session_id == session.id)
                .order_by(Exception_.created_at)
            )
        ).all()
    )
    ids = {p.student_id for p in participants} | {t.student_id for t in turns if t.student_id}
    names = (
        {u.id: u.pseudonym for u in (await db.scalars(select(User).where(User.id.in_(ids)))).all()}
        if ids
        else {}
    )
    return Run(
        session,
        contract,
        brief,
        teacher.pseudonym if teacher else "",
        klass.label if klass else "",
        participants,
        turns,
        states,
        outcomes,
        alerts,
        names,
    )


def _by_student(run: Run) -> tuple[dict, dict]:
    turns: dict[uuid.UUID, list[AgentTurn]] = defaultdict(list)
    alerts: dict[uuid.UUID, list[Exception_]] = defaultdict(list)
    for t in run.turns:
        turns[t.student_id].append(t)
    for a in run.alerts:
        alerts[a.student_id].append(a)
    return turns, alerts


def _mark_percent(run: Run, student_id: uuid.UUID) -> float | None:
    outcome = run.outcomes.get(student_id)
    if outcome is None or not run.mark_max:
        return None
    total = (
        outcome.confirmed_total if outcome.confirmed_total is not None else outcome.suggested_total
    )
    return 100 * total / run.mark_max


def _lesson_row(run: Run) -> dict:
    took_part = {t.student_id for t in run.turns}
    conditions = {
        condition_word(p.condition) for p in run.participants if p.student_id in took_part
    }
    return {
        "session_id": str(run.session.id),
        "at": when(run.session.opened_at or run.session.created_at),
        "closed_at": when(run.session.closed_at),
        "title": run.title,
        "subject": run.brief.subject or (run.contract.subject if run.contract else ""),
        "unit": run.contract.unit if run.contract else None,
        "teacher": run.teacher,
        "class_label": run.class_label,
        "status": run.session.status,
        "condition": conditions.pop() if len(conditions) == 1 else "Mixed",
        "approach": approach_word(run.contract.approach if run.contract else None),
        "students": len(run.participants),
        "took_part": len(took_part),
        "finished": sum(run.finished(s) for s in took_part),
        "models": sorted({t.model for t in run.turns}),
        "prompt_versions": sorted({t.prompt_version for t in run.turns}),
        **_tally(run.turns, run.alerts),
    }


def _groups(buckets: dict, kind: str) -> list[dict]:
    """One row per group of students, the same shape for conditions and approaches."""
    rows = []
    for (group, name), b in sorted(buckets.items()):
        if group != kind:
            continue
        rows.append(
            {
                "name": name,
                "lessons": len(b["lessons"]),
                "students": b["students"],
                "finished": b["finished"],
                "turns_per_student": round(b["turns"] / b["students"], 1) if b["students"] else 0,
                "help_per_student": round(b["help"] / b["students"], 1) if b["students"] else 0,
                "answers_given": b["answers_given"],
                "checks_failed": b["checks_failed"],
                "alerts": b["alerts"],
                "mean_mark_percent": round(sum(b["marks"]) / len(b["marks"]))
                if b["marks"]
                else None,
            }
        )
    return rows


async def overview(db: AsyncSession) -> dict:
    """The whole study: totals, the conditions side by side, and every lesson as a row."""
    lessons = []
    every_turn: list[AgentTurn] = []
    every_alert: list[Exception_] = []
    students: set[uuid.UUID] = set()
    finished = 0
    buckets: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "lessons": set(),
            "students": 0,
            "finished": 0,
            "turns": 0,
            "help": 0,
            "answers_given": 0,
            "checks_failed": 0,
            "alerts": 0,
            "marks": [],
        }
    )
    for session in (await db.scalars(select(Session).order_by(Session.created_at.desc()))).all():
        run = await _run(db, session)
        if not run.turns:
            continue
        lessons.append(_lesson_row(run))
        every_turn += run.turns
        every_alert += run.alerts
        turns_of, alerts_of = _by_student(run)
        for p in run.participants:
            if p.student_id not in turns_of:
                continue
            students.add(p.student_id)
            finished += run.finished(p.student_id)
            tally = _tally(turns_of[p.student_id], alerts_of.get(p.student_id, []))
            mark = _mark_percent(run, p.student_id)
            approach = approach_word(run.contract.approach if run.contract else None)
            for group in (("condition", condition_word(p.condition)), ("approach", approach)):
                bucket = buckets[group]
                bucket["lessons"].add(session.id)
                bucket["students"] += 1
                bucket["finished"] += run.finished(p.student_id)
                bucket["turns"] += tally["turns"]
                bucket["help"] += tally["hints"] + tally["worked_steps"]
                for key in ("answers_given", "checks_failed", "alerts"):
                    bucket[key] += tally[key]
                if mark is not None:
                    bucket["marks"].append(mark)
    settings = get_settings()
    return {
        "study": {
            "active": settings.study_active,
            "policy": settings.study_policy,
            "supervisor": settings.study_supervisor
            if settings.study_active
            else settings.supervisor_enforce,
            "model": settings.openrouter_model,
            "prompt_versions": sorted({t.prompt_version for t in every_turn}),
        },
        "totals": {
            "lessons": len(lessons),
            "students": len(students),
            "finished": finished,
            **_tally(every_turn, every_alert),
        },
        "conditions": _groups(buckets, "condition"),
        "approaches": _groups(buckets, "approach"),
        "lessons": lessons,
    }


async def lesson(db: AsyncSession, session_id: uuid.UUID) -> dict | None:
    """One lesson run: every student as a row, then what the teacher was told and what the
    checks caught."""
    session = await db.get(Session, session_id)
    if session is None:
        return None
    run = await _run(db, session)
    turns_of, alerts_of = _by_student(run)
    guidance = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.kind == EvidenceKind.TEACHER_GUIDANCE.value,
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()

    students = []
    for p in sorted(run.participants, key=lambda p: run.names.get(p.student_id, "")):
        sid = p.student_id
        turns = turns_of.get(sid, [])
        found = [facts(t) for t in turns]
        tally = _tally(turns, alerts_of.get(sid, []))
        state = run.states.get(sid)
        outcome = run.outcomes.get(sid)
        students.append(
            {
                "student_id": str(sid),
                "pseudonym": run.names.get(sid, ""),
                "condition": condition_word(p.condition),
                "took_part": bool(turns),
                "finished": run.finished(sid),
                "step_index": state.step_index if state else 0,
                "steps_total": len(run.brief.steps),
                "judgments": [s.get("judgment") for s in (state.steps if state else [])],
                **{k: tally[k] for k in ("turns", "hints", "worked_steps", "answers_given")},
                "checks_failed": tally["checks_failed"],
                "check_kinds": sorted({c for f in found for c in f["conflicts"]}),
                "guided": sum(f["guided"] for f in found),
                "alerts": [
                    {
                        "kind": a.kind,
                        "at": when(a.created_at),
                        "status": a.status,
                        "dealt_with_at": when(a.acknowledged_at),
                    }
                    for a in alerts_of.get(sid, [])
                ],
                "mark_suggested": outcome.suggested_total if outcome else None,
                "mark_confirmed": outcome.confirmed_total if outcome else None,
                "needs_look": bool(
                    tally["answers_given"]
                    or tally["checks_failed"]
                    or any(a.status == ExceptionStatus.OPEN.value for a in alerts_of.get(sid, []))
                ),
            }
        )

    return {
        **_lesson_row(run),
        "steps": [s.name for s in run.brief.steps],
        "mark_max": run.mark_max,
        "rules": run.brief.rules.describe(),
        "students": students,
        "alert_list": [
            {
                "id": str(a.id),
                "at": when(a.created_at),
                "kind": a.kind,
                "student_id": str(a.student_id),
                "pseudonym": run.names.get(a.student_id, ""),
                "summary": a.summary,
                "status": a.status,
                "dealt_with_at": when(a.acknowledged_at),
            }
            for a in run.alerts
        ],
        "checks": [
            {
                "at": when(t.created_at),
                "student_id": str(t.student_id),
                "pseudonym": run.names.get(t.student_id, ""),
                "step_index": t.request.get("step_index"),
                "conflicts": list(t.conflicts or []),
                "outcome": t.validation_outcome,
                "retried_because": t.request.get("retry_reason"),
            }
            for t in run.turns
            if t.conflicts
        ],
        "guidance": [
            {
                "at": when(g.created_at),
                "student_id": str(g.student_id),
                "pseudonym": run.names.get(g.student_id, ""),
                "text": g.payload.get("text", ""),
                "shown_to_student": bool(g.payload.get("shown_to_student")),
            }
            for g in guidance
        ],
    }


async def conversation(
    db: AsyncSession, session_id: uuid.UUID, student_id: uuid.UUID
) -> dict | None:
    """One student's lesson, read like a chat, with what each agent turn did beside it."""
    session = await db.get(Session, session_id)
    student = await db.get(User, student_id)
    if session is None or student is None:
        return None
    run = await _run(db, session)
    mine = [t for t in run.turns if t.student_id == student_id]
    by_id = {t.id: t for t in mine}
    convo = await db.scalar(
        select(Conversation).where(
            Conversation.kind == ConversationKind.STUDENT.value,
            Conversation.session_id == session.id,
            Conversation.student_id == student_id,
        )
    )
    messages = (
        (
            await db.scalars(
                select(Message)
                .where(Message.conversation_id == convo.id)
                .order_by(Message.created_at)
            )
        ).all()
        if convo
        else []
    )
    items = []
    for m in messages:
        if m.role == MessageRole.AGENT.value:
            turn = by_id.get(m.turn_id) if m.turn_id else None
            items.append(
                {
                    "kind": "agent",
                    "at": when(m.created_at),
                    "text": m.text,
                    "withheld": bool(m.data.get("withheld")),
                    "turn_id": str(m.turn_id) if m.turn_id else None,
                    **(facts(turn) if turn else {}),
                    "shown": turn.context_manifest if turn else None,
                    "raw": (_reply(turn) or turn.response) if turn else None,
                }
            )
        elif m.role == MessageRole.STUDENT.value:
            items.append({"kind": "student", "at": when(m.created_at), "text": m.text})
        else:
            items.append(
                {
                    "kind": "event",
                    "at": when(m.created_at),
                    "text": m.text,
                    "teacher_only": m.audience == Audience.TEACHER.value,
                }
            )

    state = run.states.get(student_id)
    judged = state.steps if state else []
    steps = [
        {
            "name": s.name,
            "judgment": judged[i].get("judgment") if i < len(judged) else None,
            "attempts": judged[i].get("attempts", 0) if i < len(judged) else 0,
            "reached": bool(state)
            and (i < state.step_index or (i == state.step_index and bool(mine))),
        }
        for i, s in enumerate(run.brief.steps)
    ]

    # The earlier lessons whose records the agent was shown about this student.
    retrieved: set[uuid.UUID] = set()
    for t in mine:
        for rid in t.context_manifest.get("retrieved_ids", []):
            try:
                retrieved.add(uuid.UUID(str(rid)))
            except ValueError:
                continue
    earlier: list[dict] = []
    if retrieved:
        sessions_seen = {
            r.session_id
            for r in (
                await db.scalars(select(EvidenceRecord).where(EvidenceRecord.id.in_(retrieved)))
            ).all()
        }
        for sid in sessions_seen:
            other = await db.get(Session, sid)
            contract = await db.get(LessonContract, other.contract_id) if other else None
            if other and contract:
                brief = LessonBrief.model_validate(contract.brief or {})
                earlier.append(
                    {
                        "title": brief.title or contract.title,
                        "at": when(other.opened_at or other.created_at),
                    }
                )

    teacher_part: list[dict] = []
    for a in run.alerts:
        if a.student_id != student_id:
            continue
        teacher_part.append({"at": when(a.created_at), "what": "alert", "kind": a.kind})
        if a.acknowledged_at:
            teacher_part.append(
                {"at": when(a.acknowledged_at), "what": "dealt_with", "kind": a.kind}
            )
    for g in (
        await db.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.student_id == student_id,
                EvidenceRecord.kind == EvidenceKind.TEACHER_GUIDANCE.value,
            )
        )
    ).all():
        teacher_part.append(
            {
                "at": when(g.created_at),
                "what": "guidance",
                "text": g.payload.get("text", ""),
                "shown_to_student": bool(g.payload.get("shown_to_student")),
            }
        )
    for log in (
        await db.scalars(
            select(TeacherAccessLog).where(
                TeacherAccessLog.session_id == session.id,
                TeacherAccessLog.student_id == student_id,
                TeacherAccessLog.action == TeacherAction.TRANSCRIPT_DRILLDOWN.value,
            )
        )
    ).all():
        teacher_part.append({"at": when(log.created_at), "what": "read_conversation"})
    outcome = run.outcomes.get(student_id)
    if outcome and outcome.confirmed_at:
        teacher_part.append(
            {
                "at": when(outcome.confirmed_at),
                "what": "mark",
                "total": outcome.confirmed_total,
                "comment": outcome.comment,
            }
        )
    teacher_part.sort(key=lambda x: x["at"] or "")

    took_part = sorted(
        (
            p.student_id
            for p in run.participants
            if any(t.student_id == p.student_id for t in mine or run.turns)
        ),
        key=lambda s: run.names.get(s, ""),
    )
    took_part = [s for s in took_part if s in {t.student_id for t in run.turns}]
    where = took_part.index(student_id) if student_id in took_part else -1
    neighbour = lambda i: (  # noqa: E731 - two lookups, one shape
        {"student_id": str(took_part[i]), "pseudonym": run.names.get(took_part[i], "")}
        if 0 <= i < len(took_part)
        else None
    )
    participant = next((p for p in run.participants if p.student_id == student_id), None)
    return {
        "session_id": str(session.id),
        "student_id": str(student_id),
        "pseudonym": student.pseudonym,
        "title": run.title,
        "at": when(session.opened_at or session.created_at),
        "condition": condition_word(participant.condition if participant else None),
        "approach": approach_word(run.contract.approach if run.contract else None),
        "turns": len(mine),
        "models": sorted({t.model for t in mine}),
        "prompt_versions": sorted({t.prompt_version for t in mine}),
        "mean_latency_ms": _tally(mine, [])["mean_latency_ms"],
        "steps": steps,
        "rules": run.brief.rules.describe(),
        "earlier": sorted(earlier, key=lambda e: e["at"] or ""),
        "memory_used": any(t.context_manifest.get("retrieved_used") for t in mine),
        "teacher": teacher_part,
        "mark": {
            "suggested": outcome.suggested_total if outcome else None,
            "confirmed": outcome.confirmed_total if outcome else None,
            "max": run.mark_max,
            "comment": outcome.comment if outcome else None,
        },
        "previous": neighbour(where - 1) if where >= 0 else None,
        "next": neighbour(where + 1) if where >= 0 else None,
        "items": items,
    }
