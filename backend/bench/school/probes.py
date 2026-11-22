"""The probes a school day runs after its lessons, with no model calls:
- privacy (X1 to X3): a teacher cannot open another teacher's lessons, pupils or research pages,
  and a pupil cannot open another class's lesson, a teacher's page or another pupil's lines;
- the research pages and export, read with the research key (R1);
- a browser look at the teacher's screens with the whole class, wide and at phone width (S5).

Each returns plain dicts with a "probe" key, which the runner adds to the run's events for the
checks to read. A dict says what was asked and what came back: "probe", "path" (the request,
ids and all), "status" (None when nothing came back or nothing was sent) and a short "detail".
The export's dict adds "rows", and the look's has "passed", "reachable" and "research_seen" in
place of a path and a status. None of them ever holds what signs anyone in: a cookie, a join code
or the research key. Nothing here prints anything.
"""

import asyncio
import csv
import io
import json
import os
import signal
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from bench.school.guard import Refused, check_target
from bench.school.look import KEY_ENV, PASSWORD, SHOT_PAGES, counted, hidden, written_out
from bench.school.teacher import ACTIONS, LESSONS, THREAD, Seat, Teacher

JOIN = "/api/auth/join"
LEARN = "/api/learn"
# A teacher's own runs: those of today (open, paused or ended this week), then every ended one.
TODAY = "/api/teacher/today"
PAST = "/api/teacher/lessons/past"
RESEARCH = "/api/research"
SUMMARY = f"{RESEARCH}/summary"
EXPORT = f"{RESEARCH}/export"
KEY_HEADER = "X-Research-Key"
NO_KEY = "no research key set"
# How long a probe's request may take: the export reads the whole record.
TIMEOUT = httpx.Timeout(120.0, connect=10.0)

LOOK = Path(__file__).with_name("look.py")
LOOK_COMMAND = ("uv", "run", "-q", "--no-project", "--with", "playwright==1.64.1", "python", "-I")
# How long the website has to answer before the look starts, how long signing in on the test
# API may take, and how long the look may take before it is stopped, in seconds. A look that
# goes well takes well under a minute.
REACH_S = 5
SIGN_IN_S = 15
LOOK_S = 600
# How many of a failed look's problems its detail names.
MOST_PROBLEMS = 8
# Left out of the look's environment: Playwright's own logging and its inspector, either of
# which could print what the look types, the research key among it.
QUIET = ("DEBUG", "PWDEBUG")


# ---------- privacy ----------


async def privacy(
    base_url: str,
    client_factory: Callable[[], httpx.AsyncClient] | None,
    *,
    teacher_a: Teacher,
    teacher_b: Teacher,
    session_a: str,
    pupil_a: tuple[Seat, str],
    pupil_b: tuple[Seat, str],
    classmate_a: Seat,
    line_of_a: str,
) -> list[dict]:
    """X1 to X3: requests made as the wrong user, one dict each, in this order. B's teacher,
    with their own cookie, on one of A's lessons, A's class view, pupil A's card and
    conversation, and the research page of A's lesson (x1); pupil B on A's lesson and on the
    teacher's page (x2); pupil B rating pupil A's tutor line, and then `classmate_a`, a pupil of
    A's own lesson, doing the same (x3). The classmate gets past the lesson's door, so their
    refusal is the platform's check that a line is the pupil's own.

    `pupil_a` and `pupil_b` are each a pupil's seat and the session of the lesson they were in:
    pupil A's is `session_a`, and `line_of_a` is one of the tutor's lines on pupil A's page. Each
    pupil signs in with their code in a browser of their own, from `client_factory` (without
    one, a client on `base_url`, which must be a test API on this machine).

    A refusal shows something only when the ids are the right ones. So, before anything is
    tried: `session_a` must be one of teacher A's own runs; pupil A opens their own page of the
    lesson, which must show the line; the classmate must have the lesson among their own; and
    A's teacher reads their own lessons, one of which B's teacher asks for. When any of that
    fails, or a pupil cannot sign in, nothing is tried: every dict has no status and says why, so
    that the checks fail rather than pass. Setting up only reads.

    Users that would make a probe show a leak that is not there, or a refusal that is not one
    (pupil A in another lesson than session_a, pupil B in session_a, one teacher twice, or pupil
    A as their own classmate), are the run's mistake: ValueError, before anything is sent."""
    (seat_a, lesson_of_a), (seat_b, lesson_of_b) = pupil_a, pupil_b
    session_a, line_of_a = str(session_a), str(line_of_a)
    if str(lesson_of_a) != session_a:
        raise ValueError("Pupil A must be a pupil of session_a, the lesson the probes ask for.")
    if str(lesson_of_b) == session_a:
        raise ValueError("Pupil B must be a pupil of another lesson: session_a is their own.")
    if teacher_a.name == teacher_b.name:
        raise ValueError("Teacher B must be another teacher than teacher A.")
    if classmate_a.student_id == seat_a.student_id:
        raise ValueError("The classmate must be another pupil than pupil A: the line is A's own.")
    browser = client_factory or _browsers_on(base_url)
    a, b, pupil, them = teacher_a.name, teacher_b.name, seat_a.pseudonym, seat_b.pseudonym
    sid, of_pupil = session_a, {"session_id": session_a, "student_id": seat_a.student_id}
    async with browser() as as_a, browser() as as_b, browser() as as_c:
        why_not, lesson = await _set_up(
            teacher_a, session_a, line_of_a, (as_a, seat_a), (as_b, seat_b), (as_c, classmate_a)
        )
        rate = f"/api/learn/{sid}/lines/{line_of_a}/helped"
        planned = [
            _press(teacher_b, "show_lesson", f"{b} on one of {a}'s lessons", lesson_id=lesson),
            _press(teacher_b, "show_class", f"{b} on {a}'s class view", session_id=sid),
            _press(teacher_b, "show_student", f"{b} on {pupil}'s card in {a}'s lesson", **of_pupil),
            _press(
                teacher_b,
                "show_transcript",
                f"{b} reading {pupil}'s conversation in {a}'s lesson",
                **of_pupil,
            ),
            _Probe(
                "x1",
                teacher_b.client,
                "GET",
                f"{RESEARCH}/lessons/{sid}",
                None,
                f"{b} on the research page of {a}'s lesson",
            ),
            _Probe(
                "x2",
                as_b,
                "GET",
                f"/api/learn/{sid}",
                None,
                f"{them} on {a}'s lesson, another class's",
            ),
            _Probe("x2", as_b, "GET", THREAD, None, f"{them} on the teacher's page"),
            _Probe(
                "x3", as_b, "POST", rate, {"helped": True}, f"{them} rating {pupil}'s tutor line"
            ),
            _Probe(
                "x3",
                as_c,
                "POST",
                rate,
                {"helped": True},
                f"{classmate_a.pseudonym} rating {pupil}'s tutor line in their own lesson",
            ),
        ]
        if why_not:
            return [probe.not_tried(why_not) for probe in planned]
        return [await probe.send() for probe in planned]


@dataclass
class _Probe:
    """One request made as the wrong user, and the dict that says how it went."""

    probe: str
    client: httpx.AsyncClient
    method: str
    url: str
    body: dict | None
    detail: str

    @property
    def path(self) -> str:
        """The request, ids and all: for a teacher's button, which one, with what."""
        if self.url != ACTIONS:
            return f"{self.method} {self.url}"
        fields = " ".join(f"{name}={v}" for name, v in self.body.items() if name != "action")
        return f"{self.method} {self.url} {self.body['action']} {fields}"

    async def send(self) -> dict:
        """Makes the request and says how it went. A refusal quotes what the platform said, which
        tells apart where it was refused (a lesson's door, or a line that is not the pupil's);
        a success quotes nothing, since its answer is what should have stayed closed."""
        try:
            reply = await self.client.request(self.method, self.url, json=self.body)
        except httpx.HTTPError as failed:
            return self._said(None, f"{self.detail}: no answer came ({type(failed).__name__})")
        said = _json(reply).get("detail") if not reply.is_success else None
        if isinstance(said, str) and said:
            return self._said(reply.status_code, f'{self.detail}; the platform said "{said[:80]}"')
        return self._said(reply.status_code, self.detail)

    def not_tried(self, why: str) -> dict:
        return self._said(None, f"not tried: {why}, so a refusal would show nothing")

    def _said(self, status: int | None, detail: str) -> dict:
        return {"probe": self.probe, "path": self.path, "status": status, "detail": detail}


def _press(teacher: Teacher, action: str, detail: str, **ids: str | None) -> _Probe:
    """The teacher pressing one of the buttons on a teacher's cards, with these ids."""
    return _Probe("x1", teacher.client, "POST", ACTIONS, {"action": action, **ids}, detail)


Browser = tuple[httpx.AsyncClient, Seat]


async def _set_up(
    teacher_a: Teacher,
    session_a: str,
    line_of_a: str,
    pupil_a: Browser,
    pupil_b: Browser,
    classmate: Browser,
) -> tuple[str | None, str | None]:
    """Makes sure the ids are the right ones, signing each pupil in in their own browser: why
    the probes would show nothing (None when they would show something), and one of A's lessons.
    Only reads."""
    (as_a, seat_a), (as_b, seat_b), (as_c, seat_c) = pupil_a, pupil_b, classmate
    try:
        why = (
            await _runs_lesson(teacher_a, session_a)
            or await _signs_in(as_a, seat_a, "pupil A")
            or await _shows_line(as_a, session_a, line_of_a)
            or await _signs_in(as_c, seat_c, "the classmate")
            or await _in_lesson(as_c, session_a, seat_c)
            or await _signs_in(as_b, seat_b, "pupil B")
        )
        return (why, None) if why else await _a_lesson(teacher_a)
    except httpx.HTTPError as failed:
        return f"setting up got no answer from the platform ({type(failed).__name__})", None


async def _runs_lesson(teacher: Teacher, session_id: str) -> str | None:
    """Why the lesson run is not the teacher's own, by their own lists of runs, or None."""
    for path in (TODAY, PAST):
        reply = await teacher.client.get(path)
        if reply.status_code != 200:
            return f"{teacher.name}'s own lessons could not be read ({path}: {reply.status_code})"
        data = _data(reply)
        if isinstance(data, dict):
            data = [*(data.get("coming_up") or []), *(data.get("finished") or [])]
        runs = {str(row.get("lesson_id")) for row in data or [] if isinstance(row, dict)}
        if session_id in runs:
            return None
    return f"{session_id} is not one of {teacher.name}'s lessons"


async def _in_lesson(client: httpx.AsyncClient, session_id: str, seat: Seat) -> str | None:
    """Why the classmate is not a pupil of the lesson, by their own list of lessons (which
    writes nothing), or None."""
    reply = await client.get(LEARN)
    data = _data(reply) if reply.status_code == 200 else None
    listed = {str(card.get("session_id")) for card in data or [] if isinstance(card, dict)}
    if session_id in listed:
        return None
    return f"the classmate ({seat.pseudonym}) does not have the lesson among their own"


async def _signs_in(client: httpx.AsyncClient, seat: Seat, who: str) -> str | None:
    reply = await client.post(JOIN, json={"code": seat.code})
    if reply.status_code == 200:
        return None
    return f"{who} ({seat.pseudonym}) could not sign in with their code ({reply.status_code})"


async def _shows_line(client: httpx.AsyncClient, session_id: str, line_id: str) -> str | None:
    """Why pupil A's own page of the lesson does not show the tutor's line, or None."""
    reply = await client.get(f"/api/learn/{session_id}")
    if reply.status_code != 200:
        return f"pupil A's own page of the lesson answered {reply.status_code}"
    lines = [str(x.get("id")) for x in _json(reply).get("lines") or [] if x.get("who") == "agent"]
    if line_id in lines:
        return None
    return f"pupil A's own page does not show the tutor's line {line_id}"


async def _a_lesson(teacher: Teacher) -> tuple[str | None, str | None]:
    """One of the teacher's own lessons, from their list; or why there is none."""
    reply = await teacher.client.get(LESSONS)
    listed = (_json(reply).get("lessons") or []) if reply.status_code == 200 else []
    if not listed:
        return f"{teacher.name}'s own list of lessons answered {reply.status_code} with none", None
    return None, str(listed[0]["lesson_id"])


# ---------- the research pages ----------


async def research(
    base_url: str, client_factory: Callable[[], httpx.AsyncClient] | None, sessions: list[str]
) -> list[dict]:
    """R1: the research pages and export, read with the research key as a researcher reads them.
    One dict for the summary, which says how many of `sessions` it lists; one for each of their
    pages, with its tutor turns and pupils; and one for the export, whose "rows" counts the rows
    of its turns.csv for each of `sessions` ({session id: rows}; None when the export could not
    be read).

    The key comes from the settings and goes in each request's header, nowhere else. With no key
    set, nothing is asked, and the one dict says so. Without `client_factory`, the requests go to
    `base_url`, which must be a test API on this machine."""
    key = get_settings().research_key
    if not key:
        return [{"probe": "research", "status": None, "detail": NO_KEY}]
    run = [str(s) for s in sessions]
    browser = client_factory or _browsers_on(base_url)
    async with browser() as client:

        async def read(path: str) -> tuple[httpx.Response | None, str]:
            try:
                return await client.get(path, headers={KEY_HEADER: key}), ""
            except httpx.HTTPError as failed:
                return None, type(failed).__name__

        found = [_page(SUMMARY, *await read(SUMMARY), lambda data: _listed(data, run))]
        for sid in run:
            path = f"{RESEARCH}/lessons/{sid}"
            found.append(_page(path, *await read(path), _lesson_said))
        found.append(_export(*await read(EXPORT), run))
    return found


def _page(path: str, reply: httpx.Response | None, failure: str, describe) -> dict:
    """How a research page answered, and what it shows of the run when it opened."""
    if reply is None:
        status, detail = None, f"no answer came ({failure})"
    elif reply.status_code != 200:
        status, detail = reply.status_code, "did not open"
    else:
        status, detail = 200, describe(_json(reply))
    return {"probe": "research", "path": path, "status": status, "detail": detail}


def _listed(summary: dict, run: list[str]) -> str:
    listed = {str(row.get("session_id")) for row in summary.get("lessons") or []}
    missing = [sid for sid in run if sid not in listed]
    said = f"lists {len(run) - len(missing)} of the run's {len(run)} lessons"
    return f"{said}; not listed: {', '.join(missing)}" if missing else said


def _lesson_said(lesson: dict) -> str:
    return f"{lesson.get('turns', 0)} tutor turns, {len(lesson.get('students') or [])} pupils"


def _export(reply: httpx.Response | None, failure: str, run: list[str]) -> dict:
    found = {"probe": "research", "path": EXPORT, "status": None, "detail": "", "rows": None}
    if reply is None:
        return {**found, "detail": f"no answer came ({failure})"}
    if reply.status_code != 200:
        return {**found, "status": reply.status_code, "detail": "did not open"}
    try:
        rows = _turn_rows(reply.content, run)
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, csv.Error) as failed:
        said = f"its turns.csv could not be read ({type(failed).__name__})"
        return {**found, "status": 200, "detail": said}
    said = f"turns.csv has {sum(rows.values())} rows for the run's {len(run)} lessons"
    return {**found, "status": 200, "detail": said, "rows": rows}


def _turn_rows(export: bytes, run: list[str]) -> dict[str, int]:
    """The rows of the export's turns.csv for each lesson of the run, read in memory: the
    export is never saved."""
    rows = dict.fromkeys(run, 0)
    with zipfile.ZipFile(io.BytesIO(export)) as archive, archive.open("turns.csv") as raw:
        for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline="")):
            if row.get("session_id") in rows:
                rows[row["session_id"]] += 1
    return rows


# ---------- the browser look ----------


async def run_look(website: str, api: str, teacher: str, folder: Path) -> dict:
    """S5: runs look.py on `website` as `teacher` (see look.py for what it reads and checks) and
    says how it went: {"probe": "look", "passed", "reachable", "research_seen", "detail"}.
    `reachable` is False when the website does not answer, and `research_seen` whether the look
    saw the research pages (never without a research key). The look only reads, so the teacher's
    screen must already show the class view of their lesson (the runner presses show_class
    first).

    Before any browser starts, the teacher signs in on the test API at `api` itself, and the
    website must then show their screen with that sign-in. A website whose /api goes anywhere
    else, such as one built without API_INTERNAL_URL, which sends it to the live API, answers
    401: then nothing is looked at, and nothing the look sends through the website can write to
    the live database.

    The look writes look.json and its screenshots to `folder`, after what an earlier look wrote
    there is taken away. The research key, when one is set, reaches the script through its
    environment alone, without Playwright's logging, and is taken out of anything the script
    says. Refused (raised) for a website or API that is not a test one on this machine (never
    the live site's 3000 or 8000), each before anything is sent to it, and for an API at the
    website's own address."""
    check_target(website)
    folder = Path(folder)
    silent = await _no_answer(website)
    if silent:
        said = f"The website at {website} did not answer ({silent}), so nothing was looked at."
        return _looked(False, False, False, said)
    check_target(api)
    if urlsplit(api).port == urlsplit(website).port:
        raise Refused("The test API is the website's own address: the look signs in on the API.")
    refused = await _not_the_test_api(website, api, teacher)
    if refused:
        return _looked(False, True, False, refused)
    folder.mkdir(parents=True, exist_ok=True)
    _clear(folder)
    key = get_settings().research_key
    env = {name: value for name, value in os.environ.items() if name not in QUIET}
    command = [*LOOK_COMMAND, str(LOOK), website, api, teacher, str(folder)]
    try:
        code, said = await _launch(command, {**env, KEY_ENV: key})
    except TimeoutError:
        said = f"The look took longer than {LOOK_S} s, so it was stopped."
        return _looked(False, True, False, said)
    except OSError as failed:
        said = f"The look could not be started ({type(failed).__name__})."
        return _looked(False, True, False, said)
    report = _report(folder / "look.json")
    if report is None:
        last = said.strip().splitlines()[-1] if said.strip() else "nothing"
        told = f"look.py ended with code {code} and wrote no look.json. The last it said: {last}"
        return _looked(False, True, False, hidden(told, key))
    passed = code == 0 and report.get("passed") is True
    seen = report.get("research_seen") is True
    return _looked(passed, True, seen, hidden(_look_detail(report, code, folder), key))


async def _no_answer(website: str) -> str | None:
    """The kind of failure when the website gives no answer; None when it answers anything."""
    try:
        async with httpx.AsyncClient(timeout=REACH_S, trust_env=False) as client:
            await client.get(website)
    except httpx.HTTPError as failed:
        return type(failed).__name__
    return None


async def _not_the_test_api(website: str, api: str, teacher: str) -> str | None:
    """Why the website is not to be looked at, or None: the teacher signs in on the test API
    itself, and the website must then show their screen with that sign-in (cookies on this
    machine are not kept apart by port). Only the sign-in writes, and it goes to the test API."""
    sign_in = {"role": "teacher", "username": teacher, "password": PASSWORD}
    try:
        async with httpx.AsyncClient(timeout=SIGN_IN_S, trust_env=False) as client:
            signed = await client.post(f"{api}/api/auth/demo", json=sign_in)
            if signed.status_code != 200:
                return (
                    f"Demo sign-in as {teacher} on the test API at {api} answered "
                    f"{signed.status_code}, so nothing was looked at."
                )
            screen = await client.get(f"{website}/api/teacher/thread")
    except httpx.HTTPError as failed:
        return (
            f"The test API at {api} or the website could not be asked who is signed in "
            f"({type(failed).__name__}), so nothing was looked at."
        )
    if screen.status_code == 200:
        return None
    return (
        f"The website at {website} does not reach the test API at {api}: signed in there, the "
        f"teacher's screen answered {screen.status_code} through the website. Its /api may go "
        "to another API (the live one, when it was built without API_INTERNAL_URL), so nothing "
        "was looked at."
    )


def _clear(folder: Path) -> None:
    """Takes away what an earlier look wrote to the folder, look.json and its screenshots, so
    that none of it is read or shown as this look's. Nothing else in the folder is touched."""
    (folder / "look.json").unlink(missing_ok=True)
    for page in SHOT_PAGES:
        for shot in folder.glob(f"{page}-*.png"):
            shot.unlink()


async def _launch(command: list[str], env: dict[str, str]) -> tuple[int, str]:
    """Runs the look and waits for it: its exit code, and what it said on stderr. It runs in a
    process group of its own, which is stopped whole, browser and all, when it takes longer than
    LOOK_S seconds (TimeoutError) or the run is stopped."""
    process = await asyncio.create_subprocess_exec(
        *command,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _, said = await asyncio.wait_for(process.communicate(), LOOK_S)
    except TimeoutError:
        _stop_group(process.pid)
        await process.wait()
        raise
    except asyncio.CancelledError:
        _stop_group(process.pid)
        raise
    return process.returncode, said.decode(errors="replace")


def _stop_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        # Gone already, or only uv's exit is left to collect, which macOS answers with a
        # permission error.
        pass


def _report(path: Path) -> dict | None:
    """What the look wrote to look.json, or None when it wrote nothing readable."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def _look_detail(report: dict, code: int, folder: Path) -> str:
    problems = [str(p) for p in report.get("problems") or []]
    if problems:
        said = f"{counted(len(problems), 'problem')}: {'; '.join(problems[:MOST_PROBLEMS])}"
        if len(problems) > MOST_PROBLEMS:
            said += f"; and {len(problems) - MOST_PROBLEMS} more"
        said += "."
    elif code != 0 or report.get("passed") is not True:
        said = f"look.py ended with code {code} without saying what failed."
    else:
        said = (
            f"Looked at {len(report.get('pages') or [])} pages, wide and at phone width: every "
            "pupil on the class view, nothing off the side, no dialog over the screen, no page "
            "errors, no long dashes, and nothing sent but reads."
        )
    research_view = str(report.get("research") or "")
    if research_view.startswith("not opened"):
        said += f" The research view was {research_view}."
    stopped = [str(s) for s in report.get("stopped") or []]
    if stopped:
        said += f" Stopped before they left the browser: {', '.join(stopped)}."
    return f"{said} Screenshots and look.json are in {folder}."


def _looked(passed: bool, reachable: bool, research_seen: bool, detail: str) -> dict:
    return {
        "probe": "look",
        "passed": passed,
        "reachable": reachable,
        "research_seen": research_seen,
        "detail": written_out(detail),
    }


# ---------- shared ----------


def _browsers_on(base_url: str) -> Callable[[], httpx.AsyncClient]:
    """Browsers on `base_url`, for a caller that brings none: refused for anything but a test
    API on this machine."""
    check_target(base_url)
    return lambda: httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT)


def _data(reply: httpx.Response):
    """The answer's JSON, or None when it is not JSON."""
    try:
        return reply.json()
    except ValueError:
        return None


def _json(reply: httpx.Response) -> dict:
    """The answer's JSON object, or an empty one when it is not one."""
    data = _data(reply)
    return data if isinstance(data, dict) else {}
