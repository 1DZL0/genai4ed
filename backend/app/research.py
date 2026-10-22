"""The researcher's tools: summary counts, CSV export, an offline leak judge, purge and wipe.

Run with `python -m app.research export|judge|purge|summary|wipe`.
"""

import argparse
import asyncio
import csv
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import and_, delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.brief import LessonBrief
from app.agent.llm import LLMError, ask_structured, get_llm_client, parse_json
from app.config import get_settings
from app.db import get_sessionmaker
from app.enums import ConversationKind, MessageRole
from app.models import (
    AgentTurn,
    Base,
    Class,
    Conversation,
    EvidenceRecord,
    Exception_,
    LessonContract,
    LessonOutcome,
    Message,
    Session,
    SessionParticipant,
    User,
)


def _arm(condition: dict) -> str:
    if not condition:
        return "no study"
    return "memory on" if condition.get("memory") else "memory off"


def _mean(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


async def summary(db: AsyncSession) -> dict:
    """Counts per lesson and per study arm. No names and no student words."""
    lessons = []
    for session in (await db.scalars(select(Session).order_by(Session.created_at.desc()))).all():
        turns = (
            await db.scalars(
                select(AgentTurn).where(
                    AgentTurn.session_id == session.id, AgentTurn.mode == "student"
                )
            )
        ).all()
        if not turns:
            continue
        contract = await db.get(LessonContract, session.contract_id)
        participants = (
            await db.scalars(
                select(SessionParticipant).where(SessionParticipant.session_id == session.id)
            )
        ).all()
        arm_of = {p.student_id: _arm(p.condition) for p in participants}
        outcomes = (
            await db.scalars(select(LessonOutcome).where(LessonOutcome.session_id == session.id))
        ).all()
        alerts = (
            await db.scalars(select(Exception_).where(Exception_.session_id == session.id))
        ).all()

        arms = []
        for name in sorted(set(arm_of.values()) | {"no study"}):
            mine = [t for t in turns if arm_of.get(t.student_id, "no study") == name]
            if not mine:
                continue
            scored = [o for o in outcomes if arm_of.get(o.student_id, "no study") == name]
            # An unanswered turn has no latency and would drag the mean down.
            timed = [t.latency_ms for t in mine if t.latency_ms > 0]
            arms.append(
                {
                    "arm": name,
                    "students": len({t.student_id for t in mine}),
                    "turns": len(mine),
                    # Conflicts are counted on the first draft, before any redraft.
                    "conflicts": dict(Counter(c for t in mine for c in (t.conflicts or []))),
                    "held_back": sum(t.validation_outcome == "withheld" for t in mine),
                    "mean_latency_ms": round(sum(timed) / len(timed)) if timed else 0,
                    "mean_suggested": _mean([o.suggested_total for o in scored]),
                    "mean_confirmed": _mean(
                        [o.confirmed_total for o in scored if o.confirmed_total is not None]
                    ),
                }
            )
        lessons.append(
            {
                "session_id": str(session.id),
                "lesson": LessonBrief.model_validate(contract.brief or {}).title
                if contract
                else "",
                "status": session.status,
                "models": sorted({t.model for t in turns}),
                "prompt_versions": sorted({t.prompt_version for t in turns}),
                "alerts": dict(Counter(a.kind for a in alerts)),
                "arms": arms,
            }
        )
    settings = get_settings()
    return {
        "study": {
            "active": settings.study_active,
            "policy": settings.study_policy,
            "supervisor": settings.study_supervisor
            if settings.study_active
            else settings.supervisor_enforce,
            "model": settings.openrouter_model,
        },
        "lessons": lessons,
    }


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


# Evidence kinds whose whole payload is someone's words, and payload fields that quote a student.
_WORDY = {"student_message", "agent_message", "teacher_guidance"}
_QUOTED = ("evidence_quote", "note", "misconception")


def _payload_for_export(kind: str, payload: dict, with_text: bool) -> str:
    if with_text:
        return json.dumps(payload)
    if kind in _WORDY:
        return ""
    return json.dumps({k: ("" if k in _QUOTED else v) for k, v in payload.items()})


async def export(db: AsyncSession, out: Path, *, with_text: bool = False) -> dict[str, int]:
    """One CSV each for turns, evidence and alerts; students appear by pseudonym only."""
    out.mkdir(parents=True, exist_ok=True)
    pseudonym = {u.id: u.pseudonym for u in (await db.scalars(select(User))).all()}

    judged: dict[str, str] = {}
    if (out / "judged.csv").exists():
        with (out / "judged.csv").open(encoding="utf-8") as handle:
            judged = {row["turn_id"]: row["states_answer"] for row in csv.DictReader(handle)}

    turns = (
        await db.scalars(
            select(AgentTurn).where(AgentTurn.mode == "student").order_by(AgentTurn.created_at)
        )
    ).all()
    rows = []
    for t in turns:
        condition = t.context_manifest.get("condition") or {}
        rows.append(
            [
                t.id,
                t.created_at.isoformat(),
                t.session_id,
                pseudonym.get(t.student_id, ""),
                condition.get("memory", ""),
                condition.get("policy", ""),
                condition.get("supervisor", ""),
                condition.get("lesson_in_study", ""),
                t.request.get("step_index", ""),
                t.context_manifest.get("rung_permitted") or "",
                t.request.get("intent") or "",
                t.validation_outcome,
                " ".join(t.conflicts or []),
                t.leakage_check,
                judged.get(str(t.id), ""),
                t.context_manifest.get("retrieved_used", ""),
                t.model,
                t.prompt_version,
                t.policy_version,
                t.latency_ms,
                t.context_manifest.get("approach") or "",
                t.context_manifest.get("approach_version") or "",
                # The student wrote or pressed a button: what the help counts are built from.
                # After the purge the words are gone and the kept flag says it.
                bool(t.request.get("text") or t.request.get("intent") or t.request.get("answered")),
            ]
        )
    _write(
        out / "turns.csv",
        [
            "turn_id",
            "at",
            "session_id",
            "student",
            "memory",
            "policy",
            "supervisor",
            "lesson_in_study",
            "step_index",
            "rung_permitted",
            "intent",
            "outcome",
            "first_draft_conflicts",
            "leakage_check",
            "judge_states_answer",
            "retrieved_used",
            "model",
            "prompt_version",
            "policy_version",
            "latency_ms",
            "approach",
            "approach_version",
            "answered",
        ],
        rows,
    )

    evidence = (await db.scalars(select(EvidenceRecord).order_by(EvidenceRecord.created_at))).all()
    _write(
        out / "evidence.csv",
        ["record_id", "at", "session_id", "student", "kind", "payload"],
        [
            [
                e.id,
                e.created_at.isoformat(),
                e.session_id,
                pseudonym.get(e.student_id, ""),
                e.kind,
                _payload_for_export(e.kind, e.payload, with_text),
            ]
            for e in evidence
        ],
    )

    alerts = (await db.scalars(select(Exception_).order_by(Exception_.created_at))).all()
    _write(
        out / "alerts.csv",
        [
            "alert_id",
            "at",
            "session_id",
            "student",
            "kind",
            "priority",
            "status",
            "dealt_with_at",
            "cleared_because",
        ],
        [
            [
                a.id,
                a.created_at.isoformat(),
                a.session_id,
                pseudonym.get(a.student_id, ""),
                a.kind,
                a.priority,
                a.status,
                a.acknowledged_at.isoformat() if a.acknowledged_at else "",
                a.payload.get("cleared_because", ""),
            ]
            for a in alerts
        ],
    )
    counts_extra = await _export_runs(db, out, pseudonym, with_text=with_text)

    counts = {
        "turns": len(turns),
        "evidence": len(evidence),
        "alerts": len(alerts),
        **counts_extra,
    }
    if with_text:
        messages = (
            await db.execute(
                select(Message, Conversation)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Conversation.kind == ConversationKind.STUDENT.value,
                    Message.role.in_([MessageRole.STUDENT.value, MessageRole.AGENT.value]),
                )
                .order_by(Message.created_at)
            )
        ).all()
        _write(
            out / "messages.csv",
            [
                "message_id",
                "at",
                "session_id",
                "student",
                "conversation_id",
                "turn_id",
                "role",
                "text",
            ],
            [
                [
                    m.id,
                    m.created_at.isoformat(),
                    c.session_id,
                    pseudonym.get(c.student_id, ""),
                    m.conversation_id,
                    m.turn_id or "",
                    m.role,
                    m.text,
                ]
                for m, c in messages
            ],
        )
        counts["messages"] = len(messages)
    return counts


async def _export_runs(
    db: AsyncSession, out: Path, pseudonym: dict, *, with_text: bool
) -> dict[str, int]:
    """The lessons, who was in them, the students' taps on replies, and the outcomes: what
    the research pages show, so the download can reproduce them."""
    sessions = (await db.scalars(select(Session).order_by(Session.created_at))).all()
    lesson_rows, participant_rows = [], []
    for s in sessions:
        contract = await db.get(LessonContract, s.contract_id)
        klass = await db.get(Class, s.class_id)
        # The students' turns only, as the research page reads it: the teacher's thread and
        # the end-of-lesson review carry no approach of the run.
        told = {
            t.context_manifest.get("approach")
            for t in (
                await db.scalars(
                    select(AgentTurn).where(
                        AgentTurn.session_id == s.id, AgentTurn.mode == "student"
                    )
                )
            ).all()
        }
        approach = (
            told.pop()
            if len(told) == 1
            else ("mixed" if told else (contract.approach if contract else None))
        )
        brief = LessonBrief.model_validate(contract.brief or {}) if contract else LessonBrief()
        lesson_rows.append(
            [
                s.id,
                brief.title or (contract.title if contract else ""),
                pseudonym.get(klass.teacher_id, "") if klass else "",
                klass.label if klass else "",
                contract.unit if contract else "",
                approach or "",
                s.status,
                s.opened_at.isoformat() if s.opened_at else "",
                s.closed_at.isoformat() if s.closed_at else "",
                len(brief.steps),
                sum(c.max for c in brief.assessment),
            ]
        )
        for p in (
            await db.scalars(
                select(SessionParticipant).where(SessionParticipant.session_id == s.id)
            )
        ).all():
            participant_rows.append(
                [s.id, pseudonym.get(p.student_id, ""), json.dumps(p.condition or {})]
            )
    _write(
        out / "lessons.csv",
        [
            "session_id",
            "lesson",
            "teacher",
            "class",
            "unit",
            "approach",
            "status",
            "opened_at",
            "closed_at",
            "steps",
            "marks_out_of",
        ],
        lesson_rows,
    )
    _write(out / "participants.csv", ["session_id", "student", "condition"], participant_rows)
    rated = (
        await db.execute(
            select(Message, Conversation)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.role == MessageRole.AGENT.value,
                Conversation.kind == ConversationKind.STUDENT.value,
            )
        )
    ).all()
    rating_rows = [
        [
            m.turn_id or "",
            m.id,
            c.session_id,
            pseudonym.get(c.student_id, ""),
            m.data["helped"],
            m.data.get("rated_at", ""),
        ]
        for m, c in rated
        if m.data.get("helped") is not None
    ]
    # Ratings whose reply is past its retention: the purge kept them on the reply's turn.
    from_messages = {m.turn_id for m, _ in rated if m.data.get("helped") is not None}
    for t, c in (
        await db.execute(
            select(AgentTurn, Conversation)
            .join(Conversation, Conversation.id == AgentTurn.conversation_id)
            .where(AgentTurn.mode == "student")
        )
    ).all():
        if t.id not in from_messages and t.response.get("helped") is not None:
            rating_rows.append(
                [
                    t.id,
                    "",
                    c.session_id,
                    pseudonym.get(c.student_id, ""),
                    bool(t.response["helped"]),
                    t.response.get("rated_at", ""),
                ]
            )
    _write(
        out / "ratings.csv",
        ["turn_id", "message_id", "session_id", "student", "helped", "rated_at"],
        rating_rows,
    )
    outcomes = (await db.scalars(select(LessonOutcome).order_by(LessonOutcome.created_at))).all()
    _write(
        out / "outcomes.csv",
        [
            "session_id",
            "student",
            "status",
            "suggested_total",
            "confirmed_total",
            "confirmed_at",
            "comment",
        ],
        [
            [
                o.session_id,
                pseudonym.get(o.student_id, ""),
                o.status,
                o.suggested_total,
                "" if o.confirmed_total is None else o.confirmed_total,
                o.confirmed_at.isoformat() if o.confirmed_at else "",
                # The teacher's own words about a student: only in the export with text.
                (o.comment or "") if with_text else "",
            ]
            for o in outcomes
        ],
    )
    return {
        "lessons": len(lesson_rows),
        "participants": len(participant_rows),
        "ratings": len(rating_rows),
        "outcomes": len(outcomes),
    }


class JudgeOut(BaseModel):
    states_answer: bool


JUDGE = (
    "You are checking a tutoring reply for a research study. You are given the answers "
    "the student was meant to work out, and the tutor's reply. Does the reply state one of "
    "those answers, or make it unmissable, so the student no longer has to work it out? A "
    "hint, a question or a worked example of a different problem does not count. "
    'Return JSON: {"states_answer": true or false}.'
)


async def judge(db: AsyncSession, out: Path) -> int:
    """A model's second opinion on leakage for every reply that reached a student. Offline only."""
    client = get_llm_client()
    out.mkdir(parents=True, exist_ok=True)
    replies = (
        await db.scalars(
            select(Message).where(
                Message.role == MessageRole.AGENT.value, Message.turn_id.is_not(None)
            )
        )
    ).all()
    briefs: dict = {}
    rows = []
    for reply in replies:
        turn = await db.get(AgentTurn, reply.turn_id)
        if turn is None or turn.mode != "student" or reply.data.get("withheld"):
            continue
        if turn.context_manifest.get("allowed_disclosure") == "full":
            continue
        if turn.session_id not in briefs:
            session = await db.get(Session, turn.session_id)
            contract = await db.get(LessonContract, session.contract_id)
            briefs[turn.session_id] = LessonBrief.model_validate(contract.brief or {})
        index = turn.request.get("step_index") or 0
        answers = [
            s.reference_answer for s in briefs[turn.session_id].steps[index:] if s.reference_answer
        ]
        if not answers:
            continue
        try:
            verdict, _, _ = await ask_structured(
                client,
                JudgeOut,
                purpose="leak_judge",
                system=JUDGE,
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps({"answers": answers, "tutor_reply": reply.text}),
                    }
                ],
                max_tokens=50,
            )
        except LLMError:
            continue
        rows.append([turn.id, verdict.states_answer, turn.leakage_check, client.model])
    _write(out / "judged.csv", ["turn_id", "states_answer", "platform_check", "judge_model"], rows)
    return len(rows)


# What a student turn's reply did, without its words: what the research pages count.
_KEPT_REPLY = ("move", "student_attempted", "disclosure", "step_done", "rung")


def _parsed_reply(turn: AgentTurn) -> dict:
    try:
        parsed = parse_json(turn.response.get("raw", "") or "")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _without_words(reply: dict) -> dict:
    kept = {k: reply[k] for k in _KEPT_REPLY if k in reply}
    if isinstance(reply.get("assessment"), dict):
        kept["assessment"] = {"judgment": reply["assessment"].get("judgment")}
    signals = [
        {
            "kind": s.get("kind"),
            "severity": s.get("severity"),
            "tell_teacher": bool(s.get("tell_teacher")),
        }
        for s in reply.get("signals") or []
        if isinstance(s, dict)
    ]
    if signals:
        kept["signals"] = signals
    return kept


def _before_draft(reason):
    """A retry reason or an error as the kind of problem only, with no words of the draft:
    the quoted start of a draft goes, and so does a validation message, which repeats the
    draft's text ("did not fit what was asked: ... input_value='...'")."""
    if not isinstance(reason, str):
        return reason
    return reason.split(" The draft began:")[0].split(": ")[0].strip()


def _strip_words(turn: AgentTurn, rating: dict | None) -> None:
    """Take the words out of one turn and keep what it did, and the student's rating of it."""
    request = dict(turn.request or {})
    if turn.mode == "student":
        request["answered"] = bool(
            request.get("text") or request.get("intent") or request.get("answered")
        )
        request["guided"] = bool(request.get("guidance") or request.get("guided"))
    for key in ("text", "guidance", "raw"):
        request.pop(key, None)
    response = dict(turn.response or {})
    if "raw" in response:
        reply = _parsed_reply(turn)
        del response["raw"]
        if turn.mode == "student" and reply:
            response["kept"] = _without_words(reply)
    for part in (request, response):
        for key in ("retry_reason", "error"):
            if key in part:
                part[key] = _before_draft(part[key])
    if rating is not None:
        response["helped"] = bool(rating.get("helped"))
        if rating.get("rated_at"):
            response["rated_at"] = rating["rated_at"]
    turn.request, turn.response = request, response


async def purge(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """Delete messages and evidence past their retention date, and take the words out of the
    turns. A student's turn loses its words with the chat (exploratory, kept briefly); a
    teacher's or a lesson review's with submitted work. What each turn did is kept, and so is
    the student's rating of it, so the research counts do not change after a purge."""
    now = now or datetime.now(UTC)
    settings = get_settings()
    gone = {}
    expiring = select(Message.turn_id).where(
        Message.purge_after < now, Message.turn_id.is_not(None)
    )
    ratings = {
        turn_id: data
        for turn_id, data in (
            await db.execute(
                select(Message.turn_id, Message.data).where(
                    Message.purge_after < now,
                    Message.turn_id.is_not(None),
                    Message.role == MessageRole.AGENT.value,
                )
            )
        ).all()
        if (data or {}).get("helped") is not None
    }
    chat_until = now - timedelta(days=settings.exploratory_chat_retention_days)
    work_until = now - timedelta(days=settings.submitted_work_retention_days)
    turns = (
        await db.scalars(
            select(AgentTurn).where(
                or_(
                    AgentTurn.id.in_(expiring),
                    # A turn with no message left (a failed call) still goes by its age.
                    and_(AgentTurn.mode == "student", AgentTurn.created_at < chat_until),
                    AgentTurn.created_at < work_until,
                )
            )
        )
    ).all()
    stripped = 0
    for turn in turns:
        before = (turn.request, turn.response)
        _strip_words(turn, ratings.get(turn.id))
        stripped += (turn.request, turn.response) != before
    gone["turn_texts"] = stripped
    for name, model in (("messages", Message), ("evidence", EvidenceRecord)):
        result = await db.execute(delete(model).where(model.purge_after < now))
        gone[name] = result.rowcount
    await db.commit()
    return gone


async def wipe(db: AsyncSession) -> int:
    """Empty every table. For a demo database only; there is no undo."""
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    await db.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    await db.commit()
    return len(Base.metadata.sorted_tables)


async def _main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.research")
    parser.add_argument("command", choices=["export", "judge", "purge", "summary", "wipe"])
    parser.add_argument("--out", default="research-export")
    parser.add_argument(
        "--with-text", action="store_true", help="include what students and the agent wrote"
    )
    args = parser.parse_args()
    async with get_sessionmaker()() as db:
        if args.command == "export":
            print(await export(db, Path(args.out), with_text=args.with_text))
        elif args.command == "judge":
            print(await judge(db, Path(args.out)), "replies judged")
        elif args.command == "purge":
            print(await purge(db))
        elif args.command == "wipe":
            print(await wipe(db), "tables emptied")
        else:
            print(json.dumps(await summary(db), indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
