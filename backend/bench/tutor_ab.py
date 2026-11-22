"""The tutor A/B: the same situations, the same student words, today's prompt against a new one.

Each situation (bench.tutor_ab_cases) is seeded in a scratch database the way the app keeps a
lesson: the teacher, a class, the student with what the tutor remembers of them, the approved
lesson and an open session. The student's messages are driven through the real tutor
(StudentAgent.respond), so the prompt, the reply schema and the platform's checks all run as
they do in a lesson. A different model then reads each conversation, without being told which
prompt wrote it, and answers each of the situation's criteria pass or fail with a reason.

From backend/, with the database container up and the repo's .env (never printed):

    uv run python -m bench.tutor_ab --label old --repeat 3
    uv run python -m bench.tutor_ab --label new --repeat 3
    uv run python -m bench.tutor_ab --compare old new

To run today's prompt, run the first line from a git worktree at the commit before the prompt
changed. It writes only to the database genai4ed_ab, which it rebuilds at the start.
"""

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent import learner
from app.agent.brief import LessonBrief
from app.agent.learner import Line
from app.agent.llm import LLMError, OpenRouterClient
from app.agent.policy import PolicyRules
from app.agent.student_mode import AgentUnavailable, MoveRefused, StudentAgent, prompt_version
from app.config import get_settings
from app.db import Base
from app.enums import ContractStatus, NoteCategory, NoteSource, Role, SessionStatus
from app.models import (
    AgentTurn,
    Class,
    Enrolment,
    LessonContract,
    Session,
    SessionParticipant,
    User,
)
from bench.tutor_ab_cases import SITUATIONS, Situation

DATABASE = "genai4ed_ab"
JUDGE_MODEL = "anthropic/claude-sonnet-5.5"
OUT = Path(__file__).parent / "out"
# What the judge is told to keep from a tutor reply: the words the student saw, never a field
# only one prompt version writes.
_KEPT = ("message", "move", "assessment", "pitch", "pitch_call", "pitch_changed", "signals")

_JUDGE_SYSTEM = (
    "You check one thing about how a tutor talked to a student. You are shown the lesson step, "
    "what the tutor knew about the student, and the conversation. Judge only the tutor's "
    "replies against the thing to check. Answer passed true or false, and give the reason in "
    "one sentence, quoting the tutor where it helps."
)
_VERDICT = {
    "type": "object",
    "properties": {"passed": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["passed", "reason"],
    "additionalProperties": False,
}


@dataclass
class Seeded:
    teacher: User
    student: User
    contract: LessonContract
    session: Session


@dataclass
class Run:
    transcript: list[dict]
    fields: list[dict]
    error: str | None
    prompt_version: str


@dataclass
class Verdict:
    criterion: str
    passed: bool | None
    reason: str


def guarded_url(url: str) -> str:
    """The URL unchanged when it names the scratch database; anything else stops the run."""
    name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if name != DATABASE:
        raise SystemExit(f"tutor_ab writes only to {DATABASE}, not {name}")
    return url


def _brief(s: Situation) -> LessonBrief:
    rules = {
        **PolicyRules().model_dump(mode="json"),
        **(s.rules or {}),
        "adapt_to_student": s.adapt,
    }
    return LessonBrief.model_validate(
        {
            "title": f"A/B {s.id}",
            "subject": s.subject,
            "age": s.age,
            "duration_minutes": 30,
            "objectives": [st["goal"] for st in s.steps],
            "steps": list(s.steps),
            "rules": rules,
        }
    )


async def seed(db: AsyncSession, s: Situation) -> Seeded:
    """The situation as the app keeps it. The memory is written before the session opens, so
    the lesson is told it as it would be told a note from an earlier lesson."""
    tag = uuid.uuid4().hex[:6]
    teacher = User(pseudonym=f"ab-teacher-{tag}", role=Role.TEACHER.value)
    student = User(pseudonym=f"AB-{tag}", role=Role.STUDENT.value)
    db.add_all([teacher, student])
    await db.flush()
    klass = Class(teacher_id=teacher.id, label=f"AB {tag}")
    db.add(klass)
    await db.flush()
    db.add(Enrolment(class_id=klass.id, student_id=student.id))
    if s.memory_learns or s.memory_knows:
        await learner.write(
            db,
            student_id=student.id,
            written=list(s.memory_learns) or None,
            knows=[
                Line(said, NoteCategory.TOPIC_KNOWLEDGE, NoteSource.COUNTED, subject=s.subject)
                for said in s.memory_knows
            ]
            or None,
        )
    await db.commit()
    now = datetime.now(UTC)
    brief = _brief(s)
    contract = LessonContract(
        teacher_id=teacher.id,
        title=brief.title,
        subject=brief.subject,
        status=ContractStatus.ACTIVE.value,
        version=1,
        brief=brief.model_dump(mode="json"),
        activated_at=now,
        activated_by=teacher.id,
    )
    db.add(contract)
    await db.flush()
    session = Session(
        contract_id=contract.id,
        class_id=klass.id,
        status=SessionStatus.OPEN.value,
        opened_at=now + timedelta(seconds=1),
        closes_at=now + timedelta(minutes=50),
    )
    db.add(session)
    await db.flush()
    db.add(SessionParticipant(session_id=session.id, student_id=student.id))
    await db.commit()
    return Seeded(teacher=teacher, student=student, contract=contract, session=session)


async def _fields(db: AsyncSession, seeded: Seeded) -> list[dict]:
    """Each tutor turn as it was recorded: the reply's fields, or the error a failed turn kept."""
    turns = (
        await db.scalars(
            select(AgentTurn)
            .where(
                AgentTurn.session_id == seeded.session.id,
                AgentTurn.student_id == seeded.student.id,
                AgentTurn.mode == "student",
            )
            .order_by(AgentTurn.created_at)
        )
    ).all()
    found = []
    for turn in turns:
        if "error" in (turn.response or {}):
            found.append({"error": turn.response["error"]})
            continue
        try:
            data = json.loads((turn.response or {}).get("raw") or "{}")
        except json.JSONDecodeError:
            data = {}
        found.append({k: data.get(k) for k in (*_KEPT, "error_kind")} | _assessed(data))
    return found


def _assessed(data: dict) -> dict:
    assessment = data.get("assessment") or {}
    return {"error_kind": assessment.get("error_kind"), "judgment": assessment.get("judgment")}


async def run_one(db: AsyncSession, s: Situation, agent: StudentAgent) -> Run:
    """The tutor's opening, then each of the student's messages and the tutor's answer. A turn
    that fails ends the run with its reason; the transcript keeps what came before."""
    seeded = await seed(db, s)
    transcript: list[dict] = []
    error = None

    async def say(text_: str | None) -> None:
        result = await agent.respond(
            db,
            session=seeded.session,
            contract=seeded.contract,
            student=seeded.student,
            text=text_,
        )
        transcript.append({"who": "tutor", "text": result.reply.text})

    try:
        await say(None)
        for line in s.student:
            transcript.append({"who": "student", "text": line})
            await say(line)
    except (AgentUnavailable, LLMError, MoveRefused, ValueError) as exc:
        # Kept as the run's result: the set goes on.
        error = f"{type(exc).__name__}: {exc}"[:500]
        await db.rollback()
    return Run(
        transcript=transcript,
        fields=await _fields(db, seeded),
        error=error,
        prompt_version=prompt_version(),
    )


def judge_input(s: Situation, run: Run) -> str:
    """What the judge reads: the step, what the tutor knew, and the words both sides saw."""
    steps = "\n".join(f"- {st['goal']} (done when: {st['success_criteria'][0]})" for st in s.steps)
    knew = [*s.memory_learns, *s.memory_knows] or ["nothing from earlier lessons"]
    talk = "\n".join(
        f"{'Tutor' if line['who'] == 'tutor' else 'Student'}: {line['text']}"
        for line in run.transcript
    )
    return (
        f"The lesson ({s.subject}, students aged {s.age}):\n{steps}\n\n"
        "What the tutor knew about this student:\n- " + "\n- ".join(knew) + "\n\n"
        f"The conversation:\n{talk}"
    )


async def judge(client, s: Situation, run: Run) -> list[Verdict]:
    """One verdict per criterion. A reply without a true or false is asked for once more, then
    kept as no verdict, which never counts as a pass."""
    shown = judge_input(s, run)
    verdicts = []
    for criterion in s.criteria:
        verdict = Verdict(criterion=criterion, passed=None, reason="no verdict")
        for _ in range(2):
            try:
                result = await client.complete(
                    purpose="tutor_ab_judge",
                    system=_JUDGE_SYSTEM,
                    messages=[
                        {"role": "user", "content": f"{shown}\n\nThe thing to check: {criterion}"}
                    ],
                    schema=_VERDICT,
                    max_tokens=400,
                )
            except LLMError as exc:
                verdict.reason = f"no verdict: {exc}"[:300]
                continue
            data = result.data if isinstance(result.data, dict) else {}
            if isinstance(data.get("passed"), bool):
                verdict = Verdict(criterion, data["passed"], str(data.get("reason", ""))[:400])
                break
            verdict.reason = f"no verdict: {str(data.get('reason', ''))[:200]}"
        verdicts.append(verdict)
    return verdicts


def report(old: list[dict], new: list[dict]) -> str:
    """One line per situation and criterion: passes out of runs for each side, and how many
    runs gave no verdict or failed."""

    def tally(rows: list[dict]) -> dict:
        out: dict = {}
        for row in rows:
            for n, v in enumerate(row["verdicts"]):
                key = (row["situation"], n)
                passed, runs, none = out.get(key, (0, 0, 0))
                out[key] = (passed + (v["passed"] is True), runs + 1, none + (v["passed"] is None))
        return out

    a, b = tally(old), tally(new)
    lines = [f"{'situation':22} {'criterion':4} {'old':>8} {'new':>8}"]
    for key in sorted(set(a) | set(b), key=lambda k: (k[0], k[1])):
        cells = []
        for side in (a, b):
            passed, runs, none = side.get(key, (0, 0, 0))
            cells.append(f"{passed}/{runs}" + (f" ({none} no verdict)" if none else ""))
        lines.append(f"{key[0]:22} {key[1] + 1:<4} {cells[0]:>8} {cells[1]:>8}")
    failed = {
        side: sum(1 for row in rows if row.get("error"))
        for side, rows in (("old", old), ("new", new))
    }
    lines.append(f"runs that failed: old {failed['old']}, new {failed['new']}")
    return "\n".join(lines)


async def _fresh_database(url: str) -> None:
    server = create_async_engine(url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    async with server.connect() as conn:
        found = await conn.scalar(
            text("select 1 from pg_database where datname = :n"), {"n": DATABASE}
        )
        if not found:
            await conn.execute(text(f'create database "{DATABASE}"'))
    await server.dispose()
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        existing = (
            await conn.execute(text("select tablename from pg_tables where schemaname = 'public'"))
        ).scalars()
        for table in existing:
            await conn.execute(text(f'drop table if exists "{table}" cascade'))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _run(label: str, repeat: int, only: set[str]) -> None:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise SystemExit("tutor_ab needs OPENROUTER_API_KEY (from the repo's .env)")
    url = guarded_url(settings.database_url.rsplit("/", 1)[0] + "/" + DATABASE)
    await _fresh_database(url)
    engine = create_async_engine(url, pool_size=10)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    judge_client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        model=JUDGE_MODEL,
        timeout=settings.openrouter_timeout_s,
    )
    chosen = [s for s in SITUATIONS if not only or s.id in only]
    gate = asyncio.Semaphore(6)

    async def one(s: Situation, n: int) -> dict:
        async with gate, maker() as db:
            run = await run_one(db, s, StudentAgent())
            verdicts = await judge(judge_client, s, run)
            mark = " ".join(
                "pass" if v.passed else "fail" if v.passed is False else "none" for v in verdicts
            )
            print(
                f"  {s.id:22} run {n + 1}: {mark}",
                f"(failed: {run.error})" if run.error else "",
            )
            return {
                "situation": s.id,
                "targets": list(s.targets),
                "run": n + 1,
                **asdict(run),
                "verdicts": [asdict(v) for v in verdicts],
            }

    print(
        f"{len(chosen)} situations x {repeat}, tutor {settings.openrouter_model},",
        f"prompt {prompt_version()}, judge {JUDGE_MODEL}",
    )
    rows = await asyncio.gather(*(one(s, n) for s in chosen for n in range(repeat)))
    await engine.dispose()
    OUT.mkdir(exist_ok=True)
    path = OUT / f"tutor-ab-{label}.json"
    path.write_text(
        json.dumps({"label": label, "prompt_version": prompt_version(), "rows": rows}, indent=1)
    )
    print(f"Saved: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--only", default="", help="situation ids, by comma")
    parser.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"))
    args = parser.parse_args()
    if args.compare:
        old, new = (
            json.loads((OUT / f"tutor-ab-{label}.json").read_text()) for label in args.compare
        )
        print(f"old {old['prompt_version']}  new {new['prompt_version']}")
        print(report(old["rows"], new["rows"]))
        return
    if not args.label:
        sys.exit("--label is needed to run")
    asyncio.run(_run(args.label, args.repeat, {i for i in args.only.split(",") if i}))


if __name__ == "__main__":
    main()
