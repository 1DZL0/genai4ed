"""The researcher's tools: summary counts, CSV export, an offline leak judge, purge and wipe.

Run with `python -m app.research export|judge|purge|summary|wipe`.
"""

import argparse
import asyncio
import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.brief import LessonBrief
from app.agent.llm import LLMError, ask_structured, get_llm_client
from app.config import get_settings
from app.db import get_sessionmaker
from app.enums import MessageRole
from app.models import (
    AgentTurn,
    Base,
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
_QUOTED = ("evidence_quote", "note")


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
        ["alert_id", "at", "session_id", "student", "kind", "priority", "status"],
        [
            [
                a.id,
                a.created_at.isoformat(),
                a.session_id,
                pseudonym.get(a.student_id, ""),
                a.kind,
                a.priority,
                a.status,
            ]
            for a in alerts
        ],
    )

    counts = {"turns": len(turns), "evidence": len(evidence), "alerts": len(alerts)}
    if with_text:
        messages = (
            await db.scalars(
                select(Message)
                .where(Message.role.in_([MessageRole.STUDENT.value, MessageRole.AGENT.value]))
                .order_by(Message.created_at)
            )
        ).all()
        _write(
            out / "messages.csv",
            ["message_id", "at", "conversation_id", "turn_id", "role", "text"],
            [
                [m.id, m.created_at.isoformat(), m.conversation_id, m.turn_id or "", m.role, m.text]
                for m in messages
            ],
        )
        counts["messages"] = len(messages)
    return counts


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


async def purge(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """Delete messages and evidence past their retention date."""
    now = now or datetime.now(UTC)
    gone = {}
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
