"""The probes a school day runs after its lessons, with no model calls: privacy (a teacher cannot
open another teacher's lessons, pupils or research pages; a pupil cannot open another class's
lesson, a teacher's page or another pupil's lines), the research pages and export with the
research key, and the browser look at the teacher's screens.

Two teachers sign in through demo sign-in, and each makes a class and runs their sample lesson,
on the app in this process with a scripted tutor. Each user has a browser of their own (one
cookie jar). The look itself is never run here, since it needs Playwright and a website: a
stand-in takes the script's place, small servers on this machine stand in for the test API and
the website, and the script's own checks are tested without a browser.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.agent import llm
from app.config import get_settings
from app.models import AgentTurn
from bench.school import look, probes
from bench.school.guard import Refused
from bench.school.probes import privacy, research, run_look
from bench.school.teacher import LESSONS, Seat, Teacher

# What the scripted tutor says to every pupil, whatever they write.
ASKS = {"message": "What do you get? Show me how.", "move": "ask", "task": "Solve it"}
JOIN = "/api/auth/join"


@dataclass
class School:
    """Two teachers, each running their sample lesson with a class of two. Pupil A and their
    classmate, the two of A's class, have both opened the lesson: `line_of_a` is the tutor's line
    on pupil A's page."""

    browsers: Callable[[], httpx.AsyncClient]
    a: Teacher
    b: Teacher
    session_a: str
    session_b: str
    seats_a: list[Seat]
    seats_b: list[Seat]
    line_of_a: str


async def opens(browsers, seat: Seat, session_id: str) -> dict:
    """The pupil signs in with their code and starts the lesson: their page, with the tutor's
    opening on it."""
    async with browsers() as pupil:
        assert (await pupil.post(JOIN, json={"code": seat.code})).status_code == 200
        started = await pupil.post(f"/api/learn/{session_id}/start")
    assert started.status_code == 200, started.text
    return started.json()


async def page_of(browsers, seat: Seat, session_id: str) -> dict:
    """The pupil's page of the lesson as it is now, read in a browser of the test's own."""
    async with browsers() as pupil:
        assert (await pupil.post(JOIN, json={"code": seat.code})).status_code == 200
        return (await pupil.get(f"/api/learn/{session_id}")).json()


@pytest.fixture
async def school(app, monkeypatch) -> AsyncIterator[School]:
    # Demo sign-in on, and the cookie doing the work rather than the test-only header.
    monkeypatch.setattr(get_settings(), "demo_sign_in", True)
    monkeypatch.setattr(get_settings(), "dev_identity_enabled", False)
    tutor = llm.ScriptedClient(lambda purpose, system, messages: ASKS)
    app.dependency_overrides[llm.get_llm_client] = lambda: tutor

    def browsers() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async with browsers() as of_a, browsers() as of_b:
        a, b = Teacher(of_a, "ms-amari"), Teacher(of_b, "mr-brandt")
        runs = []
        for teacher, label in ((a, "9S"), (b, "9T")):
            await teacher.sign_in()
            class_id, seats = await teacher.make_class(label, 2)
            [sample] = (await teacher.client.get(LESSONS)).json()["lessons"]
            runs.append((await teacher.run(sample["lesson_id"], class_id), seats))
        (session_a, seats_a), (session_b, seats_b) = runs
        page = await opens(browsers, seats_a[0], session_a)
        await opens(browsers, seats_a[1], session_a)
        line = [x["id"] for x in page["lines"] if x["who"] == "agent"][-1]
        yield School(browsers, a, b, session_a, session_b, seats_a, seats_b, str(line))


def privacy_args(school: School, **instead) -> dict:
    """What the runner hands the privacy probe, between A's and B's teachers and pupils, with
    any of it swapped for `instead`."""
    sent = {
        "teacher_a": school.a,
        "teacher_b": school.b,
        "session_a": school.session_a,
        "pupil_a": (school.seats_a[0], school.session_a),
        "pupil_b": (school.seats_b[0], school.session_b),
        "classmate_a": school.seats_a[1],
        "line_of_a": school.line_of_a,
    }
    return {**sent, **instead}


async def probe_privacy(school: School, **instead) -> list[dict]:
    return await privacy("http://test", school.browsers, **privacy_args(school, **instead))


def holds_nothing_that_signs_in(found: list[dict], school: School) -> bool:
    """Whether the probes' dicts hold no cookie of the teachers and no pupil's join code."""
    text = json.dumps(found)
    secrets = [*school.a.client.cookies.values(), *school.b.client.cookies.values()]
    secrets += [seat.code for seat in school.seats_a + school.seats_b]
    return bool(secrets) and not any(secret in text for secret in secrets)


ORDER = ["x1"] * 5 + ["x2"] * 2 + ["x3"] * 2


# ---------- privacy ----------


async def test_another_teachers_pages_are_closed(app, school):
    found = await probe_privacy(school)

    x1 = [p for p in found if p["probe"] == "x1"]
    sid, pupil = school.session_a, school.seats_a[0].student_id
    [lesson] = (await school.a.client.get(LESSONS)).json()["lessons"]
    # B's teacher tried each of A's pages, with B's own cookie.
    assert [p["path"] for p in x1] == [
        f"POST /api/teacher/thread/actions show_lesson lesson_id={lesson['lesson_id']}",
        f"POST /api/teacher/thread/actions show_class session_id={sid}",
        f"POST /api/teacher/thread/actions show_student session_id={sid} student_id={pupil}",
        f"POST /api/teacher/thread/actions show_transcript session_id={sid} student_id={pupil}",
        f"GET /api/research/lessons/{sid}",
    ]
    assert all(p["status"] in (403, 404) for p in x1), x1
    assert all(p["detail"].startswith("mr-brandt") and "ms-amari" in p["detail"] for p in x1)
    # A probe holds what was asked and what came back, and nothing that signs anyone in.
    assert all(set(p) == {"probe", "path", "status", "detail"} for p in found)
    assert holds_nothing_that_signs_in(found, school)


async def test_a_pupil_cannot_reach_another_class_or_teacher_pages(app, school):
    found = await probe_privacy(school)

    sid, line = school.session_a, school.line_of_a
    them, classmate = school.seats_b[0].pseudonym, school.seats_a[1].pseudonym
    x2 = [p for p in found if p["probe"] == "x2"]
    x3 = [p for p in found if p["probe"] == "x3"]
    assert [p["probe"] for p in found] == ORDER
    assert [p["path"] for p in x2] == [f"GET /api/learn/{sid}", "GET /api/teacher/thread"]
    assert [p["path"] for p in x3] == [f"POST /api/learn/{sid}/lines/{line}/helped"] * 2
    assert all(p["status"] in (403, 404) for p in x2 + x3), x2 + x3
    assert all(p["detail"].startswith(them) for p in x2 + x3[:1])
    # Pupil B is turned away at the lesson's door. A classmate in the same lesson gets past it,
    # and the line itself is refused: it is not in their own conversation. Each probe quotes
    # what the platform said, which tells the two apart.
    assert x3[0]["detail"].endswith('the platform said "Session not found."')
    assert x3[1]["detail"].startswith(classmate) and "own lesson" in x3[1]["detail"]
    assert x3[1]["status"] == 404
    assert x3[1]["detail"].endswith('the platform said "No such reply."')
    assert x2[1]["detail"].endswith('the platform said "Teachers only."')
    # The line they both tried to rate is still unrated on pupil A's page.
    page = await page_of(school.browsers, school.seats_a[0], sid)
    [tapped] = [x for x in page["lines"] if str(x["id"]) == line]
    assert tapped["helped"] is None
    assert holds_nothing_that_signs_in(found, school)


async def test_ids_that_would_prove_nothing_leave_every_probe_not_tried(app, school):
    """A refusal shows something only when the ids are the right ones: pupil A's own page must
    show the line, or a 404 could come from an id that was made up. Then nothing is tried, and
    every probe says why with no status, so that the checks fail rather than pass."""
    found = await probe_privacy(school, line_of_a=str(uuid.uuid4()))

    assert [p["probe"] for p in found] == ORDER
    assert all(p["status"] is None for p in found)
    assert all(p["detail"].startswith("not tried: ") for p in found)
    assert all("does not show the tutor's line" in p["detail"] for p in found)


async def test_teachers_mixed_up_leave_every_probe_not_tried(app, school):
    """Handed the two teachers the wrong way round, B's teacher would be the lesson's own and
    open it: a leak that is not there. The lesson must be one of teacher A's own runs first."""
    found = await probe_privacy(school, teacher_a=school.b, teacher_b=school.a)

    assert [p["probe"] for p in found] == ORDER
    assert all(p["status"] is None for p in found)
    assert all(
        f"{school.session_a} is not one of mr-brandt's lessons" in p["detail"] for p in found
    )


async def test_a_classmate_from_another_class_leaves_every_probe_not_tried(app, school):
    """A "classmate" who is not in A's lesson would be turned away at its door, and so never
    test whether a line is the pupil's own. The lesson must be among the classmate's own."""
    stranger = school.seats_b[1]
    found = await probe_privacy(school, classmate_a=stranger)

    assert [p["probe"] for p in found] == ORDER
    assert all(p["status"] is None for p in found)
    assert all(
        f"the classmate ({stranger.pseudonym}) does not have the lesson among their own"
        in p["detail"]
        for p in found
    )


@pytest.mark.parametrize(
    "mistake",
    [
        "pupil A in another lesson",
        "pupil B in A's lesson",
        "one teacher twice",
        "the classmate is pupil A",
    ],
)
async def test_a_probe_set_up_wrongly_is_refused_before_anything_is_sent(app, school, mistake):
    """Each of these would make a probe show a leak that is not there, or a refusal that is
    not one: the run's own mistake, so nothing is sent."""
    instead = {
        "pupil A in another lesson": {"pupil_a": (school.seats_a[0], school.session_b)},
        "pupil B in A's lesson": {"pupil_b": (school.seats_a[1], school.session_a)},
        "one teacher twice": {"teacher_b": school.a},
        "the classmate is pupil A": {"classmate_a": school.seats_a[0]},
    }[mistake]
    asked = []

    def browsers() -> httpx.AsyncClient:
        asked.append("a browser")
        return school.browsers()

    with pytest.raises(ValueError):
        await privacy("http://test", browsers, **privacy_args(school, **instead))
    assert asked == []


# ---------- the research pages ----------


async def turns_in(db, session_id: str) -> int:
    """The tutor's turns with pupils in that lesson, as the platform keeps them."""
    return await db.scalar(
        select(func.count())
        .select_from(AgentTurn)
        .where(AgentTurn.session_id == uuid.UUID(session_id), AgentTurn.mode == "student")
    )


async def test_the_research_probes_count_the_runs_turns(app, researcher, school, db):
    # More turns: pupil A writes, pupil B starts their own lesson.
    async with school.browsers() as pupil:
        assert (await pupil.post(JOIN, json={"code": school.seats_a[0].code})).status_code == 200
        said = await pupil.post(f"/api/learn/{school.session_a}/messages", json={"text": "x = 7"})
        assert said.status_code == 200, said.text
    await opens(school.browsers, school.seats_b[0], school.session_b)
    run = [school.session_a, school.session_b]
    turns = {sid: await turns_in(db, sid) for sid in run}
    assert turns[school.session_a] >= 2 and turns[school.session_b] >= 1

    found = await research("http://test", school.browsers, run)

    assert found[0] == {
        "probe": "research",
        "path": "/api/research/summary",
        "status": 200,
        "detail": "lists 2 of the run's 2 lessons",
    }
    assert [(p["path"], p["status"]) for p in found[1:3]] == [
        (f"/api/research/lessons/{sid}", 200) for sid in run
    ]
    assert [p["detail"] for p in found[1:3]] == [
        f"{turns[sid]} tutor turns, 2 pupils" for sid in run
    ]
    [export] = found[3:]
    assert (export["path"], export["status"]) == ("/api/research/export", 200)
    # The export's turns file has a row for every one of the run's turns, lesson by lesson.
    assert export["rows"] == turns
    assert export["detail"] == f"turns.csv has {sum(turns.values())} rows for the run's 2 lessons"

    # Only the run's lessons are counted, and the summary says which it does not list.
    only_a = await research("http://test", school.browsers, [school.session_a])
    assert only_a[-1]["rows"] == {school.session_a: turns[school.session_a]}
    gone = str(uuid.uuid4())
    missing = await research("http://test", school.browsers, [school.session_a, gone])
    assert missing[0]["detail"] == f"lists 1 of the run's 2 lessons; not listed: {gone}"
    assert missing[2]["status"] == 404
    assert missing[-1]["rows"] == {school.session_a: turns[school.session_a], gone: 0}
    # The key goes in the requests' header and nowhere else.
    assert researcher["X-Research-Key"] not in json.dumps(found + only_a + missing)


async def test_without_a_research_key_the_probe_says_so_and_asks_nothing(monkeypatch):
    monkeypatch.setattr(get_settings(), "research_key", "")

    def no_browser() -> httpx.AsyncClient:
        raise AssertionError("Nothing is asked without a key.")

    found = await research("http://test", no_browser, [str(uuid.uuid4())])
    assert found == [{"probe": "research", "status": None, "detail": "no research key set"}]


# ---------- the browser look ----------


@pytest.fixture
def no_browser(monkeypatch) -> list:
    """Fails the test if the look script would be started: these tests never open a browser."""
    started = []

    async def launch(command: list[str], env: dict[str, str]) -> tuple[int, str]:
        started.append(command)
        raise AssertionError("The look script was started.")

    monkeypatch.setattr(probes, "_launch", launch)
    return started


@dataclass
class Asked:
    """One request a stand-in server was sent."""

    method: str
    path: str
    cookie: str


@pytest.fixture
async def stand_ins() -> AsyncIterator[Callable]:
    """Starts small servers on this machine, each answering with `answer(method, path,
    headers)`, which gives a status, more headers and a body. Each gives its address and the
    requests it was sent."""
    servers = []

    async def start(answer) -> tuple[str, list[Asked]]:
        asked: list[Asked] = []

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1").split("\r\n")
                method, target, _ = head[0].split(" ", 2)
                headers = {
                    name.strip().lower(): value.strip()
                    for name, value in (line.split(":", 1) for line in head[1:] if ":" in line)
                }
                if length := int(headers.get("content-length", "0")):
                    await reader.readexactly(length)
                path = target.split("?", 1)[0]
                asked.append(Asked(method, path, headers.get("cookie", "")))
                status, more, body = answer(method, path, headers)
                lines = [f"HTTP/1.1 {status} Stand-in", f"Content-Length: {len(body)}"]
                lines += ["Connection: close", *(f"{k}: {v}" for k, v in more.items())]
                writer.write(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
                await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        servers.append(server)
        return f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}", asked

    yield start
    for server in servers:
        server.close()
        await server.wait_closed()


# The sign-in the stand-in test API gives the teacher.
TOKEN = "stand-in-sign-in"


def the_api(method: str, path: str, headers: dict) -> tuple[int, dict, bytes]:
    """The test API: demo sign-in, and nothing else."""
    if (method, path) == ("POST", "/api/auth/demo"):
        cookie = {"Set-Cookie": f"pact_teacher={TOKEN}; Path=/; HttpOnly"}
        return 200, cookie, b'{"pseudonym": "ms-amari", "role": "teacher"}'
    return 404, {}, b"{}"


def a_website(reaches_the_api: bool):
    """A website whose /api goes to the stand-in test API, or else to another API, which knows
    nobody signed in there and so answers 401, as the live API would."""

    def answer(method: str, path: str, headers: dict) -> tuple[int, dict, bytes]:
        if path == "/api/teacher/thread":
            signed_in = reaches_the_api and f"pact_teacher={TOKEN}" in headers.get("cookie", "")
            return (200 if signed_in else 401), {}, b"{}"
        return 200, {}, b"<!doctype html><title>stand-in</title>"

    return answer


@pytest.fixture
async def sites(stand_ins) -> tuple[str, str, list[Asked]]:
    """A test API and a website that reaches it: the website's address, the API's, and what the
    website was sent."""
    api, _ = await stand_ins(the_api)
    website, asked = await stand_ins(a_website(reaches_the_api=True))
    return website, api, asked


async def test_run_look_says_not_reachable_without_a_website(tmp_path, no_browser):
    result = await run_look("http://127.0.0.1:3999", "http://127.0.0.1:3998", "nobody", tmp_path)
    assert result == {
        "probe": "look",
        "passed": False,
        "reachable": False,
        "research_seen": False,
        "detail": result["detail"],
    }
    assert "did not answer" in result["detail"]
    assert no_browser == []


async def test_no_probe_goes_near_the_live_site(tmp_path, no_browser, researcher, sites):
    """The live site's website (3000) and API (8000) are refused before anything is sent to
    them, and so is an API at the website's own address: the look signs in on the API itself."""
    website, api, asked = sites
    for live in ("http://127.0.0.1:3000", "http://127.0.0.1:8000"):
        with pytest.raises(Refused):
            await run_look(live, api, "ms-amari", tmp_path)
        with pytest.raises(Refused):
            await run_look(website, live, "ms-amari", tmp_path)
    with pytest.raises(Refused):
        await run_look(website, website, "ms-amari", tmp_path)
    with pytest.raises(Refused):
        await research("http://127.0.0.1:8000", None, [str(uuid.uuid4())])
    assert no_browser == []
    assert {a.method for a in asked} == {"GET"}


async def test_a_website_that_reaches_another_api_is_not_looked_at(tmp_path, stand_ins, no_browser):
    """A website built without API_INTERNAL_URL sends /api to the live API. Signed in on the
    test API itself, the teacher is then unknown through such a website, and the look does not
    start: nothing it would send through the website can write to the live database."""
    api, at_api = await stand_ins(the_api)
    website, at_website = await stand_ins(a_website(reaches_the_api=False))

    result = await run_look(website, api, "ms-amari", tmp_path)

    assert result == {
        "probe": "look",
        "passed": False,
        "reachable": True,
        "research_seen": False,
        "detail": result["detail"],
    }
    assert "does not reach the test API" in result["detail"] and "401" in result["detail"]
    assert no_browser == []
    # The sign-in went to the test API itself; the website was only read, with that sign-in.
    assert [(a.method, a.path) for a in at_api] == [("POST", "/api/auth/demo")]
    assert {a.method for a in at_website} == {"GET"}
    assert [a.cookie for a in at_website if a.path == "/api/teacher/thread"] == [
        f"pact_teacher={TOKEN}"
    ]


def stand_in(folder: Path, seen: dict, *, code: int, report: dict | None, stderr: str = ""):
    """The look script's place: notes how it was started and what the folder held, then writes
    `report` as look.json (nothing when None) and ends with `code`, saying `stderr`."""

    async def launch(command: list[str], env: dict[str, str]) -> tuple[int, str]:
        seen.update(command=command, env=env, held=sorted(p.name for p in folder.iterdir()))
        if report is not None:
            (folder / "look.json").write_text(json.dumps(report), encoding="utf-8")
        return code, stderr

    return launch


PASSED = {
    "passed": True,
    "research_seen": True,
    "pages": [
        {"name": n, "problems": []} for n in ("teacher-wide", "research-wide", "lesson-wide")
    ],
    "problems": [],
    "stopped": [],
    "research": "read with the research key",
}


async def test_run_look_runs_the_script_with_the_key_kept_out_of_sight(
    tmp_path, monkeypatch, researcher, sites
):
    website, api, _ = sites
    key = researcher["X-Research-Key"]
    # What an earlier look left is never read or shown as this look's; nothing else is touched.
    for old in ("look.json", "teacher-wide-1.png", "research-phone-2.png", "lesson-wide-1.png"):
        (tmp_path / old).write_text("from an earlier look", encoding="utf-8")
    (tmp_path / "server.log").write_text("the run's own", encoding="utf-8")
    # Playwright's own logging and its inspector would print what the look types.
    monkeypatch.setenv("DEBUG", "pw:api")
    monkeypatch.setenv("PWDEBUG", "1")
    seen: dict = {}
    monkeypatch.setattr(probes, "_launch", stand_in(tmp_path, seen, code=0, report=PASSED))

    result = await run_look(website, api, "ms-amari", tmp_path)

    assert result == {
        "probe": "look",
        "passed": True,
        "reachable": True,
        "research_seen": True,
        "detail": result["detail"],
    }
    assert result["detail"].startswith("Looked at 3 pages")
    assert seen["held"] == ["server.log"]
    assert seen["command"] == [
        "uv",
        "run",
        "-q",
        "--no-project",
        "--with",
        "playwright==1.64.1",
        "python",
        "-I",
        str(Path(probes.__file__).with_name("look.py")),
        website,
        api,
        "ms-amari",
        str(tmp_path),
    ]
    # The key reaches the script only through its environment: never its command line, which
    # anyone on the machine can read, and never what the probe says.
    assert seen["env"][look.KEY_ENV] == key
    assert not any(key in part for part in seen["command"])
    assert "DEBUG" not in seen["env"] and "PWDEBUG" not in seen["env"]
    assert key not in json.dumps(result)


async def test_a_look_that_fails_says_what_failed_and_never_the_key(
    tmp_path, monkeypatch, researcher, sites
):
    website, api, _ = sites
    key = researcher["X-Research-Key"]
    failed = {
        **PASSED,
        "passed": False,
        "research_seen": False,
        "problems": [
            "teacher-phone: 2 of 30 pupils are not on the class view: AB12C, ZX9QK",
            f"research-wide: the look at this page stopped: Locator.fill({key}) timed out",
        ],
        "stopped": ["POST /api/teacher/thread/actions"],
    }
    seen: dict = {}
    monkeypatch.setattr(probes, "_launch", stand_in(tmp_path, seen, code=1, report=failed))
    result = await run_look(website, api, "ms-amari", tmp_path)

    assert (result["passed"], result["reachable"], result["research_seen"]) == (False, True, False)
    assert result["detail"].startswith("2 problems: teacher-phone: 2 of 30 pupils")
    assert "POST /api/teacher/thread/actions" in result["detail"]
    assert key not in result["detail"]

    # A script that ends without writing look.json fails the look, and says how it ended.
    monkeypatch.setattr(
        probes,
        "_launch",
        stand_in(tmp_path, seen, code=1, report=None, stderr=f"Traceback\nError: bad {key}\n"),
    )
    result = await run_look(website, api, "ms-amari", tmp_path)
    assert (result["passed"], result["reachable"], result["research_seen"]) == (False, True, False)
    assert "wrote no look.json" in result["detail"] and "code 1" in result["detail"]
    assert key not in result["detail"]


# ---------- the look's own checks, without a browser ----------

KEY = "a-research-key-for-the-test"


def test_the_looks_checks_find_what_runs_off_the_side_long_dashes_and_missing_pupils():
    assert look.page_problems("teacher-wide", "Students\nAB12C working", []) == []
    wide = [("what is in the card panel", 37), ('div.w-big ("wide thing")', 412)]
    assert look.page_problems("teacher-phone", "Students", wide) == [
        "teacher-phone: what is in the card panel runs 37px off the side",
        'teacher-phone: div.w-big ("wide thing") runs 412px off the side',
    ]
    # Only the first few of a page's, so that one wide table does not bury the rest.
    assert len(look.page_problems("research-phone", "", [("a box", 9)] * 10)) == look.MOST_WIDE
    # What the page measured, in words: a box by what is in it, anything past the right edge
    # by its tag and first words.
    measured = [["box", "the card panel", "", 37], ["edge", "div.w-big", " wide\n  thing ", 412]]
    assert look.wide_things([*measured, ["edge", "img.photo", "", 5]]) == [
        ("what is in the card panel", 37),
        ('div.w-big ("wide thing")', 412),
        ("img.photo", 5),
    ]
    em, en = chr(0x2014), chr(0x2013)
    [dash] = look.page_problems("research-wide", f"Linear equations {em} both sides{en}ish", [])
    assert dash.startswith("research-wide: a long dash in ") and "[long dash]" in dash
    # The problem itself holds no long dash: it goes into a report written without them.
    assert em not in dash and en not in dash
    # An en dash alone counts too.
    assert len(look.page_problems("lesson-phone", f"9{en}10 minutes", [])) == 1
    # A pupil is on the class view only under their whole name.
    shown = "AB12C working\nZX9-01 finished"
    assert look.missing_pupils(shown, ["AB12C", "ZX9-01", "B12C", "ZX9-0"]) == ["B12C", "ZX9-0"]
    assert look.missing_pupils(shown, []) == []


def a_look(tmp_path: Path, key: str = KEY) -> look.Look:
    return look.Look("http://127.0.0.1:3002", "http://127.0.0.1:8010", "ms-amari", key, tmp_path)


def test_a_request_the_pages_tried_to_send_fails_the_look(tmp_path):
    seen = a_look(tmp_path)
    seen.pages.append({"name": "teacher-wide", "path": "/teacher", "problems": []})
    assert seen.report()["passed"] is True
    seen.stopped += ["POST /api/teacher/thread/actions", "POST /api/teacher/thread/actions"]
    report = seen.report()
    assert report["passed"] is False
    assert report["problems"] == [
        "the pages tried to send what is not a read, and it was stopped before it left the "
        "browser: POST /api/teacher/thread/actions"
    ]


def test_the_look_says_whether_it_saw_the_research_pages(tmp_path):
    seen = a_look(tmp_path)
    seen.research_opened += [True, True, True, True]
    assert seen.report()["research_seen"] is True
    seen.research_opened.append(False)
    assert seen.report()["research_seen"] is False
    # With no key it never sees them, whatever else it read.
    unkeyed = a_look(tmp_path, key="")
    unkeyed.research_opened.append(True)
    assert unkeyed.report()["research_seen"] is False
    assert unkeyed.report()["research"] == "not opened: no research key set"


def test_the_key_is_taken_out_of_every_problem_before_anything_is_written(tmp_path):
    seen = a_look(tmp_path)
    seen.note(seen.problems, f"research-wide: the look at this page stopped: fill({KEY})")
    seen.pages.append({"name": "research-wide", "path": "/research", "problems": [f"typed {KEY}"]})
    seen.problems.append(f"lesson-wide: also {KEY}")
    report = seen.report()
    # Taken out where each problem is made, and again over the whole report.
    assert KEY not in seen.problems[0] and "[research key]" in seen.problems[0]
    assert KEY not in json.dumps(report) and json.dumps(report).count("[research key]") == 3


def test_the_look_never_writes_or_says_the_key_whatever_stops_it(tmp_path, monkeypatch, capsys):
    """However the look ends, look.json and what it prints hold no research key."""

    def run(self) -> None:
        self.problems.append(f"teacher-wide: something odd with {KEY}")
        self.pages.append({"name": "teacher-wide", "path": "/teacher", "problems": [f"odd {KEY}"]})
        raise RuntimeError(f"Locator.fill: Timeout 30000ms exceeded filling {KEY}")

    monkeypatch.setattr(look.Look, "run", run)
    monkeypatch.setenv(look.KEY_ENV, KEY)
    argv = ["look.py", "http://127.0.0.1:3999", "http://127.0.0.1:3998", "ms-amari", str(tmp_path)]

    assert look.main(argv) == 1

    written = (tmp_path / "look.json").read_text(encoding="utf-8")
    said = capsys.readouterr()
    assert KEY not in written and KEY not in said.out and KEY not in said.err
    report = json.loads(written)
    assert report["passed"] is False and len(report["problems"]) == 2
    assert report["problems"][-1].startswith("the look stopped: RuntimeError: ")


def test_the_look_refuses_the_live_site_and_an_api_at_the_websites_address(
    tmp_path, monkeypatch, capsys
):
    started = []
    monkeypatch.setattr(look.Look, "run", lambda self: started.append(self.website))
    # Test addresses start the look: here it reads nothing, so it fails, and says so.
    test = ["look.py", "http://127.0.0.1:3002", "http://127.0.0.1:8010", "ms-amari", str(tmp_path)]
    assert look.main(test) == 1 and started == ["http://127.0.0.1:3002"]
    (tmp_path / "look.json").unlink()
    for website, api in (
        ("http://127.0.0.1:3000", "http://127.0.0.1:8010"),
        ("http://127.0.0.1:3002", "http://127.0.0.1:8000"),
        ("http://localhost:3002", "http://127.0.0.1:8010"),
        ("http://127.0.0.1:3002", "http://127.0.0.1:3002"),
    ):
        assert look.main(["look.py", website, api, "ms-amari", str(tmp_path)]) == 2
    assert started == ["http://127.0.0.1:3002"]
    assert not (tmp_path / "look.json").exists()
