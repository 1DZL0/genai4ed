"""Queries and wall time per teacher endpoint at two scales, against the test database.
Not part of the suite (no test_ prefix); run it by name, from backend/:

    uv run pytest -q -s tests/perf_probe.py

"today" is about the professor's teacher as the live data stands; "term" is one teacher after
a term of use. Numbers go to bench/out/perf_<scale>.json, for a before/after diff; see PERF.md.
"""

import json
import pathlib
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app.agent.llm import ScriptedClient
from app.demo import MATHS
from app.enums import (
    ContractStatus,
    ExceptionKind,
    ExceptionStatus,
    LearningStatus,
    Role,
    ScoreStatus,
    SessionStatus,
)
from app.models import (
    AgentTurn,
    Class,
    Enrolment,
    Exception_,
    LearningState,
    LessonContract,
    LessonOutcome,
    Session,
    SessionParticipant,
    User,
)
from tests.test_agent_student import lesson, say, turn  # noqa: F401, F811 - fixture

OUT = pathlib.Path(__file__).resolve().parents[1] / "bench" / "out"
SCALES = {
    "today": dict(classes=3, students=25, lessons=5, runs=2),
    "term": dict(classes=3, students=25, lessons=30, runs=5),
}
REPEATS = 3


async def seed(db, *, classes, students, lessons, runs):
    now = datetime.now(UTC)
    teacher = User(pseudonym="perf-t", role=Role.TEACHER.value)
    db.add(teacher)
    await db.flush()
    rooms = [Class(teacher_id=teacher.id, label=f"{7 + i}P") for i in range(classes)]
    db.add_all(rooms)
    await db.flush()
    pupils: dict[uuid.UUID, list[User]] = {}
    for room in rooms:
        pupils[room.id] = [
            User(pseudonym=f"{room.label}-{n:02d}", role=Role.STUDENT.value)
            for n in range(1, students + 1)
        ]
        db.add_all(pupils[room.id])
    await db.flush()
    for room in rooms:
        db.add_all([Enrolment(class_id=room.id, student_id=p.id) for p in pupils[room.id]])
    contracts = []
    sessions = []
    for n in range(lessons):
        contract = LessonContract(
            plan_id=uuid.uuid4(),
            teacher_id=teacher.id,
            title=f"Lesson {n + 1}: {MATHS.title}",
            subject=MATHS.subject,
            status=ContractStatus.ACTIVE.value,
            version=1,
            brief=MATHS.model_dump(mode="json"),
            activated_at=now,
            activated_by=teacher.id,
        )
        db.add(contract)
        await db.flush()
        contracts.append(contract)
        for r in range(runs):
            room = rooms[(n + r) % classes]
            opened = now - timedelta(days=lessons * runs - (n * runs + r))
            session = Session(
                contract_id=contract.id,
                class_id=room.id,
                status=SessionStatus.CLOSED.value,
                opened_at=opened,
                closes_at=opened + timedelta(minutes=50),
                closed_at=opened + timedelta(minutes=50),
            )
            db.add(session)
            await db.flush()
            sessions.append(session)
            kids = pupils[room.id]
            db.add_all([SessionParticipant(session_id=session.id, student_id=p.id) for p in kids])
            db.add_all(
                [
                    LearningState(
                        session_id=session.id,
                        student_id=p.id,
                        status=(
                            LearningStatus.COMPLETED.value
                            if i % 2
                            else LearningStatus.IN_PROGRESS.value
                        ),
                        step_index=1,
                        steps=[{"task": "x"}],
                    )
                    for i, p in enumerate(kids)
                ]
            )
            db.add_all(
                [
                    AgentTurn(
                        session_id=session.id,
                        student_id=p.id,
                        mode="student",
                        policy_version="class-agent-v1",
                        prompt_version="student-v10-perf",
                        provider="scripted",
                        model="scripted",
                        latency_ms=1,
                        validation_outcome="ok",
                        leakage_check="passed",
                        request={"text": "hi"},
                        response={},
                    )
                    for i, p in enumerate(kids)
                    if i % 3 == 0
                ]
            )
            db.add(
                Exception_(
                    session_id=session.id,
                    student_id=kids[0].id,
                    kind=ExceptionKind.STRUGGLING.value,
                    priority=2,
                    status=ExceptionStatus.OPEN.value,
                    summary="stuck on step 2",
                )
            )
            db.add(
                LessonOutcome(
                    session_id=session.id,
                    student_id=kids[1].id,
                    status=ScoreStatus.SUGGESTED.value,
                    suggested={},
                    suggested_total=0,
                    provider="scripted",
                    model="scripted",
                    prompt_version="review-v3",
                )
            )
    await db.commit()
    return teacher, rooms, contracts, sessions


class Counter:
    def __init__(self, engine):
        self.n = 0
        self.engine = engine

    def __enter__(self):
        event.listen(self.engine.sync_engine, "before_cursor_execute", self._tick)
        return self

    def __exit__(self, *a):
        event.remove(self.engine.sync_engine, "before_cursor_execute", self._tick)

    def _tick(self, *a, **k):
        self.n += 1


async def measure(client, engine, headers, method, path, body=None):
    await client.request(method, path, headers=headers, json=body)  # warm
    times, queries = [], []
    for _ in range(REPEATS):
        with Counter(engine) as c:
            t0 = time.perf_counter()
            r = await client.request(method, path, headers=headers, json=body)
            times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code < 300, (path, r.status_code, r.text[:300])
        queries.append(c.n)
    return {"queries": max(queries), "median_ms": round(statistics.median(times), 1)}


@pytest.mark.parametrize("scale", list(SCALES))
async def test_teacher_endpoints(db, client, engine, scale):
    teacher, rooms, contracts, sessions = await seed(db, **SCALES[scale])
    headers = {"X-GenAI4ED-Pseudonym": teacher.pseudonym}
    cid = rooms[0].id
    ended = sessions[-1]
    probes = [
        ("GET", "/api/teacher/thread/lessons", None),
        ("GET", "/api/teacher/thread", None),
        ("GET", "/api/teacher/classes", None),
        ("GET", f"/api/teacher/classes/{cid}/progress", None),
        ("GET", f"/api/teacher/classes/{cid}/students", None),
        (
            "POST",
            "/api/teacher/thread/actions",
            {"action": "show_lesson", "lesson_id": str(contracts[-1].id)},
        ),
        (
            "POST",
            "/api/teacher/thread/actions",
            {"action": "show_class", "session_id": str(ended.id)},
        ),
        (
            "POST",
            "/api/teacher/thread/actions",
            {"action": "show_outcomes", "session_id": str(ended.id)},
        ),
    ]
    results = {}
    print(f"\n[{scale}] {SCALES[scale]}")
    print(f"{'endpoint':52} {'queries':>8} {'median ms':>10}")
    for method, path, body in probes:
        key = f"{method} {path.split('/classes/')[0] if '/classes/' in path else path}"
        if body:
            key += " " + body["action"]
        r = await measure(client, engine, headers, method, path, body)
        results[key] = r
        print(f"{key:52} {r['queries']:8d} {r['median_ms']:10.1f}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"perf_{scale}.json").write_text(json.dumps(results, indent=1))


async def test_student_turn(db, engine, lesson):  # noqa: F811 - the fixture
    """Queries per tutor turn, model call excluded (scripted)."""
    client = ScriptedClient(
        [
            turn("Hi! Solve 3x + 4 = 19.", task="Solve 3x + 4 = 19"),
            turn("Nearly: what do you take from both sides first?", task="Solve 3x + 4 = 19"),
            turn("You added 4 instead of taking it away.", task="Solve 3x + 4 = 19"),
        ]
    )
    counts, times = [], []
    for text in (None, "x = 4", "why?"):
        with Counter(engine) as c:
            t0 = time.perf_counter()
            await say(db, lesson, client, text)
            times.append((time.perf_counter() - t0) * 1000)
        counts.append(c.n)
    print(f"\n[student turn] queries per turn {counts}, ms per turn {[round(t) for t in times]}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "perf_student.json").write_text(
        json.dumps({"queries": counts, "ms": [round(t) for t in times]})
    )
