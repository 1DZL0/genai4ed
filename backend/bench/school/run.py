"""The runner: the one command that runs a school day on the test copy.

    uv run python -m bench.school --part {1,2,all} [--only A|B|C] [--lessons draft|saved]
        [--saved-from DIR] [--model M] [--free] [--floor 15] [--out DIR] [--website URL]

It keeps to the guards (guard.py) before anything: the API it starts and the website it looks at
must be test ones on this machine, never the live site's 8000 or 3000. It starts the test API on
the copy database (serve.py), and always stops it. Before each paid part it reads what is left
on the key and stops, saying so, when the part would take it below the floor. Then:

- Part 1: one teacher and a class of 30 in one maths lesson, the teacher reading the class view
  every 45 s, asking who needs them after 4 minutes, dealing with every alert, reading a
  struggling pupil's conversation, pausing for a minute and adding 10 minutes; then the lesson's
  end, its summary, every outcome confirmed, each pupil reading their result, how many
  finished, and the follow-up lesson the summary offers;
- Part 2: Groups A, B and C at once, each with a teacher of its own and its lessons in order:
  A's teacher guides a pupil in their first lesson and asks the tutor to go gently with one
  before their second, B's teacher turns the review notes off before their second, and C's
  teacher deletes what is remembered after their lesson;
- the probes: privacy between Groups A and B, the research pages, and a browser look at Part 1's
  class view;
- then the records are collected, the checks run, and the report is written to the run's
  folder. Only the report's path and the counts are printed.

Every run has teachers of its own, named with the run's time, so nothing carries over from an
earlier run. Every lesson's words go to the class agent (`--lessons draft`, which saves the
briefs it drafted to briefs.json), or the briefs an earlier run saved are seeded as they were
(`--lessons saved`). A crash or Ctrl-C stops the test API, and what ran is saved, with the parts
that did not run named.

Nothing printed or saved holds the database URL or the key: a refusal or a crash is said in its
own words, never with a traceback of its locals.
"""

import argparse
import asyncio
import json
import math
import shutil
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from time import monotonic
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.brief import LessonBrief
from app.models import User
from bench.pupils import CannedWriter, PupilWriter, cheat_sheet
from bench.school import cast
from bench.school.checks import (
    ACKNOWLEDGED,
    ASKED,
    CONFIRMED,
    EXTENDED,
    FOLLOW_UP,
    GO_GENTLY,
    GUIDED,
    READ_CONVERSATION,
    RESULT_SEEN,
    SUMMARY,
    TEACHER_PAUSED,
    TEACHER_RESUMED,
    run_all,
)
from bench.school.checks_extra import MEMORY_AFTER_FORGET, PREVIEWED, UNIT_SET
from bench.school.collect import LessonFacts, collect, note_lines_of, pitch_call_of
from bench.school.driver import PUPILS_STOPPED, TIMEOUT, LessonLog, Writer, run_lesson
from bench.school.guard import (
    FLOOR,
    Refused,
    affordable,
    check_target,
    copy_database_url,
    remaining,
)
from bench.school.lessons import (
    GROUP_LESSONS,
    PART_ONE,
    TEXTS,
    LessonPlan,
    load_brief,
    load_briefs,
    make_files,
    save_briefs,
    seed,
)
from bench.school.probes import privacy, research, run_look
from bench.school.report import COUNTED_WHEN_FREE, save
from bench.school.serve import ServerDidNotStart, test_server
from bench.school.teacher import LESSONS, MEMORY, NotDone, Seat, Teacher

# Each part's rough cost in dollars, held to the floor before it runs.
ESTIMATES = {"1": 8.0, "2": 9.0}
# The pupils' writer: the bench's pupil model, cheaper than the tutor's (the spec's choice).
PUPIL_MODEL = "anthropic/claude-sonnet-5.5"
# The copy website the look reads, built against the test API.
WEBSITE = "http://127.0.0.1:3002"
REPO = Path(__file__).resolve().parents[3]
# How long a pupil thinks before each move, in seconds, at the least and the most.
THINK = (10.0, 60.0)

# The classes: Part 1's of 30, and each group's of 6, with their labels.
FULL_CLASS_LABEL, FULL_CLASS_SIZE = "9S", 30
GROUP_LABELS = {"A": "8A", "B": "11B", "C": "7C"}
GROUP_SIZE = 6

# Part 1's teacher, in seconds from the lesson's start: the class view read every 45 s, and the
# question to the class agent after 4 minutes, then the pause, held this long, and the minutes
# added. And the unit Part 1's lesson is filed in.
VIEW_EVERY_S = 45
ASK_AFTER_S = 240
PAUSE_S = 60
EXTRA_MINUTES = 10
UNIT = "Equations"
WHO_NEEDS_ME = "Who needs me right now?"
HOW_MANY_FINISHED = "How many of them finished?"
# Part 2: Group A's teacher guides a pupil still working 3 minutes into their first lesson, and
# asks the tutor to go gently with a pupil before their second.
GUIDE_AFTER_S = 180
GUIDANCE = "Give them a hint about the first step."
GO_GENTLY_WORDS = "Go gently with {pupil} this week, keep your questions short for them."
# What the class board says of a pupil who is still at work in the lesson.
STILL_WORKING = ("needs_you", "struggling", "working")
# How often the teacher looks whether the pupils have stopped, in seconds.
POLL_S = 1.0
# After the platform gave no answer to a lesson's drafting, how long the teacher waits before
# the next lesson's, so that a late reply is not taken for the next one.
NO_ANSWER = "got no answer from the platform"
NO_ANSWER_WAIT_S = 30
# Why a part did not run.
NOT_ENOUGH = "not enough left on the key"
# What the teacher's log says when a read of the class view failed and they carried on.
VIEW_NOT_READ = "class view not read"
# After the class agent could not write the summary (503), how long the teacher waits before
# pressing Write the summary once more.
SUMMARY_RETRY_S = 15
UNAVAILABLE = 503
# The run's own logs, written before the records are read, so that nothing is lost if that
# fails.
RAW = "raw.json"

# Every lesson of the day, in the day's order, for the logs and the facts.
ORDER = [PART_ONE.key, *(plan.key for plans in GROUP_LESSONS.values() for plan in plans)]

WriterFactory = Callable[[dict, str], Writer]


@dataclass
class Venue:
    """Where the day runs: the test API's address, a factory for its browsers (each a client with
    a cookie jar of its own and a long read timeout, as the class agent's replies take a minute or
    more) and one for short sessions on the copy database."""

    base_url: str
    client_factory: Callable[[], httpx.AsyncClient]
    session_factory: Callable[[], AsyncSession]


@dataclass
class Day:
    """What the run has done so far, kept as it goes so that a crash loses none of it: the
    lessons' logs and facts, the class agent's replies, the probes, the problems the runner met,
    Group C's memory lines captured before their teacher deleted them, the briefs drafted, and
    the teachers (by part or group) and their pupils' seats. `stack` closes the teachers'
    browsers at the end."""

    folder: Path
    stamp: str
    texts: Path
    logs: list[LessonLog] = field(default_factory=list)
    facts: list[LessonFacts] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    probes: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    captured: dict[str, list[dict]] = field(default_factory=dict)
    briefs: dict[str, dict] = field(default_factory=dict)
    teachers: dict[str, Teacher] = field(default_factory=dict)
    seats: dict[str, list[Seat]] = field(default_factory=dict)
    stack: AsyncExitStack = field(default_factory=AsyncExitStack)

    def lessons_run(self) -> int:
        return sum(1 for log in self.logs if log.session_id)

    def of(self, keys: list[str]) -> tuple[list[LessonLog], list[LessonFacts], list[str]]:
        """The logs and facts of these lessons, and the class agent's replies so far."""
        return (
            [log for log in self.logs if log.key in keys],
            [facts for facts in self.facts if facts.key in keys],
            self.replies,
        )

    async def teacher(self, venue: Venue, name: str, role: str) -> Teacher:
        """A new teacher of the run, signed in in a browser of their own, letting the tutor
        pitch each step for the pupil in front of it."""
        client = await self.stack.enter_async_context(venue.client_factory())
        teacher = Teacher(client, name)
        await teacher.sign_in()
        await teacher.let_adapt()
        self.teachers[role] = teacher
        return teacher


# ---------- the command ----------


def parse(argv: list[str] | None) -> argparse.Namespace:
    """The command's arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m bench.school", description="Runs a school day on the test copy."
    )
    parser.add_argument("--part", choices=("1", "2", "all"), required=True)
    parser.add_argument("--only", choices=tuple(GROUP_LESSONS), help="Part 2's one group")
    parser.add_argument("--lessons", choices=("draft", "saved"), default="draft")
    parser.add_argument("--saved-from", type=Path, help="the folder of an earlier run")
    parser.add_argument("--model", help="the model the test API runs with")
    parser.add_argument("--free", action="store_true", help="scripted models, no money")
    parser.add_argument("--floor", type=float, default=FLOOR)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--website", default=WEBSITE)
    opts = parser.parse_args(argv)
    if opts.lessons == "saved" and opts.saved_from is None:
        parser.error("--lessons saved needs --saved-from, the folder of an earlier run")
    return opts


async def main(argv: list[str] | None = None) -> int:
    """Runs the day the arguments ask for: 0 when no check failed, 1 when one did, 2 when the run
    could not start or stopped part way. A refusal or a failed start is printed in its own
    words and nothing else."""
    opts = parse(argv)
    if opts.out is None:
        folder = _default_folder()
        if folder.is_dir() and any(folder.iterdir()):
            # Never write over an earlier run unless --out names its folder.
            print(f"{folder} already holds an earlier run. Name a folder with --out.")
            return 2
        opts.out = folder
    folder = opts.out
    try:
        check_target(opts.website)
        if opts.lessons == "saved" and not (opts.saved_from / "briefs.json").is_file():
            print(f"There is no briefs.json in {opts.saved_from}, so no lesson can be seeded.")
            return 2
        with test_server(model=opts.model, free=opts.free, folder=folder) as base_url:
            engine = create_async_engine(copy_database_url())
            try:
                venue = Venue(
                    base_url,
                    lambda: httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT),
                    async_sessionmaker(engine, expire_on_commit=False),
                )
                return await run_day(venue, opts)
            finally:
                await engine.dispose()
    except (Refused, ServerDidNotStart) as stopped:
        # Only the message: the database URL and the key sit in the frames' locals.
        print(str(stopped))
        return 2


async def run_day(
    venue: Venue,
    opts: argparse.Namespace,
    *,
    writer_factory: WriterFactory | None = None,
    think: tuple[float, float] = THINK,
    size: int | None = None,
) -> int:
    """The day itself, at `venue`: the parts asked for, each after the money check, then the
    probes, the records, the checks and the report. `size`, when given, makes every class that
    many pupils (the first of the cast). Returns as `main` does."""
    folder = Path(opts.out) if opts.out else _default_folder()
    folder.mkdir(parents=True, exist_ok=True)
    texts = folder / "texts"
    shutil.copytree(TEXTS, texts, dirs_exist_ok=True)
    make_files(texts)
    saved = load_briefs(opts.saved_from / "briefs.json") if opts.lessons == "saved" else None
    writers = writer_factory or _writers(opts.free)
    day = Day(folder=folder, stamp=_stamp(), texts=texts)
    parts = ["1", "2"] if opts.part == "all" else [opts.part]
    parts_run: list[str] = []
    not_run: dict[str, str] = {}
    cost_by_part: dict[str, float | None] = {}
    first = last = None
    crash = ""
    interrupted = False

    async with day.stack:
        for index, part in enumerate(parts):
            later = parts[index + 1 :]
            before = None
            if not opts.free:
                before, unread = await _left()
                if before is None:
                    why = f"what is left on the key could not be read: {unread}"
                    print(f"Part {part} was not run, as {why}")
                    not_run.update(dict.fromkeys([part, *later], why))
                    break
                first = before if first is None else first
                last = before
                needed = _estimate(part, cost_by_part)
                if not affordable(needed, before, opts.floor):
                    print(
                        f"Not enough left on the key for Part {part}: ${before:.2f} left, about "
                        f"${needed:.2f} needed, floor ${opts.floor:.2f}."
                    )
                    not_run.update(dict.fromkeys([part, *later], NOT_ENOUGH))
                    break
            parts_run.append(part)
            ran_before = day.lessons_run()
            try:
                if part == "1":
                    await run_part_one(
                        venue,
                        lessons=opts.lessons,
                        saved=saved,
                        writer_factory=writers,
                        think=think,
                        day=day,
                        size=size,
                    )
                else:
                    await run_part_two(
                        venue,
                        only=opts.only,
                        lessons=opts.lessons,
                        saved=saved,
                        writer_factory=writers,
                        think=think,
                        day=day,
                        size=size,
                    )
            except (Exception, asyncio.CancelledError, KeyboardInterrupt) as e:
                crash = _failure(e)
                interrupted = not isinstance(e, Exception)
                day.problems.append(f"The run stopped in Part {part}: {crash}")
                if day.lessons_run() == ran_before:
                    not_run[part] = f"stopped partway: {crash}"
                not_run.update(dict.fromkeys(later, f"not run, as the run stopped in Part {part}"))
            if not opts.free:
                after, _ = await _left()
                cost_by_part[part] = before - after if after is not None else None
                last = after
            if crash:
                break

        # What ran is probed even after a part failed; not after Ctrl-C, which means stop.
        if day.lessons_run() and not interrupted:
            try:
                await _probe(venue, day, opts.website)
            except (Exception, asyncio.CancelledError, KeyboardInterrupt) as e:
                failure = _failure(e)
                crash = crash or failure
                day.problems.append(f"The run stopped during the probes: {failure}")

    return await _finish(venue, day, opts, parts_run, not_run, cost_by_part, first, last, crash)


async def _finish(
    venue: Venue,
    day: Day,
    opts: argparse.Namespace,
    parts_run: list[str],
    not_run: dict[str, str],
    cost_by_part: dict[str, float | None],
    first: float | None,
    last: float | None,
    crash: str,
) -> int:
    """Collects the records, runs the checks and saves the report; prints its path and the
    counts."""
    order = {key: n for n, key in enumerate(ORDER)}
    day.logs.sort(key=lambda log: order.get(log.key, len(order)))
    day.facts.sort(key=lambda facts: order.get(facts.key, len(order)))
    _write_raw(day)
    try:
        async with venue.session_factory() as db:
            data = await collect(
                db,
                day.logs,
                day.facts,
                day.replies,
                extra_events=day.probes,
                captured_note_lines=day.captured,
            )
    except Exception as e:
        print(
            f"The records could not be read, so no report was written: {_failure(e)}. "
            f"The run's own logs are in {day.folder / RAW}."
        )
        return 2
    data.errors.extend(day.problems)
    results = run_all(data)
    if opts.free:
        cost: float | None = 0.0
        cost_by_part = {}
    else:
        cost = first - last if first is not None and last is not None else None
    meta = {
        "date": date.today().isoformat(),
        "parts_run": parts_run,
        "parts_not_run": not_run,
        "models": {
            "tutor and class agent": ", ".join(sorted({t.model for t in data.turns}))
            or opts.model
            or "the test API's setting",
            "pupils": "canned lines" if opts.free else PUPIL_MODEL,
        },
        "prompt_versions": sorted({t.prompt_version for t in data.turns}),
        "cost": cost,
        "cost_by_part": cost_by_part,
        "free": bool(opts.free),
        "lessons": opts.lessons,
        "floor": opts.floor,
    }
    page = save(day.folder, results, data, meta)
    counted = [r for r in results if not opts.free or r.code in COUNTED_WHEN_FREE]
    failed = sum(r.outcome == "fail" for r in counted)
    passed = sum(r.outcome == "pass" for r in counted)
    print(page)
    print(
        f"{passed} passed, {failed} failed, {len(counted) - passed - failed} did not come up"
        + (" (a free run counts the platform's own workings only)" if opts.free else "")
    )
    if crash:
        return 2
    return 1 if failed else 0


# ---------- Part 1 ----------


async def run_part_one(
    venue: Venue,
    *,
    lessons: str,
    saved: dict | None,
    writer_factory: WriterFactory,
    think: tuple[float, float],
    day: Day,
    size: int | None = None,
) -> tuple[list[LessonLog], list[LessonFacts], list[str]]:
    """The full class: one teacher, a class of 30 (or `size`), and Part 1's lesson, with the
    teacher at work beside the pupils and the lesson's end, summary, outcomes, results and
    follow-up after it."""
    teacher = await day.teacher(venue, f"sd-maths-{day.stamp}", "1")
    class_id, seats = await teacher.make_class(FULL_CLASS_LABEL, size or FULL_CLASS_SIZE)
    day.seats["1"] = seats
    pupils = cast.part_one()[: len(seats)]
    by_name = {p.persona.name: seat for p, seat in zip(pupils, seats, strict=True)}
    log = _new_log(day, PART_ONE.key)

    async def preview_and_file(lesson_id: str) -> None:
        shown, thread = await _do(
            log.events,
            PREVIEWED,
            lambda: teacher.preview(lesson_id),
            lesson=PART_ONE.key,
            card=None,
        )
        shown["card"] = (thread or {}).get("showing")
        filed, thread = await _do(
            log.events,
            UNIT_SET,
            lambda: teacher.set_unit(lesson_id, UNIT),
            lesson=PART_ONE.key,
            text=UNIT,
            unit=None,
        )
        filed["unit"] = ((thread or {}).get("showing") or {}).get("unit")

    session_id, card = await _teach(
        venue,
        day,
        teacher,
        PART_ONE,
        log,
        class_id=class_id,
        pupils=pupils,
        seats=by_name,
        lessons=lessons,
        saved=saved,
        writer_factory=writer_factory,
        think=think,
        before_run=preview_and_file,
        script=lambda sid: _part_one_script(teacher, sid, pupils, by_name, day),
    )
    if session_id:
        await _ask(teacher, log.events, day.replies, HOW_MANY_FINISHED, None)
        await _results_seen(venue, session_id, seats, log)
        await _follow_up(teacher, session_id, card, log)
    return day.of([PART_ONE.key])


def _part_one_script(
    teacher: Teacher, session_id: str, pupils: list[cast.Pupil], seats: dict[str, Seat], day: Day
) -> Callable[[LessonLog], Awaitable[None]]:
    """Part 1's teacher while the pupils work: the class view every 45 s (timed, for S3); after
    4 minutes "Who needs me right now?", every open alert dealt with, one struggling pupil's
    conversation read, a minute's pause and 10 minutes added. Between steps they look whether
    the pupils have stopped, and finish when they have."""

    async def script(log: LessonLog) -> None:
        started = monotonic()
        next_view = 0.0
        last_card: dict = {}

        async def board() -> dict:
            """The class board now, or, when it could not be read, the last one read."""
            nonlocal next_view, last_card
            next_view = monotonic() + VIEW_EVERY_S
            card = await _read_board(teacher, session_id, log, timed=True)
            last_card = last_card if card is None else card
            return last_card

        async def until(seconds: float) -> bool:
            """Reads the class view every 45 s until `seconds` from the start; False when the
            pupils stop first."""
            while not _stopped(log):
                if monotonic() >= next_view:
                    await board()
                if monotonic() - started >= seconds:
                    return True
                await asyncio.sleep(POLL_S)
            return False

        await board()
        if not await until(ASK_AFTER_S):
            return
        await _ask(teacher, log.events, day.replies, WHO_NEEDS_ME, session_id)
        card = await board()
        for alert in card.get("alerts") or []:
            await _do(
                log.events,
                ACKNOWLEDGED,
                lambda alert=alert: teacher.act("acknowledge", exception_id=alert["id"]),
                session_id=session_id,
                exception_id=str(alert["id"]),
            )
        if _stopped(log):
            return
        reading = _struggling(card, pupils, seats)
        if reading is not None:
            student_id, pupil = reading
            await _do(
                log.events,
                READ_CONVERSATION,
                lambda: teacher.act(
                    "show_transcript", session_id=session_id, student_id=student_id
                ),
                session_id=session_id,
                pupil=pupil,
            )
        if _stopped(log):
            return
        paused, _ = await _do(
            log.events,
            TEACHER_PAUSED,
            lambda: teacher.act("pause", session_id=session_id),
            session_id=session_id,
            done=None,
        )
        if _went(paused):
            paused["done"] = _now()
            # A pause the teacher began is always ended, whatever the pupils do meanwhile.
            await asyncio.sleep(PAUSE_S)
            resumed, _ = await _do(
                log.events,
                TEACHER_RESUMED,
                lambda: teacher.act("resume", session_id=session_id),
                session_id=session_id,
                done=None,
            )
            if _went(resumed):
                resumed["done"] = _now()
        if _stopped(log):
            return
        card = await board()
        extended, thread = await _do(
            log.events,
            EXTENDED,
            lambda: teacher.act("extend", session_id=session_id, minutes=EXTRA_MINUTES),
            session_id=session_id,
            minutes=EXTRA_MINUTES,
            closes_before=card.get("closes_at"),
            closes_after=None,
        )
        extended["closes_after"] = ((thread or {}).get("showing") or {}).get("closes_at")
        await until(math.inf)

    return script


def _struggling(
    card: dict, pupils: list[cast.Pupil], seats: dict[str, Seat]
) -> tuple[str, str] | None:
    """A struggling pupil to read the conversation of, as their student id and pseudonym: one
    the class board calls struggling, else one who needs the teacher, else the cast's first
    struggling pupil."""
    on_board = card.get("students") or []
    for state in ("struggling", "needs_you"):
        for student in on_board:
            if student.get("state") == state:
                return str(student["student_id"]), student["pseudonym"]
    for pupil in pupils:
        if pupil.kind == "struggling":
            seat = seats[pupil.persona.name]
            return seat.student_id, seat.pseudonym
    return None


async def _results_seen(venue: Venue, session_id: str, seats: list[Seat], log: LessonLog) -> None:
    """Each pupil signs in again with their code and reads their page of the lesson, which
    should show the result the teacher confirmed (C9)."""
    for seat in seats:
        event = {
            "what": RESULT_SEEN,
            "at": _now(),
            "status": 0,
            "session_id": session_id,
            "pupil": seat.pseudonym,
            "result": None,
        }
        log.events.append(event)
        try:
            async with venue.client_factory() as pupil:
                signed = await pupil.post("/api/auth/join", json={"code": seat.code})
                if not signed.is_success:
                    event["status"] = signed.status_code
                    continue
                page = await pupil.get(f"/api/learn/{session_id}")
        except httpx.HTTPError:
            continue
        event["status"] = page.status_code
        if page.is_success:
            event["result"] = page.json().get("result")


async def _follow_up(teacher: Teacher, session_id: str, card: dict, log: LessonLog) -> None:
    """Takes up the follow-up lesson the summary offers, on the first thing it says a pupil
    should develop, and logs whether a draft came of it. Nothing offered, nothing logged."""
    point = next(
        (
            line.strip()
            for outcome in card.get("outcomes") or []
            for line in (outcome.get("suggested") or {}).get("develop") or []
            if isinstance(line, str) and line.strip()
        ),
        None,
    )
    if point is None:
        return
    try:
        before = await _drafts(teacher)
    except httpx.HTTPError as e:
        log.errors.append(f"teacher: the lessons could not be read before the follow-up: {e}")
        return
    event, thread = await _do(
        log.events,
        FOLLOW_UP,
        lambda: teacher.act("follow_up", text=point),
        session_id=session_id,
        text=point,
        drafted=False,
        lesson_id=None,
        reason="",
    )
    if thread is None:
        event["reason"] = "The platform did not take the follow-up."
        return
    try:
        new = sorted((await _drafts(teacher)) - before)
    except httpx.HTTPError:
        event["reason"] = "The lessons could not be read after the follow-up."
        return
    if new:
        event["drafted"], event["lesson_id"] = True, new[0]
    else:
        event["reason"] = "The teacher's lessons show no new draft after the follow-up."


async def _drafts(teacher: Teacher) -> set[str]:
    """The ids of the teacher's draft lessons with steps in them, from their list of lessons."""
    reply = await teacher.client.get(LESSONS)
    reply.raise_for_status()
    return {
        x["lesson_id"] for x in reply.json()["lessons"] if x["steps"] and x["status"] == "draft"
    }


# ---------- Part 2 ----------


async def run_part_two(
    venue: Venue,
    *,
    only: str | None,
    lessons: str,
    saved: dict | None,
    writer_factory: WriterFactory,
    think: tuple[float, float],
    day: Day,
    size: int | None = None,
) -> tuple[list[LessonLog], list[LessonFacts], list[str]]:
    """Groups A, B and C at once (or `only` one), each with a teacher of its own and its
    lessons in order. A group that fails does not stop the others; once all have finished, the
    first failure is raised and any others are noted."""
    groups = [only] if only else list(GROUP_LESSONS)
    ended = await asyncio.gather(
        *(
            _group(
                venue,
                day,
                name,
                lessons=lessons,
                saved=saved,
                writer_factory=writer_factory,
                think=think,
                size=size,
            )
            for name in groups
        ),
        return_exceptions=True,
    )
    failures = [e for e in ended if isinstance(e, BaseException)]
    for other in failures[1:]:
        day.problems.append(f"Part 2 also stopped for: {_failure(other)}")
    if failures:
        raise failures[0]
    return day.of([plan.key for name in groups for plan in GROUP_LESSONS[name]])


async def _group(
    venue: Venue,
    day: Day,
    name: str,
    *,
    lessons: str,
    saved: dict | None,
    writer_factory: WriterFactory,
    think: tuple[float, float],
    size: int | None,
) -> None:
    teacher = await day.teacher(venue, f"sd-{name.lower()}-{day.stamp}", name)
    class_id, seats = await teacher.make_class(GROUP_LABELS[name], size or GROUP_SIZE)
    day.seats[name] = seats
    ran = False
    for index, plan in enumerate(GROUP_LESSONS[name]):
        pupils = cast.group(name, plan.subject)[: len(seats)]
        by_name = {p.persona.name: seat for p, seat in zip(pupils, seats, strict=True)}
        log = _new_log(day, plan.key)
        if name == "A" and index == 1:
            target = next((p for p in pupils if p.note_target), None)
            if target is not None:
                pupil = by_name[target.persona.name].pseudonym
                words = GO_GENTLY_WORDS.format(pupil=pupil)
                asked = await _ask(teacher, log.events, day.replies, words, None)
                status = asked["status"]
                log.events.append(
                    {"what": GO_GENTLY, "at": asked["at"], "status": status, "pupil": pupil}
                )
        if name == "B" and index == 1:
            try:
                await teacher.settings(written_lines=False)
            except (NotDone, httpx.HTTPError) as e:
                log.errors.append(f"teacher: the review notes could not be turned off: {e}")
        script = None
        if name == "A" and index == 0:

            def script(sid: str, pupils=pupils, by_name=by_name):
                return _guide_script(teacher, sid, pupils, by_name)

        session_id, _ = await _teach(
            venue,
            day,
            teacher,
            plan,
            log,
            class_id=class_id,
            pupils=pupils,
            seats=by_name,
            lessons=lessons,
            saved=saved,
            writer_factory=writer_factory,
            think=think,
            script=script,
        )
        ran = ran or bool(session_id)
    if name == "C" and ran:
        await _forget(venue, day, teacher, seats)


def _guide_script(
    teacher: Teacher, session_id: str, pupils: list[cast.Pupil], seats: dict[str, Seat]
) -> Callable[[LessonLog], Awaitable[None]]:
    """Group A's teacher in their first lesson: 3 minutes in, guidance for the guide target, or,
    when they have finished, the next pupil of the cast still working."""

    async def script(log: LessonLog) -> None:
        if not await _wait(log, GUIDE_AFTER_S):
            return
        card = await _read_board(teacher, session_id, log, timed=False)
        order = sorted(pupils, key=lambda p: not p.guide_target)
        if card is None:
            # Who is still working is not known: the guide target, as planned.
            seat = seats[order[0].persona.name]
        else:
            working = {
                s["pseudonym"]
                for s in card.get("students") or []
                if s.get("state") in STILL_WORKING
            }
            seat = next(
                (
                    seats[p.persona.name]
                    for p in order
                    if seats[p.persona.name].pseudonym in working
                ),
                None,
            )
        if seat is None:
            return
        await _do(
            log.events,
            GUIDED,
            lambda: teacher.act(
                "guide", session_id=session_id, student_id=seat.student_id, text=GUIDANCE
            ),
            session_id=session_id,
            pupil=seat.pseudonym,
            text=GUIDANCE,
        )

    return script


async def _forget(venue: Venue, day: Day, teacher: Teacher, seats: list[Seat]) -> None:
    """Group C's teacher deletes what is remembered of their pupils, after the group's memory
    lines are captured for M3; then reads how many pupils still have something remembered
    (M5), None when it can't be read."""
    async with venue.session_factory() as db:
        day.captured.update(await note_lines_of(db, [seat.pseudonym for seat in seats]))
    try:
        await teacher.forget_all()
    except (NotDone, httpx.HTTPError) as e:
        day.problems.append(f"Group C's teacher could not delete what is remembered: {e}")
    students = None
    try:
        reply = await teacher.client.get(MEMORY)
        if reply.is_success:
            found = reply.json().get("students")
            students = found if isinstance(found, int) and not isinstance(found, bool) else None
    except (httpx.HTTPError, ValueError):
        students = None
    day.probes.append({"probe": MEMORY_AFTER_FORGET, "students": students})


# ---------- one lesson ----------


def _new_log(day: Day, key: str) -> LessonLog:
    """An empty log for the lesson, kept by the day at once, so that what the teacher does
    before it runs, and what ran if it stops part way, is never lost."""
    log = LessonLog(key=key, session_id="", sent=[], events=[], view_seconds=[], errors=[], cast={})
    day.logs.append(log)
    return log


async def _teach(
    venue: Venue,
    day: Day,
    teacher: Teacher,
    plan: LessonPlan,
    log: LessonLog,
    *,
    class_id: str,
    pupils: list[cast.Pupil],
    seats: dict[str, Seat],
    lessons: str,
    saved: dict | None,
    writer_factory: WriterFactory,
    think: tuple[float, float],
    before_run: Callable[[str], Awaitable[None]] | None = None,
    script: Callable[[str], Callable[[LessonLog], Awaitable[None]]] | None = None,
) -> tuple[str, dict]:
    """One lesson, from the teacher's words (or a saved brief) to its confirmed outcomes: its
    session and the outcomes card, or ("", {}) when it did not run. A lesson that was not
    drafted, could not be approved or seeded, or would not start is recorded, and the day goes
    on with the rest."""
    facts = LessonFacts(
        key=plan.key,
        session_id="",
        subject=plan.subject,
        age=plan.age,
        steps=0,
        rules={},
        brief={},
        teacher=teacher.name,
        drafted=None,
    )
    day.facts.append(facts)
    if lessons == "saved":
        lesson_id = await _seeded(venue, teacher, plan, saved or {}, log)
    else:
        lesson_id = await _drafted(venue, day, teacher, plan, facts, log)
    if lesson_id is None:
        return "", {}
    _fill(facts, await _brief(venue, lesson_id))
    if before_run is not None:
        await before_run(lesson_id)
    try:
        session_id = await teacher.run(lesson_id, class_id)
    except (NotDone, httpx.HTTPError) as e:
        log.errors.append(f"teacher: the lesson could not be started: {_failure(e)}")
        return "", {}
    facts.session_id = log.session_id = session_id

    async def read_call(line: str) -> str | None:
        # A short session per read: one session can't run reads side by side.
        async with venue.session_factory() as db:
            return await pitch_call_of(db, line)

    await run_lesson(
        key=plan.key,
        base_url=venue.base_url,
        session_id=session_id,
        seats=seats,
        pupils=pupils,
        writer=writer_factory(facts.brief, f"a {plan.age} year old pupil"),
        read_call=read_call,
        think=think,
        teacher_script=script(session_id) if script is not None else None,
        client_factory=venue.client_factory,
        log=log,
    )
    return session_id, await _close(teacher, session_id, log, day.replies)


async def _drafted(
    venue: Venue, day: Day, teacher: Teacher, plan: LessonPlan, facts: LessonFacts, log: LessonLog
) -> str | None:
    """The lesson drafted from the teacher's words and approved: its id, or None when it was not
    drafted or could not be approved. The drafting is kept in the facts (C1), the uploads in the
    log (C12), and the approved brief in briefs.json."""
    uploaded = len(teacher.events)
    drafted = await teacher.draft(plan, day.texts)
    log.events.extend(teacher.events[uploaded:])
    facts.drafted = drafted
    if NO_ANSWER in drafted.reason:
        # A reply that comes late must not be taken for the next lesson's draft.
        await asyncio.sleep(NO_ANSWER_WAIT_S)
    if drafted.lesson_id is None:
        return None
    try:
        await teacher.approve(drafted.lesson_id)
    except (NotDone, httpx.HTTPError) as e:
        _fill(facts, await _brief(venue, drafted.lesson_id))
        log.errors.append(f"teacher: the drafted lesson could not be approved: {_failure(e)}")
        return None
    day.briefs[plan.key] = await _brief(venue, drafted.lesson_id)
    save_briefs(day.folder / "briefs.json", day.briefs)
    return drafted.lesson_id


async def _seeded(
    venue: Venue, teacher: Teacher, plan: LessonPlan, saved: dict, log: LessonLog
) -> str | None:
    """The lesson seeded from the brief an earlier run saved, as the teacher's own approved
    lesson (so it is not approved again): its id, or None when there is no brief for it or the
    platform would not approve it."""
    brief = saved.get(plan.key)
    if brief is None:
        log.errors.append(f"teacher: the saved lessons have none for {plan.key}")
        return None
    async with venue.session_factory() as db:
        teacher_id = await db.scalar(select(User.id).where(User.pseudonym == teacher.name))
        try:
            return str(await seed(db, teacher_id, brief))
        except ValueError as e:
            log.errors.append(f"teacher: the saved lesson for {plan.key} was refused: {e}")
            return None


async def _brief(venue: Venue, lesson_id: str) -> dict:
    async with venue.session_factory() as db:
        return await load_brief(db, lesson_id)


def _fill(facts: LessonFacts, brief: dict) -> None:
    """The lesson's facts from its brief as the platform keeps it."""
    steps = brief.get("steps")
    rules = brief.get("rules")
    facts.brief = brief
    facts.steps = len(steps) if isinstance(steps, list) else 0
    facts.rules = rules if isinstance(rules, dict) else {}


async def _close(teacher: Teacher, session_id: str, log: LessonLog, replies: list[str]) -> dict:
    """Ends the lesson, has the summary written (asked once more, after a wait, when the class
    agent could not write it) and confirms every outcome it suggests, as suggested. What the
    agent wrote about the pupils (the summary, and each outcome's keep, develop and comment
    lines) goes into `replies`, for S4. Returns the outcomes card ({} when none came)."""
    try:
        await teacher.act("end", session_id=session_id)
    except NotDone as e:
        # 409: the lesson had already closed, at its time.
        if e.status != 409:
            log.errors.append(f"teacher: ending the lesson answered {e.status}: {e.detail}")
    except httpx.HTTPError as e:
        log.errors.append(f"teacher: ending the lesson got no answer ({type(e).__name__})")
    for attempt in range(2):
        if attempt:
            await asyncio.sleep(SUMMARY_RETRY_S)
        asked, thread = await _do(
            log.events,
            SUMMARY,
            lambda: teacher.act("suggest_outcomes", session_id=session_id),
            session_id=session_id,
        )
        if asked["status"] != UNAVAILABLE:
            break
    card = (thread or {}).get("showing") or {}
    if card.get("type") != "outcomes":
        try:
            shown = await teacher.act("show_outcomes", session_id=session_id)
            card = shown.get("showing") or {}
        except (NotDone, httpx.HTTPError) as e:
            log.errors.append(f"teacher: the outcomes could not be read: {_failure(e)}")
            return {}
    replies.extend(_written_about_pupils(card))
    for outcome in card.get("outcomes") or []:
        if outcome.get("status") == "confirmed":
            continue
        await _do(
            log.events,
            CONFIRMED,
            lambda outcome=outcome: teacher.act(
                "confirm_outcome", session_id=session_id, outcome_id=outcome["id"]
            ),
            session_id=session_id,
            pupil=outcome.get("pseudonym"),
        )
    return card


# ---------- the teacher's actions, logged ----------


async def _do(
    events: list[dict], what: str, call: Callable[[], Awaitable[Any]], **fields: Any
) -> tuple[dict, Any]:
    """Makes one of the teacher's requests and logs it as checks.EVENTS says: "what", "at" (when
    it went) and "status" (0 when no answer came), with `fields`. Returns the event, for the
    caller to add what came back, and the platform's answer (None when it refused or did not
    answer). A refusal is the platform's to report, never the runner's to raise."""
    event = {"what": what, "at": _now(), "status": 0, **fields}
    events.append(event)
    try:
        answer = await call()
    except NotDone as refused:
        event["status"] = refused.status
        return event, None
    except httpx.HTTPError:
        return event, None
    event["status"] = 200
    return event, answer


async def _ask(
    teacher: Teacher, events: list[dict], replies: list[str], text: str, session_id: str | None
) -> dict:
    """Says `text` to the class agent, logged as an "asked" event with its reply, which is kept
    for S4 too. Returns the event."""
    event, said = await _do(
        events,
        ASKED,
        lambda: teacher.ask(text),
        session_id=session_id,
        question=text,
        reply="",
    )
    if said is not None:
        event["reply"] = said[0]
        if said[0]:
            replies.append(said[0])
    return event


async def _class_card(teacher: Teacher, session_id: str, log: LessonLog, *, timed: bool) -> dict:
    """The class board as the teacher's screen shows it: shown first, as the agent's own card may
    have replaced it, then read. Its time goes in the log when `timed` (Part 1 only: S3 reads
    every time as the full class's)."""
    await teacher.act("show_class", session_id=session_id)
    card, seconds = await teacher.class_view()
    if timed:
        log.view_seconds.append(seconds)
    return card


async def _read_board(
    teacher: Teacher, session_id: str, log: LessonLog, *, timed: bool
) -> dict | None:
    """The class board, as `_class_card` reads it; None when the platform refused or did not
    answer, which is logged as a VIEW_NOT_READ event and an error, so the teacher can carry
    on."""
    try:
        return await _class_card(teacher, session_id, log, timed=timed)
    except (NotDone, httpx.HTTPError) as e:
        log.events.append(
            {
                "what": VIEW_NOT_READ,
                "at": _now(),
                "status": e.status if isinstance(e, NotDone) else 0,
                "session_id": session_id,
                "detail": _failure(e),
            }
        )
        log.errors.append(f"teacher: the class view could not be read: {_failure(e)}")
        return None


def _stopped(log: LessonLog) -> bool:
    """Whether the driver says every pupil has stopped."""
    return any(e.get("what") == PUPILS_STOPPED for e in log.events)


async def _wait(log: LessonLog, seconds: float) -> bool:
    """Waits `seconds`, looking every so often whether the pupils have stopped: False when they
    have."""
    end = monotonic() + seconds
    while not _stopped(log):
        if monotonic() >= end:
            return True
        await asyncio.sleep(POLL_S)
    return False


def _went(event: dict) -> bool:
    return 200 <= event["status"] < 300


# ---------- the probes ----------


async def _probe(venue: Venue, day: Day, website: str) -> None:
    """Privacy between Groups A and B (when both ran), the research pages for the run's lessons,
    and the look at Part 1's class view (when it ran). Every probe's dict goes to the events."""
    found = _privacy_set_up(day)
    if found is not None:
        try:
            day.probes.extend(await privacy(venue.base_url, venue.client_factory, **found))
        except ValueError as e:
            day.problems.append(f"The privacy probes were set up wrongly: {e}")
    sessions = [log.session_id for log in day.logs if log.session_id]
    if sessions:
        day.probes.extend(await research(venue.base_url, venue.client_factory, sessions))
    teacher = day.teachers.get("1")
    full = next((x for x in day.logs if x.key == PART_ONE.key and x.session_id), None)
    if teacher is None or full is None:
        return
    try:
        await teacher.act("show_class", session_id=full.session_id)
    except (NotDone, httpx.HTTPError) as e:
        day.problems.append(f"Part 1's class view could not be put on screen: {_failure(e)}")
    try:
        day.probes.append(
            await run_look(website, venue.base_url, teacher.name, day.folder / "look")
        )
    except Refused as e:
        day.probes.append(
            {
                "probe": "look",
                "passed": False,
                "reachable": False,
                "research_seen": False,
                "detail": str(e),
            }
        )


def _privacy_set_up(day: Day) -> dict | None:
    """What probes.privacy needs, from Group A's first lesson that ran and Group B's: pupil A,
    whose page shows the tutor's latest line to them, a classmate who opened the same lesson,
    and a pupil of B's. None when the groups did not both run with such pupils."""
    teacher_a, teacher_b = day.teachers.get("A"), day.teachers.get("B")
    a_keys = [plan.key for plan in GROUP_LESSONS["A"]]
    b_keys = [plan.key for plan in GROUP_LESSONS["B"]]
    a_log = next((x for x in day.logs if x.key in a_keys and x.session_id), None)
    b_log = next((x for x in day.logs if x.key in b_keys and x.session_id), None)
    if teacher_a is None or teacher_b is None or a_log is None or b_log is None:
        return None
    seat_of = {seat.pseudonym: seat for seat in day.seats.get("A", []) + day.seats.get("B", [])}
    answered = [s for s in a_log.sent if s.status == 200 and s.agent_line_id]
    in_b = next((s for s in b_log.sent if s.status == 200), None)
    if not answered or in_b is None:
        return None
    pupil_a = answered[-1]
    classmate = next(
        (s.pupil for s in a_log.sent if s.status == 200 and s.pupil != pupil_a.pupil), None
    )
    if classmate is None:
        return None
    return {
        "teacher_a": teacher_a,
        "teacher_b": teacher_b,
        "session_a": a_log.session_id,
        "pupil_a": (seat_of[pupil_a.pupil], a_log.session_id),
        "pupil_b": (seat_of[in_b.pupil], b_log.session_id),
        "classmate_a": seat_of[classmate],
        "line_of_a": pupil_a.agent_line_id,
    }


# ---------- small things ----------


def _writers(free: bool) -> WriterFactory:
    """The pupils' writer for a lesson, from its brief and the pupils' voice: canned lines in a
    free run, the pupil model otherwise."""
    if free:
        return lambda brief, voice: CannedWriter()
    return lambda brief, voice: PupilWriter(
        PUPIL_MODEL, cheat_sheet(LessonBrief.model_validate(brief)), voice=voice
    )


async def _left() -> tuple[float | None, str]:
    """What is left on the key, or None and why it could not be read."""
    try:
        return await remaining(), ""
    except Refused as e:
        return None, str(e)


def _written_about_pupils(card: dict) -> list[str]:
    """The texts the class agent wrote about the pupils on the outcomes card: the summary, and
    each outcome's keep, develop and comment lines, suggested or kept."""
    texts = [card.get("summary")]
    for outcome in card.get("outcomes") or []:
        suggested = outcome.get("suggested") or {}
        develop = suggested.get("develop")
        texts += [suggested.get("keep"), suggested.get("comment"), outcome.get("comment")]
        texts += develop if isinstance(develop, list) else []
    return [t for t in texts if isinstance(t, str) and t.strip()]


def _estimate(part: str, cost_by_part: dict[str, float | None]) -> float:
    """What the part is reckoned to cost: its estimate, raised in step with what Part 1 really
    cost against its own estimate when that is known (a pricier model costs more in both), and
    never lowered."""
    spent = cost_by_part.get("1")
    if part == "1" or spent is None:
        return ESTIMATES[part]
    return ESTIMATES[part] * max(1.0, spent / ESTIMATES["1"])


def _write_raw(day: Day) -> None:
    """The run's own logs, written before the records are read: every lesson's log, the facts,
    the probes, the class agent's replies and the memory lines captured, so that a failure while
    reading the records or checking loses none of it."""
    raw = {
        "logs": [asdict(log) for log in day.logs],
        "lessons": [asdict(facts) for facts in day.facts],
        "probes": day.probes,
        "teacher_replies": day.replies,
        "captured_note_lines": day.captured,
        "problems": day.problems,
    }
    (day.folder / RAW).write_text(
        json.dumps(raw, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def _default_folder() -> Path:
    """Where a run's files go unless --out says otherwise: the repo's
    .superdesign/tmp/school-day-<YYYY-MM-DD-HHMM>/."""
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    return REPO / ".superdesign" / "tmp" / f"school-day-{stamp}"


def _stamp() -> str:
    """The run's time, as its teachers are named with it."""
    return datetime.now().strftime("%m%d%H%M")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _failure(e: BaseException) -> str:
    """An exception in plain words: its kind, and what it says when it says anything."""
    said = str(e)
    return f"{type(e).__name__}: {said}" if said else type(e).__name__
