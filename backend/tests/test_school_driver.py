"""The lesson driver: pupils playing one lesson at once over HTTP, each in a browser of their
own (one cookie jar each), with a teacher script beside them, and every request logged with the
move it was meant to be.

The app runs in this process. Here each request gets a database session of its own from the
app's pool, as on a server, so the pupils' requests really run side by side: the other tests
share one session, which takes one request at a time. The tutor and the writer are scripted,
and nothing is slept: the driver's sleep is swapped for a clock that notes each wait and, where
a test needs things in an order, holds a wait until something has happened or does something
when a given wait comes.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app import db as app_db
from app.agent import llm
from app.agent.brief import LessonBrief
from app.config import get_settings
from app.db import get_session
from app.enums import Role
from app.models import Enrolment, SessionParticipant, User
from bench.pupils import BEATS, CANNED, DRIVER_KINDS, Beat, Persona, beat
from bench.school import driver
from bench.school.cast import Pupil
from bench.school.driver import LessonLog, Sent, run_lesson
from bench.school.teacher import Seat

# ---------- the room: sessions, the clock, the browsers ----------


@pytest.fixture(autouse=True)
async def side_by_side(app):
    """Each request on a database session of its own, from the app's own pool, as on a server."""
    app.dependency_overrides.pop(get_session)
    yield
    await app_db.get_engine().dispose()


async def happens(condition: Callable[[], bool], within: float = 10) -> None:
    """Waits in short real steps until `condition()` holds; fails the test after `within`
    seconds rather than hang."""
    deadline = time.monotonic() + within
    while not condition():
        assert time.monotonic() < deadline, "the lesson never got there"
        await asyncio.sleep(0.005)


class Clock:
    """The driver's waits: each one noted, and none slept. `hold` keeps every wait of one length
    waiting until a condition holds; `at` does something when a given wait comes (counting from
    1), before the pupil carries on."""

    def __init__(self) -> None:
        self.waits: list[float] = []
        self._holds: dict[float, Callable[[], bool]] = {}
        self._at: dict[int, Callable[[], Awaitable[Any]]] = {}

    def hold(self, seconds: float, until: Callable[[], bool]) -> None:
        self._holds[seconds] = until

    def at(self, wait: int, do: Callable[[], Awaitable[Any]]) -> None:
        self._at[wait] = do

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        if (do := self._at.get(len(self.waits))) is not None:
            await do()
        if (until := self._holds.get(seconds)) is not None:
            await happens(until)
        await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def clock(monkeypatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(driver, "sleep", clock.sleep)
    return clock


@dataclass
class Asked:
    """One request a browser sent: which browser, and whether it carried a cookie."""

    browser: int
    method: str
    path: str
    body: Any
    cookie: bool


class Browsers:
    """Makes each pupil's browser: a client of its own on the app in this process, with its own
    cookie jar. Every request is noted with the browser it came from, in the order sent, and so
    is the most that were on their way at once. `instead` may answer a request in the app's
    place, with a status and a stock detail, or raise as when no answer comes; None lets the
    request through."""

    def __init__(self, app, instead: Callable[[Asked], int | None] = lambda asked: None) -> None:
        self.app = app
        self.instead = instead
        self.made = 0
        self.asked: list[Asked] = []
        self.on_the_way = 0
        self.most_at_once = 0

    def __call__(self) -> httpx.AsyncClient:
        self.made += 1
        return httpx.AsyncClient(transport=Noted(self, self.made), base_url="http://test")


class Noted(httpx.ASGITransport):
    """One browser's way to the app: notes each request, and lets `instead` answer it first."""

    def __init__(self, browsers: Browsers, number: int) -> None:
        super().__init__(app=browsers.app)
        self.browsers = browsers
        self.number = number

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        room = self.browsers
        body = json.loads(request.content) if request.content else None
        asked = Asked(
            self.number, request.method, request.url.path, body, "cookie" in request.headers
        )
        room.asked.append(asked)
        if (status := room.instead(asked)) is not None:
            return httpx.Response(status, json={"detail": f"Stand-in {status}."}, request=request)
        room.on_the_way += 1
        room.most_at_once = max(room.most_at_once, room.on_the_way)
        try:
            return await super().handle_async_request(request)
        finally:
            room.on_the_way -= 1


def browser(app) -> httpx.AsyncClient:
    """A browser of the test's own, for the teacher or for reading a pupil's page."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ---------- the pupils, their words and the tutor ----------

# What the scripted writer has a pupil say, by move.
SAYS = {
    "right": "x = 5",
    "right_why": "x = 5 cos 15 / 3 is 5",
    "wrong": "x = 7",
    "bare_wrong": "8",
    "how": "i took 4 off both sides",
    "not_sure": "not sure",
    "what_mean": "what do u mean",
    "closer": "is it 4 or something",
}


class Writer:
    """The pupils' words: each move's line from SAYS with the pupil's name after it, so a line
    shows whose it is. It keeps what it was asked, and gives the moves in `fallback` as
    fallbacks. A pupil named in `breaks_for` makes it fail."""

    def __init__(self, fallback: tuple[str, ...] = (), breaks_for: str | None = None) -> None:
        self.asked: list[tuple[str, str, list[dict]]] = []
        self.fallback = fallback
        self.breaks_for = breaks_for
        # Why the last fallback fell back, as the real writer keeps it: the move and the pupil.
        self.last_failure: str | None = None

    async def write(self, persona: Persona, move: Beat, lines: list[dict]) -> tuple[str, bool]:
        if persona.name == self.breaks_for:
            raise RuntimeError("the writer broke")
        self.asked.append((persona.name, move.kind, lines))
        fell_back = move.kind in self.fallback
        if fell_back:
            self.last_failure = f"http 429 on {move.kind} for {persona.name}"
        return f"{SAYS[move.kind]} ({persona.name})", fell_back


ASKS = "What do you get? Show me how."


def asking(purpose: str, system: str, messages: list[dict]) -> dict:
    """The tutor asks again whatever the pupil writes, so nobody moves on."""
    return {"message": ASKS, "move": "ask", "task": "Solve it"}


def moving_on(purpose: str, system: str, messages: list[dict]) -> dict:
    """The tutor moves the pupil on when they write x = 5, and asks again otherwise."""
    said = messages[-1]["content"] if messages[-1]["role"] == "user" else ""
    if "x = 5" not in said:
        return asking(purpose, system, messages)
    return {
        "message": "Yes, that's it. Next one.",
        "move": "advance",
        "student_attempted": True,
        "step_done": True,
        "task": "Next question",
        "assessment": {"judgment": "met", "evidence_quote": said},
    }


def failing(*calls: int):
    """The tutor asks again every time, but the model gives no answer on these calls (counting
    from 1), as when the model times out."""
    count = 0

    def reply(purpose: str, system: str, messages: list[dict]) -> dict:
        nonlocal count
        count += 1
        if count in calls:
            raise llm.LLMError("The model gave no answer.")
        return asking(purpose, system, messages)

    return reply


def pupil(name: str, moves: str, kind: str = "average", **more) -> Pupil:
    """A pupil of the cast called `name`, whose plan is `moves`, separated by spaces."""
    persona = Persona(name, f"14, {name}, writes short lines", [beat(m) for m in moves.split()])
    return Pupil(kind, persona, **more)


async def seats(app, three, **names: str) -> dict[str, Seat]:
    """The pupils' seats, from the join codes their teacher issues for the class, under the name
    the cast calls each one: name=pseudonym."""
    async with browser(app) as teacher:
        issued = await teacher.post(
            f"/api/teacher/classes/{three.klass.id}/join-codes",
            headers=three.headers(three.teacher),
        )
    assert issued.status_code == 200, issued.text
    by_pseudonym = {
        c["pseudonym"]: Seat(c["student_id"], c["pseudonym"], c["code"]) for c in issued.json()
    }
    return {name: by_pseudonym[pseudonym] for name, pseudonym in names.items()}


async def no_call(line_id: str) -> str | None:
    return None


async def play(
    app,
    three,
    pupils: list[Pupil],
    seated: dict[str, Seat],
    *,
    browsers: Browsers | None = None,
    writer: Writer | None = None,
    read_call=no_call,
    think: tuple[float, float] = (0, 0),
    teacher_script=None,
    max_turns: int = 4,
    key: str = "maths-1",
    log: LessonLog | None = None,
) -> LessonLog:
    return await run_lesson(
        key=key,
        base_url="http://test",
        session_id=str(three.session.id),
        seats=seated,
        pupils=pupils,
        writer=writer or Writer(),
        read_call=read_call,
        think=think,
        teacher_script=teacher_script,
        max_turns=max_turns,
        client_factory=browsers or Browsers(app),
        **({"log": log} if log is not None else {}),
    )


async def more_pupils(db, three, count: int) -> None:
    """`count` more pupils in the class and its lesson, after its two: 10B-03, 10B-04 and on."""
    added = [User(pseudonym=f"10B-{n:02d}", role=Role.STUDENT.value) for n in range(3, 3 + count)]
    db.add_all(added)
    await db.flush()
    db.add_all([Enrolment(class_id=three.klass.id, student_id=p.id) for p in added])
    db.add_all([SessionParticipant(session_id=three.session.id, student_id=p.id) for p in added])
    await db.commit()


def of(log: LessonLog, seat: Seat) -> list[Sent]:
    """What this pupil sent, in order."""
    return [s for s in log.sent if s.pupil == seat.pseudonym]


async def page_of(app, three, seat: Seat) -> dict:
    """The pupil's lesson as their page shows it now, read in a browser of the test's own."""
    async with browser(app) as theirs:
        assert (await theirs.post("/api/auth/join", json={"code": seat.code})).status_code == 200
        return (await theirs.get(f"/api/learn/{three.session.id}")).json()


async def set_state(app, three, to: str) -> httpx.Response:
    """The teacher pauses (to="paused"), resumes ("open") or ends ("closed") the lesson."""
    async with browser(app) as teacher:
        return await teacher.post(
            f"/api/teacher/sessions/{three.session.id}/state",
            params={"to": to},
            headers=three.headers(three.teacher),
        )


def keep(logs: list[LessonLog]):
    """A teacher script that only holds on to the log, so that a test can watch the lesson."""

    async def script(log: LessonLog) -> None:
        logs.append(log)

    return script


# ---------- every message, its move and its reply ----------


async def test_every_message_is_logged_with_its_move_and_the_reply_line(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, keen="10B-01", unsure="10B-02")
    keen = pupil("keen", "right how wrong", note_target=True)
    unsure = pupil("unsure", "not_sure wrong right", kind="struggling", guide_target=True)
    writer = Writer(fallback=("how",))
    read = []

    async def call_of(line_id: str) -> str | None:
        read.append(line_id)
        return None

    log = await play(
        app, three, [keen, unsure], seated, writer=writer, read_call=call_of, max_turns=3
    )

    # The only events are the writer's fallbacks, on "how" (see the test after this one).
    assert log.errors == []
    assert {(e["what"], e["beat"]) for e in log.events} == {("writer fell back", "how")}
    assert (log.key, log.session_id) == ("maths-1", str(three.session.id))
    for who in (keen, unsure):
        name, moves = who.persona.name, [b.kind for b in who.persona.plan]
        seat = seated[name]
        mine = of(log, seat)
        assert [s.beat for s in mine] == ["open", *moves]
        assert [s.text for s in mine] == ["", *(f"{SAYS[m]} ({name})" for m in moves)]
        assert [s.fallback for s in mine] == [False, *(m == "how" for m in moves)]
        assert all(s.status == 200 and s.kind == who.kind for s in mine)
        assert all(s.session_id == str(three.session.id) for s in mine)
        assert all(datetime.fromisoformat(s.at).tzinfo and s.seconds >= 0 for s in mine)
        # Each reply is the tutor's line that answered it on the pupil's page, which grows by
        # their message and that reply each time.
        page = await page_of(app, three, seat)
        assert [s.agent_line_id for s in mine] == [
            line["id"] for line in page["lines"] if line["who"] == "agent"
        ]
        assert [s.lines for s in mine] == [1, 3, 5, 7]
        assert all(s.step_index == 0 and isinstance(s.wrong_tries, int) for s in mine)
    assert all(s.agent_line_id for s in log.sent if s.status == 200)
    # The checks know who is who by pseudonym.
    assert log.cast == {
        seated["keen"].pseudonym: {
            "name": "keen",
            "kind": "average",
            "steer": None,
            "eal": False,
            "note_target": True,
            "guide_target": False,
            "joins_after_s": 0,
            "signs_back_in": False,
        },
        seated["unsure"].pseudonym: {
            "name": "unsure",
            "kind": "struggling",
            "steer": None,
            "eal": False,
            "note_target": False,
            "guide_target": True,
            "joins_after_s": 0,
            "signs_back_in": False,
        },
    }
    # The writer is handed the conversation as the pupil sees it, as who said what.
    keen_asked = [lines for name, _, lines in writer.asked if name == "keen"]
    assert keen_asked[0] == [{"who": "agent", "text": ASKS}]
    assert keen_asked[1] == [
        {"who": "agent", "text": ASKS},
        {"who": "student", "text": "x = 5 (keen)"},
        {"who": "agent", "text": ASKS},
    ]
    # A pupil on a plan never needs the tutor's pitch call; each waited before every move.
    assert read == []
    assert clock.waits == [0] * 6


async def test_each_stand_in_line_is_logged_with_why_the_writer_fell_back(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, keen="10B-01", rushed="10B-02")
    keen = pupil("keen", "right how not_sure how")
    # A double tap's line is written once, as a wrong answer, and sent twice.
    rushed = pupil("rushed", "double_tap right", kind="struggling")
    writer = Writer(fallback=("how", "wrong"))

    log = await play(app, three, [keen, rushed], seated, writer=writer, max_turns=4)

    assert log.errors == []
    fell_back = [e for e in log.events if e["what"] == "writer fell back"]
    assert fell_back == log.events
    # One event a line the writer could not write, with the reason it kept for that line.
    assert sorted((e["pupil"], e["beat"], e["why"]) for e in fell_back) == [
        (seated["keen"].pseudonym, "how", "http 429 on how for keen"),
        (seated["keen"].pseudonym, "how", "http 429 on how for keen"),
        (seated["rushed"].pseudonym, "wrong", "http 429 on wrong for rushed"),
    ]
    for event in fell_back:
        assert set(event) == {"what", "pupil", "beat", "why", "at"}
        assert datetime.fromisoformat(event["at"]).tzinfo is not None
    # The lines themselves went as they always did, marked as fallbacks.
    assert [s.fallback for s in of(log, seated["keen"])] == [False, False, True, False, True]
    assert {s.fallback for s in of(log, seated["rushed"]) if s.beat == "double_tap"} == {True}


async def test_a_writer_that_keeps_no_reason_is_logged_as_giving_none(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, keen="10B-01")

    class Silent:
        async def write(self, persona: Persona, move: Beat, lines: list[dict]):
            return "x = 5", True

    log = await play(app, three, [pupil("keen", "right")], seated, writer=Silent(), max_turns=1)

    [event] = log.events
    assert (event["what"], event["beat"], event["why"]) == ("writer fell back", "right", None)


async def test_a_steered_pupil_moves_by_the_tutors_call_on_each_reply(app, three):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, slow="10B-01")
    read = []

    async def stretched(line_id: str) -> str | None:
        read.append(line_id)
        return "stretched"

    slow = Pupil("average", Persona("slow", "14, slow and careful", [beat("right")]), steer="slow")
    log = await play(app, three, [slow], seated, read_call=stretched, max_turns=3)

    mine = of(log, seated["slow"])
    # Gets there slowly on the tutor's own version: what do you mean, closer, then right.
    assert [s.beat for s in mine] == ["open", "what_mean", "closer", "right_why"]
    assert read == [s.agent_line_id for s in mine]


async def test_a_steered_pupil_reacts_to_each_new_call_and_counts_afresh_on_a_new_step(app, three):
    three.tutor = llm.ScriptedClient(moving_on)
    seated = await seats(app, three, slow="10B-01")
    calls = ["stretched", "stayed", "stayed", "stretched", "as written", "as written"]
    read: list[str] = []

    async def call_of(line_id: str) -> str | None:
        read.append(line_id)
        return calls[len(read) - 1]

    slow = Pupil("average", Persona("slow", "14, slow and careful", [beat("right")]), steer="slow")
    log = await play(app, three, [slow], seated, read_call=call_of, max_turns=5)

    mine = of(log, seated["slow"])
    # Each move answers the call on the reply just before it. On the tutor's version (stretched,
    # then stayed): what do you mean, closer, then right with a reason, which moves them on. On
    # the new step the count starts again; on the step as written they just answer.
    assert [(s.beat, s.step_index) for s in mine] == [
        ("open", 0),
        ("what_mean", 0),
        ("closer", 0),
        ("right_why", 1),
        ("what_mean", 1),
        ("right", 2),
    ]
    assert read == [s.agent_line_id for s in mine]


@pytest.mark.parametrize("trouble", ["raises", "hangs"])
async def test_a_pitch_call_that_cannot_be_read_is_an_error_and_the_pupil_carries_on(
    app, three, monkeypatch, trouble
):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, slow="10B-01")
    # Not the real ten seconds: a hanging read is given up on at once.
    monkeypatch.setattr(driver, "READ_CALL_TIMEOUT_S", 0.01)
    read: list[str] = []
    cut_off = asyncio.Event()

    async def call_of(line_id: str) -> str | None:
        # The first read fails, raising or hanging; every later one says the tutor stretched.
        read.append(line_id)
        if len(read) > 1:
            return "stretched"
        if trouble == "raises":
            raise RuntimeError("the record could not be read")
        try:
            await asyncio.Event().wait()
        finally:
            cut_off.set()

    slow = Pupil("average", Persona("slow", "14, slow and careful", [beat("right")]), steer="slow")
    log = await asyncio.wait_for(
        play(app, three, [slow], seated, read_call=call_of, max_turns=3), timeout=10
    )

    mine = of(log, seated["slow"])
    # With no call on the opening they answer the step as written, then react to the calls.
    assert [s.beat for s in mine] == ["open", "right", "what_mean", "closer"]
    failed = "RuntimeError: the record could not be read" if trouble == "raises" else "TimeoutError"
    assert log.errors == [
        f"{seated['slow'].pseudonym}: could not read the tutor's pitch call on line "
        f"{mine[0].agent_line_id}: {failed}"
    ]
    # A hanging read is cut off, not left running.
    assert trouble == "raises" or cut_off.is_set()


async def test_a_copier_sends_a_classmates_wrong_answer_word_for_word(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, classmate="10B-01", copier="10B-02")
    writer = Writer()

    # Alone there is no wrong answer to copy, so they give a wrong answer of their own.
    log = await play(
        app,
        three,
        [pupil("copier", "copied_wrong", kind="copier")],
        seated,
        writer=writer,
        max_turns=1,
    )
    [_, own] = of(log, seated["copier"])
    assert (own.beat, own.text) == ("wrong", "x = 7 (copier)")

    # Next to a classmate, once they have answered wrong, the copier sends the latest of their
    # wrong answers exactly, without the writer.
    logs: list[LessonLog] = []
    clock.hold(60, lambda: bool(logs) and len(of(logs[0], seated["classmate"])) == 3)
    writer.asked.clear()
    log = await play(
        app,
        three,
        [
            pupil("classmate", "wrong bare_wrong"),
            pupil("copier", "copied_wrong", kind="copier", joins_after_s=60),
        ],
        seated,
        writer=writer,
        teacher_script=keep(logs),
        max_turns=2,
    )
    copied = of(log, seated["copier"])[1:]
    assert [(s.beat, s.text, s.status) for s in copied] == [
        ("copied_wrong", "8 (classmate)", 200)
    ] * 2
    assert [name for name, _, _ in writer.asked] == ["classmate", "classmate"]
    assert log.errors == []


# ---------- joining late and signing back in ----------


async def test_a_late_pupil_starts_after_the_others(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, early="10B-01", late="10B-02")
    browsers = Browsers(app)
    logs: list[LessonLog] = []
    clock.hold(180, lambda: bool(logs) and len(of(logs[0], seated["early"])) == 3)

    log = await play(
        app,
        three,
        [pupil("early", "right wrong"), pupil("late", "not_sure right", joins_after_s=180)],
        seated,
        browsers=browsers,
        teacher_script=keep(logs),
        max_turns=2,
    )

    early, late = of(log, seated["early"]), of(log, seated["late"])
    assert [s.beat for s in late] == ["open", "not_sure", "right"]
    # They get the opening, on the first step, after everything the others had done.
    opened = late[0]
    assert (opened.status, opened.step_index, opened.lines) == (200, 0, 1)
    assert opened.agent_line_id
    assert log.sent.index(opened) > log.sent.index(early[-1])
    # And they signed in only after their wait.
    assert 180 in clock.waits
    joins = [a for a in browsers.asked if a.path == "/api/auth/join"]
    assert [a.body["code"] for a in joins] == [seated["early"].code, seated["late"].code]
    late_join = browsers.asked.index(joins[1])
    assert all(i < late_join for i, a in enumerate(browsers.asked) if a.browser == joins[0].browser)
    assert log.errors == []


async def test_signing_back_in_returns_to_the_same_step(app, three):
    three.tutor = llm.ScriptedClient(moving_on)
    seated = await seats(app, three, back="10B-01")
    code = seated["back"].code
    browsers = Browsers(app)

    log = await play(
        app,
        three,
        [pupil("back", "right how wrong right", signs_back_in=True)],
        seated,
        browsers=browsers,
        max_turns=4,
    )

    mine = of(log, seated["back"])
    assert [s.beat for s in mine] == ["open", "right", "how", "signed_back_in", "wrong", "right"]
    assert all(s.status == 200 for s in mine) and log.errors == []
    # Back on the step they left, with every line they had: the view was read, nothing sent.
    before, again = mine[2], mine[3]
    assert again.text == "" and again.step_index == before.step_index == 1
    assert (again.lines, again.agent_line_id) == (before.lines, before.agent_line_id)
    # In a new browser, with no cookie, signed in with the same code, and carrying on there.
    assert browsers.made == 2
    joins = [a for a in browsers.asked if a.path == "/api/auth/join"]
    assert [(a.browser, a.body["code"], a.cookie) for a in joins] == [
        (1, code, False),
        (2, code, False),
    ]
    assert {a.browser for a in browsers.asked[browsers.asked.index(joins[1]) :]} == {2}
    assert [s.step_index for s in mine[4:]] == [1, 2]


# ---------- the lesson paused, out of time or ended ----------


async def test_a_paused_lesson_makes_pupils_wait_not_fail(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, waiting="10B-01")
    seat = seated["waiting"]
    paused, resumed = asyncio.Event(), asyncio.Event()

    async def teacher(log: LessonLog) -> None:
        # The teacher pauses the class once the pupil is in, and resumes it once the pupil has
        # been told it is paused.
        await happens(lambda: len(of(log, seat)) == 1)
        assert (await set_state(app, three, "paused")).status_code == 200
        paused.set()
        await happens(lambda: any(e["what"] == "paused" for e in log.events))
        assert (await set_state(app, three, "open")).status_code == 200
        log.events.append({"what": "resumed"})
        resumed.set()

    # The pupil thinks until the class is paused, and waits as told until it is resumed.
    clock.hold(0, paused.is_set)
    clock.hold(driver.PAUSED_WAIT_S, resumed.is_set)
    log = await play(
        app,
        three,
        [pupil("waiting", "ask_teacher wrong right")],
        seated,
        teacher_script=teacher,
        max_turns=3,
    )

    assert log.errors == []
    # Asking for the teacher works while paused; the message waited, then went.
    assert [(s.beat, s.status) for s in of(log, seat)] == [
        ("open", 200),
        ("ask_teacher", 200),
        ("wrong", 200),
        ("right", 200),
    ]
    paused_note, resumed_note, stopped_note = log.events
    assert (paused_note["what"], paused_note["pupil"], paused_note["beat"]) == (
        "paused",
        seat.pseudonym,
        "wrong",
    )
    assert resumed_note == {"what": "resumed"}
    assert stopped_note["what"] == driver.PUPILS_STOPPED
    assert clock.waits == [0, 0, driver.PAUSED_WAIT_S, 0]


def pupils_stopped(log: LessonLog) -> bool:
    return any(e["what"] == driver.PUPILS_STOPPED for e in log.events)


async def test_a_teacher_who_reads_the_class_in_a_loop_is_told_when_the_pupils_stop(app, three):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, steady="10B-01")

    async def teacher(log: LessonLog) -> None:
        # Glances at the class every so often, until the pupils have all stopped.
        async with browser(app) as theirs:
            while not pupils_stopped(log):
                started = time.perf_counter()
                read = await theirs.get("/api/teacher/thread", headers=three.headers(three.teacher))
                assert read.status_code == 200
                log.view_seconds.append(time.perf_counter() - started)
                await asyncio.sleep(0.005)
        log.events.append({"what": "teacher done"})

    log = await asyncio.wait_for(
        play(
            app,
            three,
            [pupil("steady", "right wrong")],
            seated,
            teacher_script=teacher,
            max_turns=2,
        ),
        timeout=10,
    )

    assert [s.beat for s in of(log, seated["steady"])] == ["open", "right", "wrong"]
    assert log.view_seconds and log.errors == []
    # Told once the pupils had stopped, after everything they sent, and it then finished.
    assert [e["what"] for e in log.events] == [driver.PUPILS_STOPPED, "teacher done"]
    stopped_at = datetime.fromisoformat(log.events[0]["at"])
    assert all(datetime.fromisoformat(s.at) < stopped_at for s in log.sent)


async def test_a_teacher_script_that_never_ends_is_stopped_as_an_error(app, three, monkeypatch):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, steady="10B-01")
    monkeypatch.setattr(driver, "TEACHER_GRACE_S", 0.05)
    stopped = asyncio.Event()

    async def teacher(log: LessonLog) -> None:
        try:
            await asyncio.Event().wait()  # never told anything, never ends
        finally:
            stopped.set()

    log = await asyncio.wait_for(
        play(app, three, [pupil("steady", "right")], seated, teacher_script=teacher, max_turns=1),
        timeout=10,
    )

    assert stopped.is_set()
    assert [s.beat for s in of(log, seated["steady"])] == ["open", "right"]
    assert log.errors == [
        "teacher: still at work 0.05 seconds after the pupils stopped, so told to stop"
    ]


async def test_a_teacher_script_that_will_not_stop_is_left_behind_as_an_error(
    app, three, monkeypatch
):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, steady="10B-01")
    monkeypatch.setattr(driver, "TEACHER_GRACE_S", 0.05)
    monkeypatch.setattr(driver, "TEACHER_STOP_S", 0.05)
    let_go, ended = asyncio.Event(), asyncio.Event()

    async def stubborn(log: LessonLog) -> None:
        try:
            while not let_go.is_set():
                try:
                    await let_go.wait()
                except asyncio.CancelledError:
                    continue  # told to stop, and carries on regardless
        finally:
            ended.set()

    log = await asyncio.wait_for(
        play(app, three, [pupil("steady", "right")], seated, teacher_script=stubborn, max_turns=1),
        timeout=10,
    )

    assert log.errors == [
        "teacher: still at work 0.05 seconds after the pupils stopped, so told to stop",
        "teacher: still running 0.05 seconds after being told to stop, so left behind",
    ]
    assert not ended.is_set()
    # The test's own clean-up: the script left behind is let go.
    let_go.set()
    await happens(ended.is_set)


async def test_time_up_stops_a_pupil_cleanly(app, three, db, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, steady="10B-01")

    async def time_runs_out() -> None:
        three.session.closes_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

    clock.at(3, time_runs_out)  # while the pupil thinks before their third move
    log = await play(app, three, [pupil("steady", "right wrong how right")], seated, max_turns=4)

    mine = of(log, seated["steady"])
    assert [(s.beat, s.status) for s in mine] == [
        ("open", 200),
        ("right", 200),
        ("wrong", 200),
        ("how", 409),
    ]
    assert [(e["what"], e["pupil"], e["beat"]) for e in log.events] == [
        ("time up", seated["steady"].pseudonym, "how")
    ]
    assert log.errors == []
    # Stopped: no more thinking, and no more moves.
    assert clock.waits == [0, 0, 0]


async def test_a_lesson_the_teacher_ends_stops_its_pupils_cleanly(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, steady="10B-01")

    async def teacher_ends_it() -> None:
        assert (await set_state(app, three, "closed")).status_code == 200

    clock.at(2, teacher_ends_it)
    log = await play(app, three, [pupil("steady", "right ask_teacher wrong")], seated, max_turns=3)

    mine = of(log, seated["steady"])
    assert [(s.beat, s.status) for s in mine] == [
        ("open", 200),
        ("right", 200),
        ("ask_teacher", 409),
    ]
    assert [(e["what"], e["beat"]) for e in log.events] == [("closed", "ask_teacher")]
    assert log.errors == []


# ---------- rate limits, an agent that cannot answer, no answer at all ----------


async def test_rate_limits_and_unavailable_are_retried_and_counted(app, three, clock, monkeypatch):
    settings = get_settings()
    # The day's cap on the pupil's turns is reached with the opening, and lifted while they wait;
    # then the tutor's model gives no answer once.
    monkeypatch.setattr(settings, "student_turns_per_day", 1)

    async def cap_lifted() -> None:
        monkeypatch.setattr(settings, "student_turns_per_day", 200)

    clock.at(3, cap_lifted)
    three.tutor = llm.ScriptedClient(failing(2))
    seated = await seats(app, three, keen="10B-01")

    log = await play(app, three, [pupil("keen", "wrong right")], seated, max_turns=2)

    mine = of(log, seated["keen"])
    # Only what each move ended with is sent; the refusals on the way are counted as events.
    assert [(s.beat, s.status) for s in mine] == [("open", 200), ("wrong", 200), ("right", 200)]
    assert all(s.agent_line_id for s in log.sent if s.status == 200)
    assert [(e["what"], e["pupil"], e["beat"]) for e in log.events] == [
        ("rate limited", seated["keen"].pseudonym, "wrong"),
        ("rate limited", seated["keen"].pseudonym, "wrong"),
        ("unavailable", seated["keen"].pseudonym, "wrong"),
    ]
    assert "a lot today" in log.events[0]["detail"]
    assert log.errors == []
    assert clock.waits == [
        0,
        driver.RATE_LIMITED_WAIT_S,
        driver.RATE_LIMITED_WAIT_S,
        driver.UNAVAILABLE_WAIT_S,
        0,
    ]


async def test_a_refusal_that_outlasts_its_retries_is_an_error(app, three, clock, monkeypatch):
    seated = await seats(app, three, capped="10B-01", unlucky="10B-02")
    three.tutor = llm.ScriptedClient(asking)

    # The cap is never lifted: refused once and six times again, then given up as an error.
    monkeypatch.setattr(get_settings(), "student_turns_per_day", 1)
    log = await play(app, three, [pupil("capped", "wrong")], seated, max_turns=1)
    [_, refused] = of(log, seated["capped"])
    assert (refused.beat, refused.status, refused.agent_line_id) == ("wrong", 429, None)
    assert [e["what"] for e in log.events] == ["rate limited"] * 7
    assert clock.waits == [0] + [driver.RATE_LIMITED_WAIT_S] * 6
    [error] = log.errors
    assert seated["capped"].pseudonym in error and "429" in error

    # The tutor's model gives no answer, again and again: tried once more, then an error.
    monkeypatch.setattr(get_settings(), "student_turns_per_day", 200)
    three.tutor = llm.ScriptedClient(failing(2, 3))
    clock.waits.clear()
    log = await play(app, three, [pupil("unlucky", "wrong")], seated, max_turns=1)
    [_, failed] = of(log, seated["unlucky"])
    assert (failed.beat, failed.status) == ("wrong", 503)
    assert [e["what"] for e in log.events] == ["unavailable"] * 2
    assert clock.waits == [0, driver.UNAVAILABLE_WAIT_S]
    [error] = log.errors
    assert seated["unlucky"].pseudonym in error and "503" in error


async def test_signing_in_and_back_in_wait_out_rate_limits_and_unavailable(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, back="10B-01")
    joins: list[Asked] = []

    def busy_at_the_door(asked: Asked) -> int | None:
        # Signing in is refused once as too many at once, and signing back in once as
        # unavailable; each goes through when asked again.
        if asked.path != "/api/auth/join":
            return None
        joins.append(asked)
        return {1: 429, 3: 503}.get(len(joins))

    log = await play(
        app,
        three,
        [pupil("back", "right how wrong right", signs_back_in=True)],
        seated,
        browsers=Browsers(app, instead=busy_at_the_door),
        max_turns=4,
    )

    assert log.errors == []
    assert [s.beat for s in of(log, seated["back"])] == [
        "open",
        "right",
        "how",
        "signed_back_in",
        "wrong",
        "right",
    ]
    assert [(e["what"], e["pupil"], e["beat"]) for e in log.events] == [
        ("rate limited", seated["back"].pseudonym, "sign_in"),
        ("unavailable", seated["back"].pseudonym, "sign_in"),
    ]
    assert len(joins) == 4
    assert clock.waits.count(driver.RATE_LIMITED_WAIT_S) == 1
    assert clock.waits.count(driver.UNAVAILABLE_WAIT_S) == 1


async def test_failures_on_one_side_are_logged_and_the_lesson_goes_on(app, three):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, timed_out="10B-01", broken="10B-02")
    lesson = f"/api/learn/{three.session.id}/messages"
    dropped: list[Asked] = []

    def first_message_of_the_first_pupil(asked: Asked) -> None:
        if dropped or asked.path != lesson or asked.browser != 1:
            return None
        dropped.append(asked)
        raise httpx.ReadTimeout("no answer in time")

    # The first pupil's first message gets no answer in time.
    browsers = Browsers(app, instead=first_message_of_the_first_pupil)

    async def teacher(log: LessonLog) -> None:
        raise RuntimeError("the teacher script broke")

    log = await play(
        app,
        three,
        [pupil("timed_out", "wrong right"), pupil("broken", "right")],
        seated,
        browsers=browsers,
        writer=Writer(breaks_for="broken"),
        teacher_script=teacher,
        max_turns=2,
    )

    # No answer: logged with status 0 and as an error, and the pupil carries on.
    assert [(s.beat, s.status) for s in of(log, seated["timed_out"])] == [
        ("open", 200),
        ("wrong", 0),
        ("right", 200),
    ]
    # A pupil whose writer fails stops; the teacher script's failure is logged too.
    assert [s.beat for s in of(log, seated["broken"])] == ["open"]
    assert sorted(log.errors) == sorted(
        [
            f"{seated['timed_out'].pseudonym}, wrong: no answer (ReadTimeout)",
            f"{seated['broken'].pseudonym}: stopped by RuntimeError: the writer broke",
            "teacher: stopped by RuntimeError: the teacher script broke",
        ]
    )


async def test_a_refused_code_or_a_move_with_nothing_to_undo_is_an_error(app, three):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, locked_out="10B-01", muddled="10B-02")
    # A code the platform does not know, as when the teacher has issued new ones since.
    seated["locked_out"] = Seat(seated["locked_out"].student_id, "10B-01", "AAAA-BBBB")

    log = await play(
        app,
        three,
        [pupil("locked_out", "right"), pupil("muddled", "come_back right")],
        seated,
        max_turns=2,
    )

    # The pupil who cannot sign in never starts, and their code is not in the log.
    assert of(log, seated["locked_out"]) == []
    # Coming back with nothing left for later sends nothing, and the pupil carries on.
    assert [(s.beat, s.status) for s in of(log, seated["muddled"])] == [
        ("open", 200),
        ("right", 200),
    ]
    assert sorted(log.errors) == [
        "10B-01: signing in with their code answered 401 That code was not recognised. Check "
        "it with your teacher.",
        "10B-02, come_back: no part was left for later to come back to",
    ]
    assert "AAAA-BBBB" not in repr(log)


# ---------- the buttons, the taps and the moves ----------


async def test_the_buttons_go_where_a_pupil_would_press_them(app, three):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, presser="10B-01")
    seat = seated["presser"]
    browsers = Browsers(app)
    writer = Writer()
    moves = (
        "wrong button:why_wrong button:dont_understand helped ask_teacher leave right come_back "
        "long_paste greek"
    )

    log = await play(
        app,
        three,
        [pupil("presser", moves)],
        seated,
        browsers=browsers,
        writer=writer,
        max_turns=10,
    )

    assert log.errors == []
    mine = of(log, seat)
    assert [s.beat for s in mine] == ["open", *moves.split()]
    assert all(s.status == 200 for s in mine)
    lesson = f"/api/learn/{three.session.id}"
    rated = mine[3].agent_line_id  # the tutor's reply to "I don't understand"
    assert [(a.method, a.path, a.body) for a in browsers.asked if a.path.startswith(lesson)] == [
        ("POST", f"{lesson}/start", None),
        ("POST", f"{lesson}/messages", {"text": "x = 7 (presser)"}),
        ("POST", f"{lesson}/messages", {"text": "", "intent": "why_wrong"}),
        ("POST", f"{lesson}/messages", {"text": "", "intent": "dont_understand"}),
        ("POST", f"{lesson}/lines/{rated}/helped", {"helped": True}),
        ("POST", f"{lesson}/request-teacher", None),
        ("POST", f"{lesson}/move", {"leave": 0}),
        ("POST", f"{lesson}/messages", {"text": "x = 5 (presser)"}),
        ("POST", f"{lesson}/move", {"to": 0}),
        ("POST", f"{lesson}/messages", {"text": CANNED["long_paste"]}),
        ("POST", f"{lesson}/messages", {"text": CANNED["greek"]}),
    ]
    # A press has no words of the pupil's; the fixed texts go as they are, not written.
    assert [s.text for s in mine] == [
        "",
        "x = 7 (presser)",
        "",
        "",
        "",
        "",
        "",
        "x = 5 (presser)",
        "",
        CANNED["long_paste"],
        CANNED["greek"],
    ]
    assert [kind for _, kind, _ in writer.asked] == ["wrong", "right"]
    # Left for later, on to the next step, and back to the one left.
    assert [s.step_index for s in mine] == [0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0]
    # The tap is kept on the reply it was about, and the teacher was asked for.
    page = await page_of(app, three, seat)
    assert next(line for line in page["lines"] if line["id"] == rated)["helped"] is True
    assert page["asked_teacher"] is True


async def test_a_double_tap_sends_one_line_twice_at_once(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, rushed="10B-01")
    browsers = Browsers(app)
    writer = Writer()

    log = await play(
        app,
        three,
        [pupil("rushed", "double_tap", kind="struggling")],
        seated,
        browsers=browsers,
        writer=writer,
        max_turns=1,
    )

    taps = of(log, seated["rushed"])[1:]
    assert [(s.beat, s.text) for s in taps] == [("double_tap", "x = 7 (rushed)")] * 2
    assert [kind for _, kind, _ in writer.asked] == ["wrong"]
    # Both on their way at once: the platform answers one and holds the other back, and the one
    # held back is not sent again.
    assert browsers.most_at_once == 2
    assert sorted(s.status for s in taps) == [200, 429]
    assert log.events == [] and log.errors == [] and clock.waits == [0]
    page = await page_of(app, three, seated["rushed"])
    assert [line["who"] for line in page["lines"]] == ["agent", "student", "agent"]


async def test_a_jump_goes_to_the_last_part_takes_one_move_there_and_comes_back(app, three, db):
    brief = LessonBrief.model_validate(three.contract.brief)
    brief.rules = brief.rules.model_copy(update={"free_movement": True})
    three.contract.brief = brief.model_dump(mode="json")
    await db.commit()
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, ahead="10B-01")
    browsers = Browsers(app)

    log = await play(
        app,
        three,
        [pupil("ahead", "not_sure jump wrong")],
        seated,
        browsers=browsers,
        max_turns=3,
    )

    assert [(s.beat, s.step_index, s.status) for s in of(log, seated["ahead"])] == [
        ("open", 0, 200),
        ("not_sure", 0, 200),
        ("jump", 2, 200),
        ("not_sure", 2, 200),
        ("jump", 0, 200),
        ("wrong", 0, 200),
    ]
    assert [a.body for a in browsers.asked if a.path.endswith("/move")] == [{"to": 2}, {"to": 0}]
    assert log.errors == []


# Every move the driver makes itself, in an order one pupil could make them all in a lesson.
EVERY_DRIVER_MOVE = (
    "leave come_back helped ask_teacher button:dont_understand button:another_way "
    "button:example button:why_wrong long_paste greek double_tap jump"
)


async def test_every_move_the_driver_makes_itself_has_its_own_way_and_skips_the_writer(
    app, three, db
):
    moves = EVERY_DRIVER_MOVE.split()
    assert set(moves) == DRIVER_KINDS, "add the new move here, and give it its own way"
    brief = LessonBrief.model_validate(three.contract.brief)
    brief.rules = brief.rules.model_copy(update={"free_movement": True})
    three.contract.brief = brief.model_dump(mode="json")
    await db.commit()
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, busy="10B-01")
    writer = Writer()

    log = await play(
        app,
        three,
        [pupil("busy", EVERY_DRIVER_MOVE)],
        seated,
        writer=writer,
        max_turns=len(moves),
    )

    assert log.errors == []
    assert DRIVER_KINDS <= {s.beat for s in of(log, seated["busy"])}
    # Only written moves reach the writer: the double tap's line, and the jump's move there.
    assert [kind for _, kind, _ in writer.asked] == ["wrong", "not_sure"]
    assert all(kind in BEATS for _, kind, _ in writer.asked)


async def test_a_move_the_driver_has_no_way_to_make_stops_the_pupil_as_an_error(app, three):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, odd="10B-01")
    writer = Writer()
    odd = Pupil("average", Persona("odd", "14, the odd one out", [Beat("cartwheel", "")]))

    log = await play(app, three, [odd], seated, writer=writer, max_turns=1)

    assert [s.beat for s in of(log, seated["odd"])] == ["open"]
    assert writer.asked == []
    [error] = log.errors
    assert error.startswith(f"{seated['odd'].pseudonym}: stopped by ValueError: ")
    assert "'cartwheel'" in error


# ---------- when a pupil stops, and their think times ----------


async def test_a_pupil_stops_once_the_lesson_is_completed(app, three, clock):
    three.tutor = llm.ScriptedClient(moving_on)
    seated = await seats(app, three, quick="10B-01")

    log = await play(app, three, [pupil("quick", "right", kind="strong")], seated, max_turns=14)

    # Three steps, three right answers, and then no more moves though turns were left.
    assert [s.beat for s in of(log, seated["quick"])] == ["open", "right", "right", "right"]
    assert clock.waits == [0, 0, 0]
    assert (await page_of(app, three, seated["quick"]))["completed"] is True


async def test_think_times_are_random_but_repeat_for_the_same_lesson(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, thinker="10B-01")

    async def waits_in(key: str) -> list[float]:
        clock.waits.clear()
        await play(
            app,
            three,
            [pupil("thinker", "not_sure")],
            seated,
            think=(10, 60),
            max_turns=3,
            key=key,
        )
        return list(clock.waits)

    first = await waits_in("maths-1")
    assert len(set(first)) == 3 and all(10 <= wait <= 60 for wait in first)
    assert await waits_in("maths-1") == first
    assert await waits_in("maths-2") != first


async def test_a_pupil_with_no_seat_is_a_mistake_before_anything_is_sent(app, three):
    browsers = Browsers(app)
    with pytest.raises(ValueError, match="nobody"):
        await play(app, three, [pupil("nobody", "right")], {}, browsers=browsers)
    assert browsers.made == 0


# ---------- a class at once, and a run stopped part way ----------


async def test_ten_pupils_at_once_all_finish_with_every_move_logged(app, three, db):
    await more_pupils(db, three, 8)
    three.tutor = llm.ScriptedClient(asking)
    plans = [
        "right wrong how",
        "not_sure button:example right",
        "wrong button:why_wrong helped",
        "how right_why right",
        "bare_wrong ask_teacher right",
        "what_mean closer right",
        "right long_paste wrong",
        "greek not_sure right",
        "wrong right how",
        "closer bare_wrong right_why",
    ]
    names = {f"p{n}": f"10B-{n:02d}" for n in range(1, 11)}
    seated = await seats(app, three, **names)
    pupils = [pupil(name, plan) for name, plan in zip(names, plans, strict=True)]
    browsers = Browsers(app)

    log = await play(app, three, pupils, seated, browsers=browsers, max_turns=3)

    assert log.errors == [] and log.events == []
    for who in pupils:
        mine = of(log, seated[who.persona.name])
        assert [s.beat for s in mine] == ["open", *(b.kind for b in who.persona.plan)]
        assert all(s.status == 200 and s.agent_line_id for s in mine)
    assert len(log.sent) == 10 * 4
    assert len(log.cast) == 10
    # Side by side, not one after another.
    assert browsers.most_at_once > 1


async def test_a_run_stopped_part_way_keeps_what_was_logged_in_the_callers_log(app, three, clock):
    three.tutor = llm.ScriptedClient(asking)
    seated = await seats(app, three, steady="10B-01")
    kept = LessonLog(key="", session_id="", sent=[], events=[], view_seconds=[], errors=[], cast={})
    # The pupil thinks freely for two moves, then is held thinking until the run is stopped.
    clock.hold(0, lambda: len(kept.sent) < 3)

    running = asyncio.create_task(
        play(app, three, [pupil("steady", "right wrong how right")], seated, log=kept)
    )
    await happens(lambda: len(clock.waits) == 3)
    running.cancel()  # as Ctrl-C does
    with pytest.raises(asyncio.CancelledError):
        await running

    assert (kept.key, kept.session_id) == ("maths-1", str(three.session.id))
    assert [s.beat for s in kept.sent] == ["open", "right", "wrong"]
    assert list(kept.cast) == [seated["steady"].pseudonym]
    assert kept.errors == []
