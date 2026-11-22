"""The runner: the one command that runs a school day. It keeps to the guards, starts the test
API, reads the money before each part, plays Part 1 (the full class) and Part 2 (three groups at
once), runs the probes, collects the records, runs the checks and writes the report.

Here the day runs in this process against a `Venue` on the app, with no server and no model:
the platform's scripted demo agent plays the tutor and the class agent, every pupil says the
move's canned line, nobody thinks before a move, and a class is 3 pupils instead of 30. Each
request gets a database session of its own from the app's pool, as on a server, so the pupils
really work side by side.
"""

import asyncio
import json
import uuid
from datetime import datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import db as app_db
from app.agent import llm
from app.agent.scripted import demo_responder
from app.config import get_settings
from app.db import get_session
from app.models import User
from bench.pupils import CannedWriter
from bench.school import checks, driver, run
from bench.school.checks import EVENTS, EVERY_EVENT, run_all
from bench.school.collect import RunData
from bench.school.report import REACHED_BY
from bench.school.run import Venue
from bench.school.teacher import NotDone

# How step 1 would open, which the demo agent does not write: the preview's answer here.
OPENS = {"message": "Hi! Let's start: solve 3x + 4 = 19.", "move": "ask"}
# The look at the website is never started here: a stand-in notes what it was asked.
LOOKED = {"probe": "look", "passed": True, "reachable": True, "research_seen": False, "detail": ""}


@pytest.fixture
async def venue(app, engine, monkeypatch):
    """The app in this process as the runner's venue: demo sign-in on, the cookie doing the work,
    each request on a database session of its own, and the runner's waits made short."""
    app.dependency_overrides.pop(get_session)
    monkeypatch.setattr(get_settings(), "demo_sign_in", True)
    monkeypatch.setattr(get_settings(), "dev_identity_enabled", False)
    monkeypatch.setattr(run, "POLL_S", 0.01)
    monkeypatch.setattr(run, "NO_ANSWER_WAIT_S", 0)
    monkeypatch.setattr(run, "SUMMARY_RETRY_S", 0)

    # The app's own failures come back as 500s, as from a server.
    def browsers() -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60)

    yield Venue("http://test", browsers, async_sessionmaker(engine, expire_on_commit=False))
    await app_db.get_engine().dispose()


@pytest.fixture
def previews(app) -> None:
    """The demo agent, which also writes how step 1 would open for a preview."""

    def agent(purpose: str, system: str, messages: list[dict]) -> dict:
        if purpose == "student_preview":
            return OPENS
        return demo_responder(purpose, system, messages)

    scripted = llm.ScriptedClient(agent)
    app.dependency_overrides[llm.get_llm_client] = lambda: scripted


@pytest.fixture
def looks(monkeypatch) -> list[tuple]:
    """Each look the runner asks for, in place of the browser look itself."""
    asked: list[tuple] = []

    async def look(website, api, teacher, folder):
        asked.append((website, api, teacher, folder))
        return dict(LOOKED)

    monkeypatch.setattr(run, "run_look", look)
    return asked


async def a_day(venue, folder, *args: str, size: int = 3) -> tuple[int, dict]:
    """Runs the day in this process with these arguments, and returns its exit code and what it
    saved in results.json."""
    opts = run.parse([*args, "--out", str(folder)])
    code = await run.run_day(
        venue,
        opts,
        writer_factory=lambda brief, voice: CannedWriter(),
        think=(0, 0),
        size=size,
    )
    return code, json.loads((folder / "results.json").read_text(encoding="utf-8"))


def lesson(saved: dict, key: str) -> dict:
    [found] = [x for x in saved["data"]["lessons"] if x["key"] == key]
    return found


def result(saved: dict, code: str) -> dict:
    [found] = [r for r in saved["results"] if r["code"] == code]
    return found


def events(saved: dict, what: str) -> list[dict]:
    return [e for e in saved["data"]["events"] if e.get("what") == what]


async def test_a_free_run_of_part_two_group_c_writes_a_report(venue, tmp_path, looks):
    code, saved = await a_day(venue, tmp_path, "--part", "2", "--only", "C", "--free")

    assert code in (0, 1)
    assert (tmp_path / "report.html").is_file()
    assert len(saved["results"]) == 55
    meta = saved["meta"]
    assert meta["free"] is True and meta["parts_run"] == ["2"] and not meta["parts_not_run"]
    poem = lesson(saved, "c-english")
    assert uuid.UUID(poem["session_id"]) and poem["drafted"]["lesson_id"]
    assert poem["subject"] == "English" and poem["teacher"].startswith("sd-c-")
    assert poem["steps"] == len(poem["brief"]["steps"]) and poem["age"] == 12
    # The poem went up with the lesson, the pupils worked, and the lesson was summed up.
    assert [(e["file"], e["status"]) for e in events(saved, "upload")] == [("poem.txt", 201)]
    assert any(s["status"] == 200 and s["text"] for s in saved["data"]["sent"])
    assert len(events(saved, "summary")) == 1 and events(saved, "confirmed")
    # The teacher deleted what is remembered, and the count read straight after was 0; the
    # lines written before it were kept for the checks.
    probes = [e for e in saved["data"]["events"] if e.get("probe") == "memory_after_forget"]
    assert probes == [{"probe": "memory_after_forget", "students": 0}]
    assert any(saved["data"]["note_lines"].values())
    assert result(saved, "M5")["outcome"] == "pass"
    # A draft run keeps the briefs, and only Part 1's teacher is looked at.
    briefs = json.loads((tmp_path / "briefs.json").read_text(encoding="utf-8"))
    assert briefs["c-english"] == poem["brief"]
    assert looks == []


async def test_part_two_runs_the_three_groups_and_probes_privacy_between_a_and_b(
    venue, tmp_path, looks
):
    code, saved = await a_day(venue, tmp_path, "--part", "2", "--free")

    ran = [x["key"] for x in saved["data"]["lessons"] if x["session_id"]]
    assert ran == ["a-maths", "a-english", "a-maths-2", "b-history", "b-science", "c-english"]
    teachers = {x["teacher"].rsplit("-", 1)[0] for x in saved["data"]["lessons"]}
    assert teachers == {"sd-a", "sd-b", "sd-c"}
    # Every privacy probe was tried, as the wrong user, and refused.
    tried = [e for e in saved["data"]["events"] if e.get("probe") in ("x1", "x2", "x3")]
    assert [e["probe"] for e in tried] == ["x1"] * 5 + ["x2"] * 2 + ["x3"] * 2
    assert all(e["status"] in (403, 404) for e in tried)
    for code_ in ("X1", "X2", "X3", "M4"):
        assert result(saved, code_)["outcome"] == "pass", code_
    assert code in (0, 1)


async def test_a_part_that_cannot_be_afforded_is_not_run_and_the_report_says_so(
    venue, tmp_path, monkeypatch, capsys, db
):
    asked = []

    async def remaining() -> float:
        asked.append(True)
        return 20.0

    monkeypatch.setattr(run, "remaining", remaining)
    code, saved = await a_day(venue, tmp_path, "--part", "2", "--floor", "15")

    assert asked
    meta = saved["meta"]
    assert list(meta["parts_not_run"]) == ["2"] and meta["parts_run"] == []
    assert meta["free"] is False and meta["cost"] == 0.0
    assert saved["data"]["lessons"] == [] and (tmp_path / "report.html").is_file()
    said = capsys.readouterr().out
    assert (
        "Not enough left on the key for Part 2: $20.00 left, about $9.00 needed, floor $15.00."
        in said
    )
    # Nobody signed in: the part never started.
    assert await db.scalar(select(func.count(User.id))) == 0
    assert code == 0


async def test_a_lesson_that_was_not_drafted_does_not_stop_the_others(venue, app, tmp_path, looks):
    """The class agent only asks about Group A's first lesson, through the words and both
    nudges: that lesson is recorded as not drafted, with the reason, and the other two run."""
    asked_about_teaching = 0

    def agent(purpose: str, system: str, messages: list[dict]) -> dict:
        nonlocal asked_about_teaching
        if purpose == "teacher_thread" and asked_about_teaching < 3:
            asked_about_teaching += 1
            return {"reply": "Should the money problems use pounds or euros?", "show": "nothing"}
        return demo_responder(purpose, system, messages)

    scripted = llm.ScriptedClient(agent)
    app.dependency_overrides[llm.get_llm_client] = lambda: scripted
    code, saved = await a_day(venue, tmp_path, "--part", "2", "--only", "A", "--free")

    first = lesson(saved, "a-maths")
    assert first["session_id"] == "" and first["drafted"]["lesson_id"] is None
    assert "did not draft" in first["drafted"]["reason"]
    for key in ("a-english", "a-maths-2"):
        assert uuid.UUID(lesson(saved, key)["session_id"])
    c1 = result(saved, "C1")
    assert c1["outcome"] == "fail"
    # The demo agent drafts the others by their wording, so it may count their steps wrong too.
    [not_drafted] = [e for e in c1["evidence"] if e["lesson"] == "a-maths"]
    assert "did not draft" in not_drafted["note"]
    assert code in (0, 1)


async def test_a_crash_after_part_one_keeps_part_one_and_names_part_two_not_run(
    venue, tmp_path, monkeypatch, looks, capsys, previews
):
    async def falls_over(*args, **kwargs):
        raise RuntimeError("the groups' teachers could not be signed in")

    monkeypatch.setattr(run, "run_part_two", falls_over)
    code, saved = await a_day(venue, tmp_path, "--part", "all", "--free")

    assert code == 2
    meta = saved["meta"]
    assert meta["parts_run"] == ["1", "2"]
    assert list(meta["parts_not_run"]) == ["2"]
    assert meta["parts_not_run"]["2"].startswith("stopped partway: RuntimeError")
    full = lesson(saved, "full-class")
    assert uuid.UUID(full["session_id"]) and full["teacher"].startswith("sd-maths-")
    assert any(s["session_id"] == full["session_id"] for s in saved["data"]["sent"])
    assert any("could not be signed in" in e for e in saved["data"]["errors"])
    # What ran is still probed: the research pages and the look at Part 1's class view.
    assert len(looks) == 1
    assert any(e.get("probe") == "research" for e in saved["data"]["events"])
    assert (tmp_path / "report.html").is_file()
    # Only the report's path and the counts are printed.
    printed = capsys.readouterr().out
    assert str(tmp_path / "report.html") in printed


async def test_saved_lessons_seed_the_same_briefs(venue, tmp_path, monkeypatch, looks):
    drafted_in, seeded_in = tmp_path / "drafted", tmp_path / "seeded"
    await a_day(venue, drafted_in, "--part", "2", "--only", "C", "--free")
    briefs = json.loads((drafted_in / "briefs.json").read_text(encoding="utf-8"))

    # A later run, with teachers of its own.
    monkeypatch.setattr(run, "_stamp", lambda: "12312359")
    args = ["--part", "2", "--only", "C", "--free", "--lessons", "saved"]
    _, saved = await a_day(venue, seeded_in, *args, "--saved-from", str(drafted_in))

    poem = lesson(saved, "c-english")
    assert uuid.UUID(poem["session_id"]) and poem["drafted"] is None
    assert poem["teacher"] == "sd-c-12312359"
    assert poem["brief"] == briefs["c-english"]
    # Nothing was drafted or uploaded, so the drafting checks did not come up.
    assert result(saved, "C1")["outcome"] == "did not come up"
    assert result(saved, "C2")["outcome"] == "did not come up"
    assert events(saved, "upload") == []
    assert not (seeded_in / "briefs.json").exists()
    # The poem was attached when drafting, which seeding does not do, and the report says so.
    page = (seeded_in / "report.html").read_text(encoding="utf-8")
    assert "its files (poem.txt) were not given to the tutor" in page


async def test_part_one_logs_the_teacher_in_the_shapes_the_checks_read(
    venue, tmp_path, monkeypatch, looks, previews
):
    """With the teacher's waits taken to nothing, every step of Part 1's teacher happens while
    the pupils work, and every action is logged with the keys checks.EVENTS names."""
    for name in ("VIEW_EVERY_S", "ASK_AFTER_S", "PAUSE_S"):
        monkeypatch.setattr(run, name, 0)
    monkeypatch.setitem(driver._RETRIES, "paused", (0.01, 1000))
    opts = run.parse(["--part", "1", "--free", "--out", str(tmp_path)])
    await run.run_day(
        venue, opts, writer_factory=lambda brief, voice: CannedWriter(), think=(0.1, 0.1), size=3
    )
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))

    teacher = [e for e in saved["data"]["events"] if e.get("what") in EVENTS]
    for event in teacher:
        assert set(EVERY_EVENT + EVENTS[event["what"]]) <= set(event), event
        assert datetime.fromisoformat(event["at"]).tzinfo is not None
    done = {e["what"] for e in teacher}
    assert {"asked", "teacher paused", "teacher resumed", "extended", "summary"} <= done
    assert {"confirmed", "result seen"} <= done
    questions = [e["question"] for e in events(saved, "asked")]
    assert questions == ["Who needs me right now?", "How many of them finished?"]
    [extended] = events(saved, "extended")
    gap = datetime.fromisoformat(extended["closes_after"]) - datetime.fromisoformat(
        extended["closes_before"]
    )
    assert gap.total_seconds() == 600
    assert all(
        e["done"] for e in events(saved, "teacher paused") + events(saved, "teacher resumed")
    )
    # Before running, the lesson was previewed and put in its unit.
    [previewed] = events(saved, "previewed")
    assert previewed["status"] == 200 and previewed["card"]
    [unit] = events(saved, "unit set")
    assert (unit["text"], unit["unit"]) == ("Equations", "Equations")
    assert saved["data"]["view_seconds"]
    # The look was asked of Part 1's teacher, on the venue's API.
    [(website, api, name, _)] = looks
    assert (website, api) == ("http://127.0.0.1:3002", "http://test")
    assert name.startswith("sd-maths-")
    assert result(saved, "C14")["outcome"] == "pass"


def test_the_command_refuses_the_live_port(monkeypatch, tmp_path, capsys):
    started = []
    monkeypatch.setattr(run, "test_server", lambda **kwargs: started.append(kwargs))
    for website in ("http://127.0.0.1:3000", "http://127.0.0.1:8000"):
        args = ["--part", "1", "--free", "--website", website, "--out", str(tmp_path)]
        assert asyncio.run(run.main(args)) == 2
    assert started == []
    assert "the live site" in capsys.readouterr().out


def test_every_check_has_the_part_that_reaches_it():
    empty = RunData(**{name: [] for name in RunData.__dataclass_fields__})
    empty.note_lines, empty.evidence_subject, empty.cast = {}, {}, {}
    codes = [r.code for r in run_all(empty)]
    assert len(codes) == 55
    assert set(codes) <= set(REACHED_BY)
    # A check that stops with an error is named by its function, so the names must be the codes.
    from bench.school.checks_extra import EXTRA_CHECKS

    every = (*checks.TEACHING_CHECKS, *checks.SCHOOL_CHECKS, *EXTRA_CHECKS)
    assert [check.__name__.upper() for check in every] == codes


async def test_a_check_that_raises_fails_with_its_error_and_the_others_still_run(
    venue, tmp_path, monkeypatch, looks
):
    def s1(data):
        raise KeyError("pupil")

    # S1 counts in a free run, so its failing fails the run.
    school = [s1 if check.__name__ == "s1" else check for check in checks.SCHOOL_CHECKS]
    monkeypatch.setattr(checks, "SCHOOL_CHECKS", school)
    code, saved = await a_day(venue, tmp_path, "--part", "2", "--only", "C", "--free")

    assert len(saved["results"]) == 55
    broken = result(saved, "S1")
    assert broken["outcome"] == "fail" and broken["title"] == checks.WORDS["S1"][0]
    assert "KeyError" in broken["detail"] and "could not be worked out" in broken["detail"]
    assert result(saved, "M5")["outcome"] == "pass"
    assert (tmp_path / "report.html").is_file()
    assert code == 1


async def test_the_raw_logs_are_saved_before_the_records_are_read(
    venue, tmp_path, monkeypatch, looks, capsys
):
    async def falls_over(*args, **kwargs):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(run, "collect", falls_over)
    opts = run.parse(["--part", "2", "--only", "C", "--free", "--out", str(tmp_path)])
    code = await run.run_day(
        venue, opts, writer_factory=lambda brief, voice: CannedWriter(), think=(0, 0), size=3
    )

    assert code == 2
    raw = json.loads((tmp_path / "raw.json").read_text(encoding="utf-8"))
    [log] = raw["logs"]
    assert log["key"] == "c-english" and log["sent"] and log["events"]
    [facts] = raw["lessons"]
    assert facts["session_id"] == log["session_id"] and facts["drafted"]["lesson_id"]
    assert {"probe": "memory_after_forget", "students": 0} in raw["probes"]
    assert raw["teacher_replies"] and isinstance(raw["captured_note_lines"], dict)
    assert "the database went away" in capsys.readouterr().out


async def test_a_class_view_that_fails_does_not_end_the_teachers_script(
    venue, tmp_path, monkeypatch, looks, previews
):
    for name in ("VIEW_EVERY_S", "ASK_AFTER_S", "PAUSE_S"):
        monkeypatch.setattr(run, name, 0)
    monkeypatch.setitem(driver._RETRIES, "paused", (0.01, 1000))
    real = run._class_card
    calls = 0

    async def once_broken(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise NotDone("POST /api/teacher/thread/actions", 500, "Internal Server Error")
        return await real(*args, **kwargs)

    monkeypatch.setattr(run, "_class_card", once_broken)
    opts = run.parse(["--part", "1", "--free", "--out", str(tmp_path)])
    await run.run_day(
        venue, opts, writer_factory=lambda brief, voice: CannedWriter(), think=(0.1, 0.1), size=3
    )
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))

    [failed] = events(saved, run.VIEW_NOT_READ)
    assert failed["status"] == 500 and failed["session_id"]
    # The teacher carried on with every step after it.
    done = {e.get("what") for e in saved["data"]["events"]}
    assert {"asked", "teacher paused", "teacher resumed", "extended"} <= done
    assert not any("teacher: stopped by" in e for e in saved["data"]["errors"])


async def test_a_class_view_that_fails_still_lets_group_a_be_guided(
    venue, tmp_path, monkeypatch, looks
):
    monkeypatch.setattr(run, "GUIDE_AFTER_S", 0)

    async def broken(*args, **kwargs):
        raise httpx.ReadTimeout("The read timed out.")

    monkeypatch.setattr(run, "_class_card", broken)
    _, saved = await a_day(venue, tmp_path, "--part", "2", "--only", "A", "--free", size=6)

    assert events(saved, run.VIEW_NOT_READ)
    [guided] = events(saved, "guided")
    target = [p for p, who in saved["data"]["cast"].items() if who["guide_target"]]
    assert [guided["pupil"]] == target


async def test_what_the_agents_write_about_pupils_is_read_for_s4(venue, tmp_path, looks):
    _, saved = await a_day(venue, tmp_path, "--part", "2", "--only", "C", "--free")

    replies = saved["data"]["teacher_replies"]
    # The demo agent's summary, and the keep and develop lines of each pupil's outcome.
    assert "(Demo agent.) Lesson summary based on step judgments." in replies
    assert "Kept going through the activity." in replies
    assert "Explain reasons in full sentences." in replies


async def test_a_summary_the_agent_could_not_write_is_asked_for_again(venue, app, tmp_path, looks):
    reviews = 0

    def agent(purpose: str, system: str, messages: list[dict]) -> dict:
        nonlocal reviews
        if purpose == "lesson_review":
            reviews += 1
            if reviews == 1:
                raise llm.LLMError("The model is busy.")
        return demo_responder(purpose, system, messages)

    scripted = llm.ScriptedClient(agent)
    app.dependency_overrides[llm.get_llm_client] = lambda: scripted
    _, saved = await a_day(venue, tmp_path, "--part", "2", "--only", "C", "--free")

    assert [e["status"] for e in events(saved, "summary")] == [503, 200]
    assert events(saved, "confirmed")


async def test_part_two_is_held_to_what_part_one_really_cost(
    venue, tmp_path, monkeypatch, looks, previews, capsys
):
    """Part 1 cost $24, three times its estimate, so Part 2 is reckoned at three times its own:
    $27, which $40 left cannot cover above a $15 floor (the plain $9 could)."""
    balances = iter([64.0, 40.0, 40.0, 40.0])

    async def remaining() -> float:
        return next(balances)

    monkeypatch.setattr(run, "remaining", remaining)
    _, saved = await a_day(venue, tmp_path, "--part", "all")

    meta = saved["meta"]
    assert meta["parts_run"] == ["1"] and list(meta["parts_not_run"]) == ["2"]
    assert meta["cost_by_part"] == {"1": 24.0} and meta["cost"] == 24.0
    assert (
        "Not enough left on the key for Part 2: $40.00 left, about $27.00 needed, floor $15.00."
        in capsys.readouterr().out
    )


def test_the_default_folder_names_the_time_and_is_never_reused(monkeypatch, tmp_path, capsys):
    name = run._default_folder().name
    assert name.startswith("school-day-") and len(name) == len("school-day-2026-11-22-1630")
    used = tmp_path / "school-day-2026-11-22-1630"
    used.mkdir()
    (used / "report.html").write_text("an earlier run", encoding="utf-8")
    started = []
    monkeypatch.setattr(run, "test_server", lambda **kwargs: started.append(kwargs))
    monkeypatch.setattr(run, "_default_folder", lambda: used)

    assert asyncio.run(run.main(["--part", "1", "--free"])) == 2
    assert started == []
    assert "already holds" in capsys.readouterr().out
    assert (used / "report.html").read_text(encoding="utf-8") == "an earlier run"
