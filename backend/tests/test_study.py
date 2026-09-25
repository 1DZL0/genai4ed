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
from app.enums import ExceptionKind
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
    # The teacher ticked the box; the study still decides.
    lesson.contract.use_past_lessons = True
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
