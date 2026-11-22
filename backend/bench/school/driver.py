"""The lesson driver: one lesson played by many pupils at once, as a class works through it.
Each pupil has a browser of their own (one cookie jar), signs in with their join code and
works through the lesson: typing, pressing the buttons, leaving a step for later and coming
back, joining late or signing out and back in. A teacher script can run beside them. Every
request a pupil makes in the lesson is logged with the move it was meant to be, so the checks
know what the right reaction was.

The platform's ordinary refusals are waited out and counted, never crashed on:
- a paused lesson is asked again every 5 seconds while it stays paused (up to a limit);
- a reply still in flight, or the day's cap on a pupil's turns (429), every 5 seconds, six
  times at most;
- an agent that could not answer (503), once more after 15 seconds.
Each refusal is noted in the log's events ("paused", "rate limited", "unavailable"), and only
the answer a move ended with is logged as sent. When the lesson's time is up or it is closed
(409), the pupil stops, noted as "time up" or "closed". Anything else the platform answers is
an error in the log, and the pupil goes on to their next move.

A pupil stops when the lesson says they have completed it, after `max_turns` moves, or when
their lesson stops. Their words are the writer's: the driver hands it the move and the lines
on the pupil's screen, never the tutor's pitch call, which only steers which move comes next.
When the writer could not write a line and sent the move's stand-in line, the events say so,
with the reason the writer kept ("writer fell back").

A browser's cookie, and a pupil's join code, are never logged or put in an error.
"""

import asyncio
import random
import time
from asyncio import sleep
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from bench.pupils import BEATS, CANNED, Beat, Persona, beat
from bench.school.cast import Pupil, SteerState, next_beat
from bench.school.teacher import Seat

# Seconds to wait before asking again after each kind of refusal, and how many times a refused
# request is asked again at most.
PAUSED_WAIT_S = 5
RATE_LIMITED_WAIT_S = 5
RATE_LIMITED_RETRIES = 6
UNAVAILABLE_WAIT_S = 15
UNAVAILABLE_RETRIES = 1
# A pause is waited out, but not for ever: a lesson still paused after this long stops the
# pupil, as an error, so that a pause nobody ends cannot hang the run.
LONGEST_PAUSE_S = 15 * 60
_RETRIES = {
    "paused": (PAUSED_WAIT_S, LONGEST_PAUSE_S // PAUSED_WAIT_S),
    "rate limited": (RATE_LIMITED_WAIT_S, RATE_LIMITED_RETRIES),
    "unavailable": (UNAVAILABLE_WAIT_S, UNAVAILABLE_RETRIES),
}
_STOPS = ("time up", "closed")

# What the platform says when it refuses a pupil for these reasons (app/auth.py and
# app/routers/learn.py).
PAUSED = "Session is paused."
CLOSED = "Session is closed."
TIME_UP = "Time's up"

# The moves whose message is a wrong answer, which a copier may copy.
WRONG = frozenset({"wrong", "bare_wrong", "confident_wrong", "copied_wrong"})
# The step a jump goes to, and the move the pupil writes there before going back: someone
# looking ahead is not sure about the last part yet.
JUMP_TO = 2
JUMP_WRITES = "not_sure"
# The move a double tap's line is written as: an answer sent in a rush.
DOUBLE_TAP_WRITES = "wrong"
# How many of the last lines on the pupil's screen the writer is given.
LINES_FOR_WRITER = 8
# How long a pupil's browser waits for an answer: one reply can take several model calls.
TIMEOUT = httpx.Timeout(240.0, connect=10.0)
# How long reading the tutor's pitch call on a line may take, in seconds, before the pupil
# carries on without it.
READ_CALL_TIMEOUT_S = 10
# The move a refusal while signing in is noted under in the events.
SIGN_IN = "sign_in"
# What the log's events say when the writer could not write a pupil's line, so the move's
# stand-in line was sent.
FELL_BACK = "writer fell back"
# What the log's events say once every pupil has stopped, for the teacher script; how long the
# script then has to finish, in seconds (time to end a pause it began, say); and how long it is
# given to wind down once told to stop, before it is left behind.
PUPILS_STOPPED = "pupils stopped"
TEACHER_GRACE_S = 300
TEACHER_STOP_S = 10


@dataclass
class Sent:
    """One request a pupil made in the lesson, as it was answered: who sent it (their pseudonym)
    and what kind of pupil they are; the move it was meant to be ("open" for the tutor's
    opening, "signed_back_in" for the page read after signing back in) and the words sent, ""
    when there were none; the status (0 when no answer came), how long the answer took in
    seconds and when the request went; and whether the words are the writer's fallback. From
    the view that came back with a success: the tutor's latest line on the page, the step the
    pupil is on, their wrong tries there and how many lines their page shows."""

    pupil: str
    kind: str
    session_id: str
    beat: str
    text: str
    status: int
    seconds: float
    agent_line_id: str | None
    at: str
    fallback: bool
    step_index: int | None = None
    wrong_tries: int | None = None
    lines: int | None = None


@dataclass
class LessonLog:
    """What happened in one lesson: everything the pupils sent; the events, which are the
    teacher script's actions and the driver's notes ({"what": "paused" | "rate limited" |
    "unavailable" | "time up" | "closed", "pupil", "beat", "at", "detail"}, where the beat is
    "sign_in" for a refusal while signing in; {"what": "writer fell back", "pupil", "beat",
    "why", "at"} for each line the writer could not write, the beat being the move it was asked
    for and why the reason it kept, None when it keeps none; and, when a teacher script runs,
    {"what": "pupils stopped", "at"}); how long the teacher's class view took each time the
    teacher script read
    it; the errors, in plain words; and the cast, each pupil's pseudonym to who they are in it."""

    key: str
    session_id: str
    sent: list[Sent]
    events: list[dict]
    view_seconds: list[float]
    errors: list[str]
    cast: dict[str, dict]


class Writer(Protocol):
    """Puts a move into a pupil's words (bench/pupils.py): the line, and whether it is the
    move's canned line because nothing better came. A writer may keep why in `last_failure`,
    which the driver reads straight after a write that fell back."""

    async def write(self, persona: Persona, beat: Beat, lines: list[dict]) -> tuple[str, bool]:
        """The pupil's line for this move, from the last lines on their screen."""


async def run_lesson(
    *,
    key: str,
    base_url: str,
    session_id: str,
    seats: dict[str, Seat],
    pupils: list[Pupil],
    writer: Writer,
    read_call: Callable[[str], Awaitable[str | None]],
    think: tuple[float, float],
    teacher_script: Callable[[LessonLog], Awaitable[None]] | None = None,
    max_turns: int = 14,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    log: LessonLog | None = None,
) -> LessonLog:
    """Plays the lesson `session_id` with `pupils`, all at once, and `teacher_script` beside
    them, which is handed the log to read and add to. Returns the log once every pupil has
    stopped and the teacher script has ended.

    Once every pupil has stopped, the log's events say so ({"what": "pupils stopped"}), so a
    teacher who reads the class view every so often can do it in a loop until then. A script
    still at work TEACHER_GRACE_S seconds later is told to stop, as an error, so the run cannot
    hang on it; one that has not stopped TEACHER_STOP_S seconds after that is left behind, as
    another. Stopping a script part way through a request is the last resort, as an app run in
    the same process may be left with that request's work half done.

    `seats` holds each pupil's join code under the name the cast calls them. `writer` puts each
    written move into the pupil's words. `read_call` gives the tutor's pitch call on one of its
    lines, for the steered pupils. Before each move a pupil waits between the two lengths in
    `think`, in seconds, drawn from a seed made of `key` and the pupil's name, so that a run
    repeats. `client_factory` makes each pupil's browser (a client with a cookie jar of its
    own), which the driver closes; without one, a client on `base_url`. `log`, when given, is
    the one filled as the lesson goes: an empty log the caller keeps hold of, so that a run
    stopped part way (by Ctrl-C, say) still has everything logged until then.

    A pupil with no seat is a mistake in the run: ValueError, before anything is sent."""
    missing = [p.persona.name for p in pupils if p.persona.name not in seats]
    if missing:
        raise ValueError(
            f"No seat for {', '.join(missing)}: seats are keyed by the name the cast calls "
            "each pupil."
        )
    cast = {seats[p.persona.name].pseudonym: _who(p) for p in pupils}
    if log is None:
        log = LessonLog(
            key=key,
            session_id=str(session_id),
            sent=[],
            events=[],
            view_seconds=[],
            errors=[],
            cast=cast,
        )
    else:
        log.key, log.session_id, log.cast = key, str(session_id), cast
    lesson = _Lesson(
        log=log,
        writer=writer,
        read_call=read_call,
        think=think,
        max_turns=max_turns,
        browser=client_factory or (lambda: httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT)),
    )
    teacher = asyncio.create_task(_teach(teacher_script, log)) if teacher_script else None
    try:
        await asyncio.gather(*(_Player(p, seats[p.persona.name], lesson).play() for p in pupils))
        if teacher is not None:
            log.events.append({"what": PUPILS_STOPPED, "at": datetime.now(UTC).isoformat()})
            await asyncio.wait({teacher}, timeout=TEACHER_GRACE_S)
            if not teacher.done():
                log.errors.append(
                    f"teacher: still at work {TEACHER_GRACE_S} seconds after the pupils "
                    "stopped, so told to stop"
                )
    finally:
        if teacher is not None:
            # A script still running is told to stop and given a moment to wind down. One that
            # ignores it is left behind rather than hang the run.
            teacher.cancel()
            await asyncio.wait({teacher}, timeout=TEACHER_STOP_S)
            if not teacher.done():
                log.errors.append(
                    f"teacher: still running {TEACHER_STOP_S} seconds after being told to "
                    "stop, so left behind"
                )
    return log


def _who(pupil: Pupil) -> dict:
    """What the checks need to know about a pupil of the cast."""
    return {
        "name": pupil.persona.name,
        "kind": pupil.kind,
        "steer": pupil.steer,
        "eal": pupil.persona.eal,
        "note_target": pupil.note_target,
        "guide_target": pupil.guide_target,
        "joins_after_s": pupil.joins_after_s,
        "signs_back_in": pupil.signs_back_in,
    }


async def _teach(script: Callable[[LessonLog], Awaitable[None]], log: LessonLog) -> None:
    """Runs the teacher script. A failure in it is logged, and the pupils carry on."""
    try:
        await script(log)
    except Exception as e:
        log.errors.append(f"teacher: stopped by {_failure(e)}")


def _failure(e: Exception) -> str:
    """An exception in plain words: its kind, and what it says when it says anything."""
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


@dataclass
class _Lesson:
    """What every pupil in the lesson shares."""

    log: LessonLog
    writer: Writer
    read_call: Callable[[str], Awaitable[str | None]]
    think: tuple[float, float]
    max_turns: int
    browser: Callable[[], httpx.AsyncClient]

    @property
    def path(self) -> str:
        return f"/api/learn/{self.log.session_id}"


@dataclass
class _Answer:
    """The platform's answer to one request: its status (0 when no answer came), the view when
    it is a success, what the platform said otherwise, how long it took and when it was asked."""

    status: int
    view: dict | None
    detail: str
    seconds: float
    at: str

    @property
    def outcome(self) -> str:
        """How it went: "ok", or why not: "paused", "time up", "closed", "rate limited",
        "unavailable", or "error" for anything else."""
        if 200 <= self.status < 300:
            return "ok"
        if self.status == 409 and self.detail == PAUSED:
            return "paused"
        if self.status == 409 and self.detail.startswith(TIME_UP):
            return "time up"
        if self.status == 409 and self.detail == CLOSED:
            return "closed"
        return {429: "rate limited", 503: "unavailable"}.get(self.status, "error")

    def said(self) -> str:
        return f"no answer ({self.detail})" if self.status == 0 else f"{self.status} {self.detail}"


# Which answer decides how two requests sent at once went: a success first, then a reason to
# stop, then anything unexpected, then the refusals worth waiting out.
_FIRST = ("ok", "time up", "closed", "error", "paused", "unavailable", "rate limited")


class _Player:
    """One pupil in the lesson, in a browser of their own."""

    def __init__(self, pupil: Pupil, seat: Seat, lesson: _Lesson) -> None:
        self.pupil = pupil
        self.seat = seat
        self.lesson = lesson
        self.log = lesson.log
        # The pupil's own think times: the same in every run of this lesson, whatever the
        # others do.
        self.rng = random.Random(f"{lesson.log.key}/{pupil.persona.name}")
        self.client: httpx.AsyncClient | None = None
        self.view: dict = {}
        self.state = SteerState()
        self.last_line: str | None = None
        self.last_call: str | None = None
        # The step they left for later, which coming back goes to.
        self.left: int | None = None
        self.stopped = False

    async def play(self) -> None:
        try:
            if self.pupil.joins_after_s:
                await sleep(self.pupil.joins_after_s)
            if await self._sign_in() and await self._send("open", "POST", "/start") == "ok":
                await self._work()
        except Exception as e:
            # One pupil's mistake must not end the lesson for the class.
            self._error(f"stopped by {_failure(e)}")
        finally:
            if self.client is not None:
                await self.client.aclose()

    async def _work(self) -> None:
        plan = self.pupil.persona.plan
        # Signing out and back in comes half way through their plan.
        back_at = max(1, min(len(plan), self.lesson.max_turns) // 2)
        for turn in range(self.lesson.max_turns):
            if self.stopped or self.view.get("completed"):
                return
            await self._think()
            if self.pupil.signs_back_in and turn == back_at:
                await self._sign_back_in()
                if self.stopped:
                    return
                await self._think()
            await self._take(next_beat(self.pupil, turn, self.state, self.last_call))

    async def _take(self, move: Beat) -> None:
        """Makes one move, where a pupil would make it."""
        kind = move.kind
        if kind == "ask_teacher":
            await self._send(kind, "POST", "/request-teacher")
        elif kind == "leave":
            here = self.view["step_index"]
            if await self._send(kind, "POST", "/move", {"leave": here}) == "ok":
                self.left = here
        elif kind == "come_back":
            if self.left is None:
                self._error("no part was left for later to come back to", kind)
            else:
                await self._send(kind, "POST", "/move", {"to": self.left})
        elif kind == "jump":
            await self._jump()
        elif kind == "helped":
            if self.last_line is None:
                self._error("no reply from the tutor to tap", kind)
            else:
                await self._send(kind, "POST", f"/lines/{self.last_line}/helped", {"helped": True})
        elif kind.startswith("button:"):
            intent = kind.removeprefix("button:")
            await self._send(kind, "POST", "/messages", {"text": "", "intent": intent})
        elif kind in CANNED:
            await self._say(kind, CANNED[kind])
        elif kind == "double_tap":
            text, fallback = await self._words(beat(DOUBLE_TAP_WRITES))
            await self._say(kind, text, fallback, taps=2)
        elif kind == "copied_wrong" and (copied := self._copied()) is not None:
            await self._say(kind, copied)
        else:
            # A written move. A copier with nothing to copy gives a wrong answer of their own.
            written = beat("wrong") if kind == "copied_wrong" else move
            if written.kind not in BEATS:
                # A move the driver makes itself with no way above, or a made-up one: a mistake
                # in the driver or the plan, never something to hand the writer.
                raise ValueError(
                    f"There is no way to make a {kind!r} move: it is not a written move, and "
                    "the driver has no way of its own to make it."
                )
            text, fallback = await self._words(written)
            await self._say(written.kind, text, fallback)

    async def _jump(self) -> None:
        """To step JUMP_TO, one written move there, and back to the step they were on."""
        before = self.view["step_index"]
        if await self._send("jump", "POST", "/move", {"to": JUMP_TO}) != "ok":
            return
        await self._think()
        move = beat(JUMP_WRITES)
        text, fallback = await self._words(move)
        await self._say(move.kind, text, fallback)
        if self.stopped:
            return
        await self._think()
        await self._send("jump", "POST", "/move", {"to": before})

    def _copied(self) -> str | None:
        """The words of the latest wrong answer another pupil sent in this lesson."""
        for sent in reversed(self.log.sent):
            if sent.beat in WRONG and sent.pupil != self.seat.pseudonym and sent.text:
                return sent.text
        return None

    async def _words(self, move: Beat) -> tuple[str, bool]:
        """The writer's line for this move, from the last lines on the pupil's screen. A line
        the writer could not write, so it gave the move's stand-in line, is noted in the events
        with the reason the writer kept (FELL_BACK)."""
        lines = [
            {"who": line["who"], "text": line["text"]}
            for line in self.view.get("lines", [])
            if line["who"] in ("student", "agent")
        ]
        writer = self.lesson.writer
        text, fallback = await writer.write(self.pupil.persona, move, lines[-LINES_FOR_WRITER:])
        if fallback:
            # Read straight after the write, with nothing awaited in between, so the reason is
            # this write's even when the pupils share one writer.
            self.log.events.append(
                {
                    "what": FELL_BACK,
                    "pupil": self.seat.pseudonym,
                    "beat": move.kind,
                    "why": getattr(writer, "last_failure", None),
                    "at": datetime.now(UTC).isoformat(),
                }
            )
        return text, fallback

    async def _say(self, move: str, text: str, fallback: bool = False, taps: int = 1) -> str:
        return await self._send(
            move, "POST", "/messages", {"text": text}, text=text, fallback=fallback, taps=taps
        )

    async def _think(self) -> None:
        await sleep(self.rng.uniform(*self.lesson.think))

    async def _sign_in(self) -> bool:
        """Signs the pupil in with their join code, in a new browser, waiting out the same
        refusals as any request (noted under the move "sign_in")."""
        self.client = self.lesson.browser()
        _, answer, times = await self._ask(
            SIGN_IN, "POST", "/api/auth/join", {"code": self.seat.code}
        )
        if answer.outcome == "ok":
            return True
        self._error(f"signing in with their code answered {answer.said()}{_times(times)}")
        self.stopped = True
        return False

    async def _sign_back_in(self) -> None:
        """Drops the browser, cookie and all, signs in again with the same code in a new one,
        and reads the lesson as their page does."""
        await self.client.aclose()
        self.client = None
        if await self._sign_in():
            await self._send("signed_back_in", "GET", "")

    async def _send(
        self,
        move: str,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        text: str = "",
        fallback: bool = False,
        taps: int = 1,
    ) -> str:
        """Makes a request in the lesson, `taps` of them at once, and waits out the refusals
        worth waiting out, noting each. What it ended with is logged as sent, and so is each tap
        of a double tap: the platform should answer one and hold the other back (429), which is
        not sent again. Says how it went: "ok", or why not."""
        answers, decider, times = await self._ask(move, method, self.lesson.path + path, body, taps)
        outcome = decider.outcome
        for answer in answers:
            self.log.sent.append(self._sent(move, text, fallback, answer))
        if outcome == "ok":
            views = [a.view for a in answers if a.view is not None]
            if views:
                await self._took(max(views, key=lambda v: len(v.get("lines", []))))
            # The other tap of a double tap: held back (429) as it should be, or else refused
            # or failed like any request.
            for answer in answers:
                if answer.outcome == "error":
                    self._error(answer.said(), move)
                elif answer.outcome not in ("ok", "rate limited"):
                    self._note(answer.outcome, move, answer)
                    self.stopped = self.stopped or answer.outcome in _STOPS
        elif outcome in _STOPS:
            self._note(outcome, move, decider)
            self.stopped = True
        else:
            self._error(decider.said() + _times(times), move)
            if outcome == "paused":
                # Still paused after LONGEST_PAUSE_S: the lesson is not coming back to them.
                self.stopped = True
        return outcome

    async def _ask(
        self, move: str, method: str, url: str, body: dict | None = None, taps: int = 1
    ) -> tuple[list[_Answer], _Answer, int]:
        """Sends the request, `taps` of them at once, until the answer is not a refusal worth
        waiting out or the waits for that refusal have run out, noting each refusal under
        `move`. Gives the answers it ended with, the one that decides how it went, and how many
        times that refusal came (0 when it was not one)."""
        refused = dict.fromkeys(_RETRIES, 0)
        while True:
            answers = await asyncio.gather(*(self._call(method, url, body) for _ in range(taps)))
            decider = min(answers, key=lambda a: _FIRST.index(a.outcome))
            outcome = decider.outcome
            if outcome not in _RETRIES:
                return answers, decider, 0
            self._note(outcome, move, decider)
            refused[outcome] += 1
            wait, most = _RETRIES[outcome]
            if refused[outcome] > most:
                return answers, decider, refused[outcome]
            await sleep(wait)

    async def _took(self, view: dict) -> None:
        """Takes in the view a reply came with: where the pupil is now and, for a steered pupil,
        the tutor's pitch call on its newest line."""
        self.view = view
        self.state.step_index = view["step_index"]
        line = _agent_line(view)
        if self.pupil.steer is not None and line is not None and line != self.last_line:
            self.last_call = await self._read_call(line)
        self.last_line = line

    async def _read_call(self, line: str) -> str | None:
        """The tutor's pitch call on its line `line`. A read that fails, or takes longer than
        READ_CALL_TIMEOUT_S, is an error, and the pupil carries on as if no call was made."""
        try:
            return await asyncio.wait_for(self.lesson.read_call(line), READ_CALL_TIMEOUT_S)
        except Exception as e:
            self._error(f"could not read the tutor's pitch call on line {line}: {_failure(e)}")
            return None

    async def _call(self, method: str, url: str, body: dict | None = None) -> _Answer:
        """One request, and the platform's answer to it."""
        at = datetime.now(UTC).isoformat()
        started = time.perf_counter()
        try:
            response = await self.client.request(method, url, json=body)
        except httpx.HTTPError as e:
            # No answer came: the request timed out, or the connection failed.
            return _Answer(0, None, type(e).__name__, time.perf_counter() - started, at)
        seconds = time.perf_counter() - started
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.is_success:
            view = data if isinstance(data, dict) else None
            return _Answer(response.status_code, view, "", seconds, at)
        detail = data.get("detail") if isinstance(data, dict) else None
        said = detail if isinstance(detail, str) else str(detail or response.text)[:300]
        return _Answer(response.status_code, None, said, seconds, at)

    def _sent(self, move: str, text: str, fallback: bool, answer: _Answer) -> Sent:
        view = answer.view or {}
        return Sent(
            pupil=self.seat.pseudonym,
            kind=self.pupil.kind,
            session_id=self.log.session_id,
            beat=move,
            text=text,
            status=answer.status,
            seconds=answer.seconds,
            agent_line_id=_agent_line(view),
            at=answer.at,
            fallback=fallback,
            step_index=view.get("step_index"),
            wrong_tries=view.get("wrong_tries"),
            lines=len(view["lines"]) if "lines" in view else None,
        )

    def _note(self, what: str, move: str, answer: _Answer) -> None:
        self.log.events.append(
            {
                "what": what,
                "pupil": self.seat.pseudonym,
                "beat": move,
                "at": answer.at,
                "detail": answer.detail,
            }
        )

    def _error(self, what: str, move: str | None = None) -> None:
        where = f"{self.seat.pseudonym}, {move}" if move else self.seat.pseudonym
        self.log.errors.append(f"{where}: {what}")


def _times(refused: int) -> str:
    """How many times a request was refused, for an error, when it was more than once."""
    return f" (refused {refused} times)" if refused > 1 else ""


def _agent_line(view: dict) -> str | None:
    """The id of the tutor's latest line on the pupil's page, if it has one."""
    ids = [line["id"] for line in view.get("lines", []) if line["who"] == "agent"]
    return str(ids[-1]) if ids else None
