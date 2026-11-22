"""The research export of how lessons came by their activity.

One file to code: the teachers' own words, alone, so a researcher codes them with the activity
list without seeing the agent's guess. Two to compare with: each turn of the teacher's agent,
and each lesson version's activity record.
"""

import csv
import uuid

from sqlalchemy import select

from app import research
from app.agent import activities
from app.agent.brief import LessonBrief
from app.agent.thread import PROMPT_VERSION
from app.models import LessonContract, Message
from tests.test_activity_in_the_lesson import _drafted, scripted
from tests.test_thread import say
from tests.test_what_was_done_with_the_guess import SAID

ESSAY = {"heading": "writing", "activity_kind": "an argumentative essay"}


def rows(path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


WORDS = "They write an essay on school uniform."


async def _designed(app, client, classroom):
    scripted(app, _drafted(**ESSAY) | {"gave": "part", "guess_said": SAID})
    await say(client, classroom, WORDS)


async def _pressed_before(db):
    """The design as it was stored when a teacher could still press a heading: Mathematics
    pressed with their words, the line saying so under them, the headings offered under the
    agent's reply, and the press on the lesson's record."""
    teacher, agent = (
        await db.scalars(select(Message).where(Message.role.in_(("teacher", "agent"))))
    ).all()
    teacher.text = f"{WORDS}\n\n{activities.picked_line(['maths'])}"
    teacher.data = {"picks": ["maths"]}
    agent.data = {**agent.data, "activity": {"ask": True}}
    lesson = await db.get(LessonContract, uuid.UUID(agent.data["card"]["lesson_id"]))
    brief = LessonBrief.model_validate(lesson.brief)
    record = {"picked": ["maths"], "picked_when": "before"}
    brief.record = brief.record.model_copy(update=record)
    lesson.brief = brief.model_dump(mode="json")
    await db.commit()


async def test_one_file_to_code_and_two_to_compare_with_the_agent(
    app, client, classroom, db, tmp_path
):
    await _designed(app, client, classroom)
    await research.export(db, tmp_path, with_text=True)

    [said] = rows(tmp_path / "teacher_messages.csv")
    # Their words alone, and nothing of the agent's.
    assert said["words"] == WORDS
    assert set(said) == {"message_id", "teacher", "at", "words"}

    [turn] = rows(tmp_path / "teacher_turns.csv")
    assert turn["message_id"] == said["message_id"]
    # Nothing can be pressed, and the lesson in focus was drafted already.
    assert (turn["pressed"], turn["stands"], turn["gave"]) == ("", "drafted", "part")
    assert turn["asked_for_activity"] == "False"
    # Which wording the turn was written from, so old rows can be told from new ones.
    assert turn["prompt_version"] == PROMPT_VERSION
    assert (turn["drafted"], turn["heading"], turn["guess_said"]) == ("True", "writing", SAID)

    [lesson] = [r for r in rows(tmp_path / "lesson_activity.csv") if r["heading"]]
    assert lesson["lesson_id"] == turn["lesson_id"]
    assert (lesson["picked"], lesson["picked_when"], lesson["heading_from"]) == (
        "",
        "",
        "worked_out",
    )
    # The heading is the agent's reading of their words; the kind is the agent's own words.
    assert (lesson["disagreed"], lesson["not_on_list"], lesson["kind_from"]) == (
        "False",
        "True",
        "own_words",
    )
    assert (lesson["guess"], lesson["said"]) == ("standing", SAID)


async def test_a_design_from_when_headings_could_be_pressed_still_exports(
    app, client, classroom, db, tmp_path
):
    await _designed(app, client, classroom)
    await _pressed_before(db)

    await research.export(db, tmp_path, with_text=True)

    [said] = rows(tmp_path / "teacher_messages.csv")
    # Their words alone: not the line saying what they pressed.
    assert said["words"] == WORDS
    [turn] = rows(tmp_path / "teacher_turns.csv")
    assert (turn["pressed"], turn["asked_for_activity"]) == ("maths", "True")
    [lesson] = [r for r in rows(tmp_path / "lesson_activity.csv") if r["heading"]]
    assert (lesson["picked"], lesson["picked_when"], lesson["heading_from"]) == (
        "maths",
        "before",
        "worked_out",
    )
    # Pressed one heading, the words read as another.
    assert lesson["disagreed"] == "True"
    # The thread still loads with those messages in it.
    read = await client.get("/api/teacher/thread", headers=classroom.headers(classroom.teacher))
    assert read.status_code == 200
    assert "activity" not in read.json()["messages"][-1]


async def test_without_text_the_words_are_left_out(app, client, classroom, db, tmp_path):
    await _designed(app, client, classroom)
    await research.export(db, tmp_path)
    [said] = rows(tmp_path / "teacher_messages.csv")
    [turn] = rows(tmp_path / "teacher_turns.csv")
    [lesson] = [r for r in rows(tmp_path / "lesson_activity.csv") if r["heading"]]
    assert (said["words"], turn["guess_said"], lesson["said"]) == ("", "", "")
    # The coded facts stay.
    assert (turn["heading"], lesson["kind_from"]) == ("writing", "own_words")


async def test_a_teachers_download_holds_only_their_own_design(
    app, client, classroom, db, tmp_path
):
    await _designed(app, client, classroom)
    await research.export(db, tmp_path, with_text=True, teacher_id=uuid.uuid4())
    for name in ("teacher_messages.csv", "teacher_turns.csv", "lesson_activity.csv"):
        assert rows(tmp_path / name) == []


def test_the_coding_guide_carries_every_heading_and_kind_on_the_list():
    from pathlib import Path

    from app.agent import activities

    docs = Path(__file__).resolve().parents[2] / "docs" / "research"
    guide = (docs / "coding-teacher-messages.md").read_text(encoding="utf-8")
    for heading in activities.PICKS:
        assert heading.label in guide
        for kind in heading.kinds:
            assert kind.name in guide, kind.name
    assert "teacher_messages.csv" in guide
    assert (docs / "activity-fit-rubric.md").exists()


async def test_a_reason_a_reply_was_sent_back_carries_no_words_without_text(
    app, client, classroom, db, tmp_path
):
    draft = _drafted(age=None) | {"new_lesson": True, "reply": "Ana wrote 'x is 4'."}
    scripted(app, draft, {"reply": "How old are they?", "show": "nothing"})
    await say(client, classroom, "A lesson on fractions.")
    await research.export(db, tmp_path)
    [turn] = rows(tmp_path / "teacher_turns.csv")
    # The kind of problem only: the reason quotes the draft, which can quote a pupil.
    assert turn["retried_because"] == "Your reply did not fit what was asked"
    await research.export(db, tmp_path, with_text=True)
    [turn] = rows(tmp_path / "teacher_turns.csv")
    assert "no age" in turn["retried_because"]
