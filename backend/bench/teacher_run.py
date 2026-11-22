"""What runs the teacher test set: the database, the app, the model and the judging.

Not run by itself: bench.teacher_set sets the environment first and then imports this, because
the app reads its settings once, when it is first imported.

Each case gets its own teacher, class and five pupils. The state it needs is put there the way
the screens would put it (the buttons through the API, the pupils through their own endpoints
with a scripted tutor), and then the one message under test goes to the real model through the
real endpoint. What is judged is what the teacher would have got: the stored reply, the stored
lesson, the class's state, and what the server had to strike.

Every teacher gets the one wording. Each row keeps the prompt version its turn was sent with,
so a saved run says which wording it judged.
"""

import asyncio
import contextvars
import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.agent import llm, store, thread
from app.agent.brief import LessonBrief
from app.agent.lessons import current_version
from app.agent.scripted import demo_responder
from app.config import get_settings
from app.db import Base, get_engine, get_sessionmaker
from app.enums import ContractStatus, MessageRole, Role
from app.main import create_app
from app.models import AgentTurn, Class, Enrolment, LessonContract, Message, Session, User
from bench.teacher_cases import EVERY, OPENING, STATES, Case, Got, State

OUT = Path(__file__).parent / "out"
TEACHER_API = "/api/teacher/thread"
PUPILS = 5


class SetupFailed(Exception):
    """The state for a case could not be put in place: the harness's fault, not the model's."""


class NoAnswer(Exception):
    """The model service gave no usable answer to the message under test."""


# ---------- the database ----------


async def prepare_database() -> str:
    """An empty database for this run, never the live one or the tests'. Returns its name."""
    url = make_url(get_settings().database_url)
    name = url.database or ""
    if "eval" not in name or not name.isidentifier():
        raise SystemExit(f"Refusing to run on the database {name!r}: its name must contain 'eval'.")
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        found = await conn.scalar(
            text("select 1 from pg_database where datname = :name"), {"name": name}
        )
        if not found:
            await conn.execute(text(f'create database "{name}"'))
    await admin.dispose()
    async with get_engine().begin() as conn:
        existing = (
            await conn.execute(text("select tablename from pg_tables where schemaname = 'public'"))
        ).scalars()
        for table in existing:
            await conn.execute(text(f'drop table if exists "{table}" cascade'))
        await conn.run_sync(Base.metadata.create_all)
    return name


# ---------- the model ----------


@dataclass
class Calls:
    """One case's model calls. `live` is on only while the message under test is answered."""

    live: bool = False
    # What the scripted tutor says next to a pupil; None lets the demo tutor answer.
    tutor: dict | None = None
    made: list[dict] = field(default_factory=list)


_calls: contextvars.ContextVar[Calls | None] = contextvars.ContextVar("calls", default=None)


def turn_block(system: str) -> str:
    """What the server added for this turn, after the fixed prompt; the whole of it when the
    prompt was changed for the run."""
    if system.startswith(thread.SYSTEM):
        return system[len(thread.SYSTEM) :]
    return system


class Routed:
    """The teacher's agent is the real model, and only for the message under test. Every other
    call (a pupil's tutor while the class is being set up) is scripted, so a run costs one
    model reply per case and the class data is the same every time."""

    name = "routed"

    def __init__(self, real: llm.LLMClient) -> None:
        self._real = real
        self.model = real.model

    async def complete(
        self,
        *,
        purpose: str,
        system: str,
        messages: list[dict],
        schema: dict,
        max_tokens: int,
        cache_prefix: str = "",
    ) -> llm.LLMResult:
        calls = _calls.get()
        if purpose == "teacher_thread" and calls is not None and calls.live:
            return await self._ask(
                calls, purpose, system, messages, schema, max_tokens, cache_prefix
            )
        if purpose == "student_turn" and calls is not None and calls.tutor is not None:
            data = calls.tutor
        else:
            data = demo_responder(purpose, system, messages)
        return llm.LLMResult(
            data=data, raw=json.dumps(data), provider="scripted", model="scripted", latency_ms=0
        )

    async def _ask(self, calls, purpose, system, messages, schema, max_tokens, cache_prefix):
        # What the server added for this turn: kept to read a failure by.
        made = {"turn_block": turn_block(system)}
        calls.made.append(made)
        try:
            result = await self._real.complete(
                purpose=purpose,
                system=system,
                messages=messages,
                schema=schema,
                max_tokens=max_tokens,
                cache_prefix=cache_prefix,
            )
        except llm.LLMError as exc:
            made["error"] = str(exc)
            made["raw"] = getattr(exc, "raw", "")
            raise
        made.update(data=result.data, usage=result.usage, latency_ms=result.latency_ms)
        return result

    async def say(
        self, *, purpose: str, system: str, messages: list[dict], max_tokens: int
    ) -> llm.LLMResult:
        reply = demo_responder(purpose, system, messages)
        words = str(reply.get("message") or reply.get("reply") or "")
        return llm.LLMResult(
            data={}, raw=words, provider="scripted", model="scripted", latency_ms=0
        )


def real_client() -> llm.OpenRouterClient:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set (the repo's .env has it).")
    return llm.OpenRouterClient(
        api_key=settings.openrouter_api_key, model=settings.openrouter_model, timeout=180
    )


# ---------- putting a case's state in place ----------


@dataclass
class Room:
    """One case's own teacher, class and pupils, and what was put there for it."""

    teacher: User
    klass: Class
    pupils: list[User]
    lessons: list[LessonContract] = field(default_factory=list)
    session_id: str = ""

    @property
    def names(self) -> dict[str, str]:
        named = {f"p{n}": p.pseudonym for n, p in enumerate(self.pupils, 1)}
        return {**named, "klass": self.klass.label}

    def fill(self, words: str) -> str:
        for key, value in self.names.items():
            words = words.replace("{" + key + "}", value)
        return words

    def as_teacher(self) -> dict[str, str]:
        return {"X-GenAI4ED-Pseudonym": self.teacher.pseudonym}


def _label(n: int) -> str:
    """7A, 7B ... 7Z, 8A: a class label nobody else in this run has."""
    return f"{7 + n // 26}{chr(ord('A') + n % 26)}"


async def _room(n: int) -> Room:
    async with get_sessionmaker()() as db:
        teacher = User(pseudonym=f"teacher-{n:03d}", role=Role.TEACHER.value)
        db.add(teacher)
        await db.flush()
        klass = Class(teacher_id=teacher.id, label=_label(n))
        db.add(klass)
        pupils = [
            User(pseudonym=f"{klass.label}-{k:02d}", role=Role.STUDENT.value)
            for k in range(1, PUPILS + 1)
        ]
        db.add_all(pupils)
        await db.flush()
        db.add_all([Enrolment(class_id=klass.id, student_id=p.id) for p in pupils])
        await db.commit()
    return Room(teacher, klass, pupils)


async def _press(http: AsyncClient, room: Room, **body) -> None:
    """A button on a card, as the teacher."""
    response = await http.post(f"{TEACHER_API}/actions", json=body, headers=room.as_teacher())
    if response.status_code != 200:
        raise SetupFailed(f"{body.get('action')}: {response.status_code} {response.text[:200]}")


async def _as_pupil(http: AsyncClient, pupil: User, path: str, body: dict | None = None) -> None:
    response = await http.post(
        f"/api/learn/{path}", json=body, headers={"X-GenAI4ED-Pseudonym": pupil.pseudonym}
    )
    if response.status_code != 200:
        raise SetupFailed(f"{pupil.pseudonym} {path}: {response.status_code} {response.text[:200]}")


async def _set_up(http: AsyncClient, room: Room, state: State, calls: Calls) -> None:
    async with get_sessionmaker()() as db:
        for lesson in state.lessons:
            brief = LessonBrief.model_validate(lesson.brief)
            contract = LessonContract(
                teacher_id=room.teacher.id,
                title=brief.title,
                subject=brief.subject,
                status=ContractStatus.DRAFT.value,
                version=1,
                brief=brief.model_dump(mode="json"),
            )
            db.add(contract)
            await db.flush()
            room.lessons.append(contract)
        await db.commit()

    for said in state.thread:
        data = dict(said.data)
        if said.lesson is not None:
            data["card"] = {"type": "lesson", "lesson_id": str(room.lessons[said.lesson].id)}
        async with get_sessionmaker()() as db:
            conversation = await store.teacher_thread(db, teacher_id=room.teacher.id)
            await store.add_message(
                db,
                conversation,
                role=MessageRole.TEACHER if said.who == "teacher" else MessageRole.AGENT,
                text=room.fill(said.text),
                data=data or None,
            )
            await db.commit()
        if said.lesson is not None and state.lessons[said.lesson].approved:
            await _press(http, room, action="approve", lesson_id=str(room.lessons[said.lesson].id))

    if not state.pupils:
        return
    await _press(
        http, room, action="run", lesson_id=str(room.lessons[-1].id), class_id=str(room.klass.id)
    )
    async with get_sessionmaker()() as db:
        room.session_id = str(
            await db.scalar(select(Session.id).where(Session.class_id == room.klass.id))
        )
    for pupil, script in zip(room.pupils, state.pupils, strict=True):
        if script.turns:
            calls.tutor = OPENING
            await _as_pupil(http, pupil, f"{room.session_id}/start")
        for words, answer in script.turns:
            calls.tutor = answer
            await _as_pupil(http, pupil, f"{room.session_id}/messages", {"text": words})
        if script.asks_teacher:
            await _as_pupil(http, pupil, f"{room.session_id}/request-teacher")
    calls.tutor = None
    if state.ended:
        await _press(http, room, action="end", session_id=room.session_id)


# ---------- one case ----------


def _snap(contract: LessonContract | None) -> dict | None:
    if contract is None:
        return None
    return {
        "id": str(contract.id),
        "title": contract.title,
        "status": contract.status,
        "version": contract.version,
        "brief": contract.brief or {},
    }


async def _plans(db, teacher: User) -> set:
    return set(
        (
            await db.scalars(
                select(LessonContract.plan_id).where(LessonContract.teacher_id == teacher.id)
            )
        ).all()
    )


async def _once(http: AsyncClient, case: Case, n: int) -> dict:
    """Set the case up, send its message to the real model, and collect what came of it."""
    calls = Calls()
    _calls.set(calls)
    room = await _room(n)
    state = STATES[case.state]
    await _set_up(http, room, state, calls)
    focus = room.lessons[-1].plan_id if room.lessons else None
    async with get_sessionmaker()() as db:
        had = await _plans(db, room.teacher)
        before = _snap(await current_version(db, focus)) if focus else None

    sent = room.fill(case.text)
    calls.live = True
    if case.press:
        # A button that takes words: the message under test is the one the button sends.
        response = await http.post(
            f"{TEACHER_API}/actions",
            json={"action": case.press, "text": sent},
            headers=room.as_teacher(),
        )
    else:
        response = await http.post(
            f"{TEACHER_API}/messages",
            json={"text": sent},
            headers=room.as_teacher(),
        )
    calls.live = False
    answered = [c for c in calls.made if "data" in c]
    if response.status_code != 200 or not answered:
        errors = "; ".join(c.get("error", "") for c in calls.made if "error" in c)
        raise NoAnswer(f"{response.status_code} {errors or response.text[:200]}")

    async with get_sessionmaker()() as db:
        conversation = await store.teacher_thread(db, teacher_id=room.teacher.id)
        turn = await db.scalar(
            select(AgentTurn)
            .where(AgentTurn.conversation_id == conversation.id)
            .order_by(AgentTurn.created_at.desc())
            .limit(1)
        )
        message = await db.scalar(select(Message).where(Message.turn_id == turn.id))
        made = [
            _snap(await current_version(db, plan)) for plan in await _plans(db, room.teacher) - had
        ]
        after = _snap(await current_version(db, focus)) if focus else None
        session = await db.scalar(
            select(Session.status)
            .where(Session.class_id == room.klass.id)
            .order_by(Session.created_at.desc())
            .limit(1)
        )
    return {
        "out": answered[-1]["data"],
        "first": answered[0]["data"] if len(calls.made) > 1 else None,
        "tries": len(calls.made),
        "reply": message.text,
        "data": message.data or {},
        "conflicts": [str(c) for c in turn.conflicts or []],
        "before": before,
        "after": after,
        "made": made,
        "session": session or "",
        "names": room.names,
        "sent": sent,
        "prompt_version": turn.prompt_version,
        "turn_block": answered[-1]["turn_block"],
        "latency_ms": sum(c.get("latency_ms", 0) for c in calls.made),
        "cost": sum(float((c.get("usage") or {}).get("cost") or 0) for c in calls.made),
        "tokens": sum(int((c.get("usage") or {}).get("total_tokens") or 0) for c in calls.made),
    }


def judge(case: Case, seen: dict) -> list[dict]:
    """The checks this reply failed, each with the rule it is about. Costs nothing: a saved
    run's rows can be judged again, by the checks as they are now."""
    got = Got(
        out=seen["out"],
        tries=seen["tries"],
        reply=seen["reply"],
        data=seen["data"],
        conflicts=seen["conflicts"],
        before=seen["before"],
        after=seen["after"],
        made=seen["made"],
        session=seen["session"],
        names=seen["names"],
    )
    failed = []
    for item in (*case.checks, *EVERY):
        try:
            why = item.test(got)
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            why = f"the check could not read the reply: {exc!r}"
        if why:
            failed.append({"rule": item.rule, "what": item.what, "why": why})
    return failed


class Numbers:
    """Hands each case run its own number, for a teacher and a class nobody else has."""

    def __init__(self) -> None:
        self._next = 0

    def take(self) -> int:
        self._next += 1
        return self._next


async def _case(
    http: AsyncClient,
    case: Case,
    numbers: Numbers,
    gate: asyncio.Semaphore,
) -> dict:
    row = {"id": case.id, "group": case.group, "state": case.state, "press": case.press}
    async with gate:
        problem = ""
        # The model service drops a call now and then: once more, from a clean start.
        for _ in range(2):
            try:
                seen = await _once(http, case, numbers.take())
            except NoAnswer as exc:
                problem = f"no answer: {exc}"
                continue
            except SetupFailed as exc:
                problem = f"setup failed: {exc}"
                break
            failed = judge(case, seen)
            return {**row, **seen, "status": "fail" if failed else "pass", "failed": failed}
    return {**row, "status": "error", "problem": problem, "failed": [], "sent": case.text}


async def run(cases: list[Case], *, repeat: int, together: int) -> list[dict]:
    app = create_app()
    app.dependency_overrides[llm.get_llm_client] = lambda: Routed(real_client())
    gate = asyncio.Semaphore(together)
    numbers = Numbers()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        jobs = [
            # Each in its own task, so each has its own record of the calls it made.
            asyncio.create_task(_case(http, case, numbers, gate))
            for case in cases
            for _ in range(repeat)
        ]
        rows = []
        for job in asyncio.as_completed(jobs):
            row = await job
            rows.append(row)
            print(f"  {row['status']:5}  {row['id']}", flush=True)
    order = {case.id: n for n, case in enumerate(cases)}
    return sorted(rows, key=lambda r: order[r["id"]])


# ---------- the report ----------


def _lesson_line(lesson: dict | None) -> str:
    if not lesson:
        return ""
    brief = lesson["brief"]
    steps = "; ".join(str(s.get("name")) for s in brief.get("steps") or [])
    rules = brief.get("rules") or {}
    return (
        f"{lesson['title']!r} ({lesson['status']} v{lesson['version']}): "
        f"{brief.get('heading')}/{brief.get('listed_kind') or brief.get('activity_kind')}, "
        f"{brief.get('activity')}, age {brief.get('age')}, {brief.get('duration_minutes')} min; "
        f"steps: {steps}; worked step after {rules.get('partial_after_attempts')}, answer after "
        f"{rules.get('full_answer_after_attempts')}, hints {rules.get('hints_allowed')}; "
        f"rules_text {brief.get('rules_text')!r}"
    )


def _card_lines(lesson: dict | None) -> list[str]:
    """What the lesson card says of the objectives, for a lesson where a step names one: the
    objectives by number, then each step with the one it serves and its own questions."""
    brief = (lesson or {}).get("brief") or {}
    steps = brief.get("steps") or []
    if not any(step.get("objective") for step in steps):
        return []
    lines = [f"--   objective {n}: {o}" for n, o in enumerate(brief.get("objectives") or [], 1)]
    for n, step in enumerate(steps, 1):
        serves = f"objective {step['objective']}" if step.get("objective") else "none"
        asks = " / ".join(step.get("prompt_ideas") or [])
        lines.append(f"--   step {n} {step.get('name')!r} serves {serves}: {asks}")
    return lines


def as_text(rows: list[dict]) -> str:
    """Every message and what came back, to read."""
    parts = []
    for row in rows:
        head = f"=== {row['id']}  [{row['group']}, {row['state']}]  {row['status'].upper()}"
        if row["status"] == "error":
            parts.append(f"{head}\n> {row['sent']}\n{row['problem']}\n")
            continue
        out = row["out"]
        # The button pressed in place of a message, if any.
        lines = [
            f"{head}  {row['tries']} tr{'y' if row['tries'] == 1 else 'ies'}, "
            f"{row['latency_ms'] / 1000:.1f} s",
            f"> {row['sent']}" + (f"   [pressed: {row['press']}]" if row.get("press") else ""),
        ]
        if row.get("prompt_version"):
            lines.append(f"-- prompt {row['prompt_version']}")
        lines += [
            row["reply"],
            "-- "
            + ", ".join(
                f"{k}={out.get(k)!r}"
                for k in ("gave", "show", "do", "new_lesson", "guess_answer", "guess_said", "guide")
                if out.get(k)
            ),
        ]
        for lesson in row["made"]:
            lines += ["-- new: " + _lesson_line(lesson), *_card_lines(lesson)]
        if not row["made"] and row["after"] and row["after"] != row["before"]:
            lines += ["-- now: " + _lesson_line(row["after"]), *_card_lines(row["after"])]
        if row["conflicts"]:
            lines.append("-- struck: " + ", ".join(row["conflicts"]))
        lines.extend(f"FAIL {f['rule']}: {f['what']}: {f['why']}" for f in row["failed"])
        parts.append("\n".join(lines) + "\n")
    return "\n".join(parts)


def _by_case(rows: list[dict]) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {}
    for row in rows:
        found.setdefault(row["id"], []).append(row)
    return found


def summary(rows: list[dict], earlier: list[dict] | None = None) -> str:
    """The numbers: passes by group, failures by rule, and what it took."""
    cases = _by_case(rows)
    passed = {k: all(r["status"] == "pass" for r in runs) for k, runs in cases.items()}
    lines = [f"{sum(passed.values())} of {len(cases)} cases passed every check."]
    groups: dict[str, list[bool]] = {}
    for key, runs in cases.items():
        groups.setdefault(runs[0]["group"], []).append(passed[key])
    lines.append("  " + ", ".join(f"{g} {sum(v)}/{len(v)}" for g, v in groups.items()))

    by_rule: dict[str, set[str]] = {}
    for row in rows:
        for failure in row["failed"]:
            by_rule.setdefault(failure["rule"], set()).add(row["id"])
    if by_rule:
        lines.append("Failures by rule:")
        for rule, ids in sorted(by_rule.items(), key=lambda item: -len(item[1])):
            lines.append(f"  {rule} ({len(ids)}): {', '.join(sorted(ids))}")
    errors = sorted({r["id"] for r in rows if r["status"] == "error"})
    if errors:
        lines.append("No answer or no setup (not counted as the prompt's): " + ", ".join(errors))
    partly = {
        k: f"{sum(r['status'] == 'pass' for r in runs)}/{len(runs)}"
        for k, runs in cases.items()
        if len(runs) > 1 and len({r["status"] for r in runs}) > 1
    }
    if partly:
        lines.append("Not the same every time: " + ", ".join(f"{k} {v}" for k, v in partly.items()))

    answered = [r for r in rows if r["status"] != "error"]
    if answered:
        first = sum(r["tries"] == 1 for r in answered)
        cost = sum(r["cost"] for r in answered)
        lines.append(
            f"Valid on the first try: {first} of {len(answered)}. "
            f"Median time: {statistics.median(r['latency_ms'] for r in answered) / 1000:.1f} s. "
            f"Measured spend: ${cost:.2f} ({sum(r['tokens'] for r in answered):,} tokens)."
        )
    if earlier is not None:
        was = {k: all(r["status"] == "pass" for r in runs) for k, runs in _by_case(earlier).items()}
        fixed = sorted(k for k in passed if passed[k] and was.get(k) is False)
        broke = sorted(k for k in passed if not passed[k] and was.get(k) is True)
        lines.append("Now passing: " + (", ".join(fixed) or "none"))
        lines.append("Now failing: " + (", ".join(broke) or "none"))
    return "\n".join(lines)


def save(label: str, rows: list[dict], *, prompt: str) -> Path:
    OUT.mkdir(exist_ok=True)
    record = {
        "label": label,
        "prompt": prompt,
        "model": get_settings().openrouter_model,
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "cases": rows,
    }
    path = OUT / f"{label}.json"
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / f"{label}.txt").write_text(as_text(rows), encoding="utf-8")
    return path


def load(label: str) -> list[dict]:
    return json.loads((OUT / f"{label}.json").read_text(encoding="utf-8"))["cases"]
