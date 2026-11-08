"""The study: assigned conditions, the fixed ladder, honest measurement, the researcher's view."""

# ruff: noqa: F811 - `lesson` is a fixture imported from the student agent tests

import csv
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import research, study
from app.agent.llm import ScriptedClient
from app.agent.student_mode import HELD_BACK
from app.config import get_settings
from app.enums import ExceptionKind, MessageRole
from app.models import AgentTurn, Exception_, Message, SessionParticipant
from tests.test_agent_student import lesson, say, turn  # noqa: F401 - `lesson` is a fixture

ASKS = turn("What did you try?", rung="diagnostic_question")


@pytest.fixture
def in_study(monkeypatch):
    monkeypatch.setattr(get_settings(), "study_active", True)


def test_the_ladder_goes_one_rung_per_answer_and_stops_short_of_the_solution():
    rungs = [study.permitted_rung(n, full_allowed=False) for n in range(9)]
    assert rungs[:3] == ["attempt", "diagnostic_question", "conceptual_cue"]
    assert rungs[-1] == "partial_step"
    assert study.permitted_rung(9, full_allowed=True) == "full_solution"


def test_assignment_is_a_crossover_that_can_be_rederived():
    student = uuid.uuid4()
    first, second = study.condition_for(student, 0), study.condition_for(student, 1)
    assert first["memory"] is not second["memory"]
    assert first == study.condition_for(student, 0)
    arms = {study.condition_for(uuid.uuid4(), 0)["memory"] for _ in range(40)}
    assert arms == {True, False}


async def test_outside_a_study_nothing_is_assigned(db, lesson):
    client = ScriptedClient([turn("Hi! Solve 3x + 4 = 19.")])
    await say(db, lesson, client, None)
    assert (await db.scalars(select(SessionParticipant.condition))).all() == [{}, {}]
    assert "Help ladder" not in client.calls[0]["system"]


async def test_in_a_study_the_condition_is_assigned_and_travels_with_every_turn(
    db,
    lesson,
    in_study,
):
    client = ScriptedClient([turn("Hi! Solve 3x + 4 = 19.")])
    await say(db, lesson, client, None)
    recorded = (await db.scalars(select(AgentTurn))).one().context_manifest["condition"]
    assert recorded == study.condition_for(lesson.alice.id, 0)
    assert recorded["policy"] == "ladder"


async def test_help_off_the_ladder_is_redrafted_and_the_first_draft_is_kept(
    db,
    lesson,
    in_study,
):
    wrong = {"student_attempted": True, "assessment": {"judgment": "not_met"}}
    client = ScriptedClient(
        [
            turn("Subtract 4 from both sides first.", move="hint", rung="targeted_hint", **wrong),
            turn("What did you do to the 4?", move="clarify", rung="diagnostic_question", **wrong),
        ]
    )
    result = await say(db, lesson, client, "x = 7")
    assert result.reply.text == "What did you do to the 4?"
    assert "diagnostic_question" in client.calls[0]["system"]
    recorded = (await db.scalars(select(AgentTurn))).one()
    assert recorded.conflicts == ["off_ladder"]
    assert recorded.context_manifest["rung_permitted"] == "diagnostic_question"


async def test_a_right_answer_needs_no_rung(db, lesson, in_study):
    client = ScriptedClient(
        [
            turn(
                "Yes! Next one.",
                move="advance",
                student_attempted=True,
                assessment={"judgment": "met"},
            )
        ]
    )
    await say(db, lesson, client, "x = 5, I took 4 off and divided by 3")
    assert (await db.scalars(select(AgentTurn))).one().conflicts == []


async def test_an_answer_to_a_later_step_counts_as_a_leak(db, lesson):
    brief = dict(lesson.contract.brief)
    brief["steps"] = [dict(s) for s in brief["steps"]]
    brief["steps"][1]["reference_answer"] = "x = 12"
    lesson.contract.brief = brief
    await db.commit()
    client = ScriptedClient(
        [turn("Good try. By the way, for the next one the answer is x = 12."), turn("Try again?")]
    )
    result = await say(db, lesson, client, "is it 6?")
    assert result.reply.text == "Try again?"
    recorded = (await db.scalars(select(AgentTurn))).one()
    assert recorded.conflicts == ["answer_leakage"]
    assert recorded.leakage_check == "failed"


async def test_a_held_back_reply_reaches_the_teachers_queue(db, lesson):
    leak = turn("The answer is 5.", disclosure="full")
    result = await say(db, lesson, ScriptedClient([leak, leak]), "just tell me")
    assert result.reply.text == HELD_BACK
    kinds = (await db.scalars(select(Exception_.kind))).all()
    assert ExceptionKind.POLICY_CONFLICT.value in kinds


async def test_with_enforcement_off_the_reply_goes_out_and_the_conflict_is_still_recorded(
    db,
    lesson,
    in_study,
    monkeypatch,
):
    monkeypatch.setattr(get_settings(), "study_supervisor", False)
    client = ScriptedClient([turn("The answer is 5.", disclosure="full", rung="full_solution")])
    result = await say(db, lesson, client, "just tell me")
    assert result.reply.text == "The answer is 5."
    assert not result.withheld
    recorded = (await db.scalars(select(AgentTurn))).one()
    assert {"over_disclosure", "answer_leakage", "off_ladder"} <= set(recorded.conflicts)


async def test_the_export_leaves_words_out_unless_asked(db, lesson, in_study, tmp_path):
    await say(db, lesson, ScriptedClient([ASKS]), "my secret sentence")
    counts = await research.export(db, tmp_path)
    assert counts["turns"] == 1 and "messages" not in counts
    with (tmp_path / "turns.csv").open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["student"] == lesson.alice.pseudonym
    assert row["memory"] in ("True", "False") and row["policy"] == "ladder"
    assert "my secret sentence" not in (tmp_path / "evidence.csv").read_text(encoding="utf-8")

    await research.export(db, tmp_path, with_text=True)
    assert "my secret sentence" in (tmp_path / "messages.csv").read_text(encoding="utf-8")


async def test_the_summary_counts_by_arm_and_holds_no_words(db, lesson, in_study):
    await say(db, lesson, ScriptedClient([ASKS]), "my secret sentence")
    found = await research.summary(db)
    assert found["study"]["active"] is True
    (arm,) = found["lessons"][0]["arms"]
    assert arm["arm"] in ("memory on", "memory off") and arm["turns"] == 1
    assert "my secret sentence" not in str(found)


async def test_purge_deletes_only_what_is_past_its_date(db, lesson):
    await say(db, lesson, ScriptedClient([turn("What did you try?")]), "hello")
    assert (await research.purge(db))["messages"] == 0
    later = datetime.now(UTC) + timedelta(days=4000)
    assert (await research.purge(db, now=later))["messages"] >= 2
    assert (await db.scalars(select(Message))).all() == []


async def test_the_researcher_page_does_not_exist_without_the_key(client, monkeypatch):
    assert (await client.get("/api/research/summary")).status_code == 404
    monkeypatch.setattr(get_settings(), "research_key", "open-sesame")
    assert (await client.get("/api/research/summary")).status_code == 404
    ok = await client.get("/api/research/summary", headers={"X-Research-Key": "open-sesame"})
    assert ok.status_code == 200 and "lessons" in ok.json()


async def test_confirming_the_answer_the_student_just_gave_is_not_a_leak(db, lesson):
    client = ScriptedClient(
        [
            turn(
                "Yes! x = 5. On to the next one.",
                move="advance",
                student_attempted=True,
                assessment={"judgment": "met"},
            )
        ]
    )
    result = await say(db, lesson, client, "3x = 15 so x = 5")
    assert result.reply.text.startswith("Yes!")
    assert (await db.scalars(select(AgentTurn))).one().conflicts == []


async def test_wipe_empties_the_demo_database(db, lesson):
    await say(db, lesson, ScriptedClient([turn("What did you try?")]), "hello")
    await research.wipe(db)
    assert (await db.scalars(select(Message))).all() == []
    assert (await db.scalars(select(SessionParticipant))).all() == []


async def test_the_export_blanks_student_quotes_inside_assessments(db, lesson, tmp_path):
    client = ScriptedClient(
        [
            turn(
                "Not quite.",
                student_attempted=True,
                assessment={"judgment": "not_met", "evidence_quote": "my secret sentence"},
            )
        ]
    )
    await say(db, lesson, client, "my secret sentence")
    await research.export(db, tmp_path)
    text = (tmp_path / "evidence.csv").read_text(encoding="utf-8")
    assert "not_met" in text and "my secret sentence" not in text


async def test_outside_a_study_enforcement_can_be_switched_off(db, lesson, monkeypatch):
    monkeypatch.setattr(get_settings(), "supervisor_enforce", False)
    client = ScriptedClient([turn("The answer is 5.", disclosure="full")])
    result = await say(db, lesson, client, "just tell me")
    assert result.reply.text == "The answer is 5." and not result.withheld
    assert "answer_leakage" in (await db.scalars(select(AgentTurn))).one().conflicts


async def test_the_records_and_the_instructions_can_be_fetched_with_the_key(
    client, lesson, monkeypatch
):
    import io
    import zipfile

    monkeypatch.setattr(get_settings(), "research_key", "open-sesame")
    headers = {"X-Research-Key": "open-sesame"}
    assert (await client.get("/api/research/export")).status_code == 404
    zipped = await client.get("/api/research/export", headers=headers)
    assert zipped.status_code == 200
    names = set(zipfile.ZipFile(io.BytesIO(zipped.content)).namelist())
    assert {"turns.csv", "evidence.csv", "alerts.csv"} <= names
    told = (await client.get("/api/research/instructions", headers=headers)).json()
    assert "class agent" in told["student"] and "class agent" in told["teacher"]


async def test_every_turn_can_be_read_back_with_the_key(client, db, lesson, monkeypatch):
    """What the student said, what the agent was shown and replied, and the server's checks."""
    await say(db, lesson, ScriptedClient([turn("What do you do first?")]), "is it 5")
    monkeypatch.setattr(get_settings(), "research_key", "open-sesame")
    url = f"/api/research/turns?session_id={lesson.session.id}"
    assert (await client.get(url)).status_code == 404
    found = (await client.get(url, headers={"X-Research-Key": "open-sesame"})).json()
    [one] = found["turns"]
    assert one["said"] == "is it 5" and one["mode"] == "student"
    assert one["reply"]["message"] == "What do you do first?"
    assert one["shown"]["session_id"] == str(lesson.session.id)
    assert one["leakage"] and one["outcome"]


async def test_a_signed_in_teacher_opens_the_research_view_and_a_student_never_does(
    client, lesson, monkeypatch
):
    monkeypatch.setattr(get_settings(), "research_key", "open-sesame")
    assert (await client.get("/api/research/summary")).status_code == 404
    teacher = {"X-GenAI4ED-Pseudonym": lesson.teacher.pseudonym}
    assert (await client.get("/api/research/summary", headers=teacher)).status_code == 200
    student = {"X-GenAI4ED-Pseudonym": lesson.alice.pseudonym}
    for path in ("/summary", f"/lessons/{lesson.session.id}", "/turns", "/instructions"):
        assert (await client.get("/api/research" + path, headers=student)).status_code == 404


async def test_the_research_pages_read_a_lesson_back_in_words(db, lesson, client, monkeypatch):
    await say(
        db,
        lesson,
        ScriptedClient([turn("Try 3x + 4 = 19.", move="hint", disclosure="hint")]),
        "help",
    )
    reply = (await db.scalars(select(Message).where(Message.role == "agent"))).first()
    reply.data = {**reply.data, "helped": True}
    await db.commit()
    monkeypatch.setattr(get_settings(), "research_key", "open-sesame")
    key = {"X-Research-Key": "open-sesame"}

    whole = (await client.get("/api/research/summary", headers=key)).json()
    (row,) = whole["lessons"]
    assert (row["turns"], row["hints"], row["took_part"], row["answers_given"]) == (1, 1, 1, 0)
    assert (row["helped"], row["not_helped"]) == (1, 0)
    assert whole["totals"]["students"] == 1 and row["condition"] == "No study"

    page = (await client.get(f"/api/research/lessons/{row['session_id']}", headers=key)).json()
    alice = next(s for s in page["students"] if s["took_part"])
    assert alice["pseudonym"] == "10B-01" and alice["hints"] == 1 and not alice["needs_look"]
    assert page["steps"] and page["checks"] == []

    talk = (
        await client.get(
            f"/api/research/lessons/{row['session_id']}/students/{alice['student_id']}",
            headers=key,
        )
    ).json()
    assert [i["kind"] for i in talk["items"]] == ["student", "agent"]
    assert (
        talk["items"][1]["disclosure"] == "hint" and talk["items"][1]["shown"]["mode"] == "student"
    )
    assert talk["steps"][0]["reached"] and talk["previous"] is None and talk["next"] is None
    assert "help" in talk["items"][0]["text"]
    assert talk["items"][1]["helped"] is True


async def test_a_teacher_sees_only_their_own_lessons_on_the_research_view(
    client, db, lesson, monkeypatch
):
    """Every teacher's research view is their own classes; the key opens everything."""
    await say(db, lesson, ScriptedClient([turn("What do you do first?")]), "is it 5")
    mine = {"X-GenAI4ED-Pseudonym": lesson.teacher.pseudonym}
    other = {"X-GenAI4ED-Pseudonym": lesson.other_teacher.pseudonym}
    sid = lesson.session.id

    summary = (await client.get("/api/research/summary", headers=mine)).json()
    assert [row["session_id"] for row in summary["lessons"]] == [str(sid)]
    assert (await client.get("/api/research/summary", headers=other)).json()["lessons"] == []

    for url in (
        f"/api/research/lessons/{sid}",
        f"/api/research/lessons/{sid}/students/{lesson.alice.id}",
        f"/api/research/turns?session_id={sid}",
    ):
        assert (await client.get(url, headers=mine)).status_code == 200, url
        assert (await client.get(url, headers=other)).status_code == 404, url

    monkeypatch.setattr(get_settings(), "research_key", "open-sesame")
    key = {"X-Research-Key": "open-sesame"}
    assert (await client.get(f"/api/research/lessons/{sid}", headers=key)).status_code == 200
    assert (await client.get("/api/research/summary", headers=key)).json()["lessons"]


async def test_the_export_a_teacher_downloads_holds_only_their_own_classes(client, db, lesson):
    import io
    import zipfile

    from app.models import LessonOutcome, Message

    await say(db, lesson, ScriptedClient([turn("What do you do first?")]), "is it 5")
    # A rated reply and a confirmed outcome with the teacher's own words about the pupil: the
    # most personal rows the export holds, so another teacher must not get them either.
    reply = (
        await db.scalars(select(Message).where(Message.role == MessageRole.AGENT.value))
    ).first()
    reply.data = {**reply.data, "helped": True, "rated_at": "2026-11-07T10:00:00Z"}
    db.add(
        LessonOutcome(
            session_id=lesson.session.id,
            student_id=lesson.alice.id,
            suggested={},
            suggested_total=3,
            confirmed_total=4,
            comment="Rushed the last step.",
            provider="scripted",
            model="scripted",
            prompt_version="review-v4",
        )
    )
    await db.commit()

    def rows_in(zipped, name: str) -> list[dict]:
        archive = zipfile.ZipFile(io.BytesIO(zipped.content))
        return list(csv.DictReader(io.StringIO(archive.read(name).decode())))

    files = ("lessons.csv", "participants.csv", "ratings.csv", "outcomes.csv")
    mine = await client.get(
        "/api/research/export?with_text=true",
        headers={"X-GenAI4ED-Pseudonym": lesson.teacher.pseudonym},
    )
    for name in files:
        assert {r["session_id"] for r in rows_in(mine, name)} == {str(lesson.session.id)}, name
    assert rows_in(mine, "outcomes.csv")[0]["comment"] == "Rushed the last step."
    other = await client.get(
        "/api/research/export?with_text=true",
        headers={"X-GenAI4ED-Pseudonym": lesson.other_teacher.pseudonym},
    )
    for name in files:
        assert rows_in(other, name) == [], name


async def test_reading_a_conversation_on_the_research_view_is_logged(client, db, lesson):
    """The teacher's card logs a transcript read; the research view must too."""
    from app.models import TeacherAccessLog

    await say(db, lesson, ScriptedClient([turn("What do you do first?")]), "is it 5")
    url = f"/api/research/lessons/{lesson.session.id}/students/{lesson.alice.id}"
    assert (
        await client.get(url, headers={"X-GenAI4ED-Pseudonym": lesson.teacher.pseudonym})
    ).status_code == 200
    rows = (
        await db.scalars(
            select(TeacherAccessLog).where(
                TeacherAccessLog.action == "transcript_drilldown",
                TeacherAccessLog.session_id == lesson.session.id,
                TeacherAccessLog.student_id == lesson.alice.id,
                TeacherAccessLog.teacher_id == lesson.teacher.id,
            )
        )
    ).all()
    assert len(rows) == 1 and rows[0].detail.get("via") == "research"


async def test_the_purge_takes_the_words_out_of_alerts_outcomes_and_summaries_too(db, lesson):
    """A wellbeing alert's summary, the note on a pupil and the class summary hold the
    pupil's words; past the work retention they lose them and keep their shape."""
    from app.models import ClassInsight, LessonOutcome

    sid, alice = lesson.session.id, lesson.alice
    db.add(
        Exception_(
            session_id=sid,
            student_id=alice.id,
            kind=ExceptionKind.SAFEGUARDING.value,
            priority=1,
            summary='Said "nobody at home cares what I do".',
        )
    )
    db.add(
        LessonOutcome(
            session_id=sid,
            student_id=alice.id,
            suggested={
                "criteria": [{"name": "Method", "points": 3, "max": 5, "reason": "Showed it"}],
                "keep": "You wrote x = 5 and said why.",
                "develop": ["Check the sign."],
            },
            suggested_total=3,
            confirmed={
                "criteria": [{"name": "Method", "points": 4, "max": 5, "reason": ""}],
                "keep": "You wrote x = 5 and said why.",
                "develop": ["Check the sign."],
            },
            confirmed_total=4,
            comment="Well done, Alice.",
            status="confirmed",
            provider="scripted",
            model="scripted",
            prompt_version="review-v4",
        )
    )
    db.add(
        ClassInsight(
            session_id=sid,
            summary="Most of the class said 'take 4 off' first.",
            items=[],
            model="scripted",
        )
    )
    await db.commit()

    kept = await research.purge(db, now=datetime.now(UTC) + timedelta(days=8))
    assert kept.get("alert_texts", 0) == 0 and kept.get("outcome_texts", 0) == 0
    gone = await research.purge(db, now=datetime.now(UTC) + timedelta(days=366))
    assert gone["alert_texts"] == 1 and gone["outcome_texts"] == 1 and gone["summaries"] == 1

    alert = (await db.scalars(select(Exception_))).one()
    assert alert.summary == "" and alert.kind == ExceptionKind.SAFEGUARDING.value
    outcome = (await db.scalars(select(LessonOutcome))).one()
    assert outcome.confirmed_total == 4 and outcome.confirmed["criteria"][0]["points"] == 4
    assert outcome.comment is None
    for note in (outcome.suggested, outcome.confirmed):
        assert note["keep"] == "" and note["develop"] == []
        assert all(c.get("reason", "") == "" for c in note["criteria"])
    insight = (await db.scalars(select(ClassInsight))).one()
    assert insight.summary == ""


async def test_a_pupil_who_only_opened_the_lesson_did_not_take_part(db, lesson, client):
    """The research view counts who took part as the board does: wrote, or pressed a help
    button. The agent's opening alone is not taking part."""
    from tests.test_agent_student import StudentAgent

    opening = ScriptedClient([turn("Hi! Solve 3x + 4 = 19.", task="Solve 3x + 4 = 19")])
    await StudentAgent(opening).respond(
        db, session=lesson.session, contract=lesson.contract, student=lesson.alice, text=None
    )
    mine = {"X-GenAI4ED-Pseudonym": lesson.teacher.pseudonym}
    summary = (await client.get("/api/research/summary", headers=mine)).json()
    [row] = summary["lessons"]
    assert row["took_part"] == 0 and summary["totals"]["students"] == 0
    await say(db, lesson, ScriptedClient([turn("What do you do first?")]), "is it 5")
    summary = (await client.get("/api/research/summary", headers=mine)).json()
    assert summary["lessons"][0]["took_part"] == 1 and summary["totals"]["students"] == 1


async def test_tokens_are_kept_on_each_turn_and_summed_per_lesson(db, lesson, client):
    await say(db, lesson, ScriptedClient([turn("What do you do first?")]), "is it 5")
    turn_row = (await db.scalars(select(AgentTurn))).one()
    assert turn_row.usage == {}
    turn_row.usage = {"prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1000}
    await db.commit()
    mine = {"X-GenAI4ED-Pseudonym": lesson.teacher.pseudonym}
    summary = (await client.get("/api/research/summary", headers=mine)).json()
    assert summary["lessons"][0]["tokens"] == 1000


async def test_the_overview_reads_the_same_number_of_times_however_many_lessons(db, lesson):
    """It read nine times per lesson, so the research page slowed as the study grew."""
    from sqlalchemy import event

    from app import research_view
    from app.models import Session

    await say(db, lesson, ScriptedClient([turn("What do you do first?")]), "is it 5")
    first = (await db.scalars(select(AgentTurn))).one()
    reads: list[str] = []

    def count(*args):
        reads.append(args[2])

    async def reads_for_overview() -> int:
        reads.clear()
        event.listen(db.bind.sync_engine, "before_cursor_execute", count)
        try:
            body = await research_view.overview(db)
        finally:
            event.remove(db.bind.sync_engine, "before_cursor_execute", count)
        return len(reads), len(body["lessons"])

    one = await reads_for_overview()
    for _ in range(3):
        again = Session(
            contract_id=lesson.session.contract_id,
            class_id=lesson.session.class_id,
            status="closed",
        )
        db.add(again)
        await db.flush()
        columns = {c.key: getattr(first, c.key) for c in AgentTurn.__table__.columns}
        db.add(AgentTurn(**{**columns, "id": uuid.uuid4(), "session_id": again.id}))
    await db.commit()
    four = await reads_for_overview()
    assert (one[1], four[1]) == (1, 4)
    assert four[0] == one[0]
