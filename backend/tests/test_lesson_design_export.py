"""The research export of how lessons came by their activity.

One file to code: the teachers' own words, alone, so a researcher codes them with the activity
list without seeing the agent's guess. Two to compare with: each turn of the teacher's agent,
and each lesson version's activity record.
"""

import csv
import uuid

from app import research
from tests.test_activity_box import picked
from tests.test_activity_in_the_lesson import _drafted, scripted
from tests.test_what_was_done_with_the_guess import SAID

ESSAY = {"heading": "writing", "activity_kind": "an argumentative essay"}


def rows(path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


async def _designed(app, client, classroom):
    scripted(app, _drafted(**ESSAY) | {"gave": "part", "guess_said": SAID})
    await picked(client, classroom, "They write an essay on school uniform.", "maths")


async def test_one_file_to_code_and_two_to_compare_with_the_agent(
    app, client, classroom, db, tmp_path
):
    await _designed(app, client, classroom)
    await research.export(db, tmp_path, with_text=True)

    [said] = rows(tmp_path / "teacher_messages.csv")
    # Their words alone: not what they pressed, and nothing of the agent's.
    assert said["words"] == "They write an essay on school uniform."
    assert set(said) == {"message_id", "teacher", "at", "words"}

    [turn] = rows(tmp_path / "teacher_turns.csv")
    assert turn["message_id"] == said["message_id"]
    assert (turn["pressed"], turn["stands"], turn["gave"]) == ("maths", "pressed", "part")
    assert (turn["drafted"], turn["heading"], turn["guess_said"]) == ("True", "writing", SAID)

    [lesson] = [r for r in rows(tmp_path / "lesson_activity.csv") if r["heading"]]
    assert lesson["lesson_id"] == turn["lesson_id"]
    assert (lesson["picked"], lesson["picked_when"], lesson["heading_from"]) == (
        "maths",
        "before",
        "worked_out",
    )
    # Pressed one heading, the words read as another; the kind is the agent's own words.
    assert (lesson["disagreed"], lesson["not_on_list"], lesson["kind_from"]) == (
        "True",
        "True",
        "own_words",
    )
    assert (lesson["guess"], lesson["said"]) == ("standing", SAID)


async def test_without_text_the_words_are_left_out(app, client, classroom, db, tmp_path):
    await _designed(app, client, classroom)
    await research.export(db, tmp_path)
    [said] = rows(tmp_path / "teacher_messages.csv")
    [turn] = rows(tmp_path / "teacher_turns.csv")
    [lesson] = [r for r in rows(tmp_path / "lesson_activity.csv") if r["heading"]]
    assert (said["words"], turn["guess_said"], lesson["said"]) == ("", "", "")
    # The coded facts stay.
    assert (turn["heading"], lesson["picked"]) == ("writing", "maths")


async def test_a_teachers_download_holds_only_their_own_design(
    app, client, classroom, db, tmp_path
):
    await _designed(app, client, classroom)
    await research.export(db, tmp_path, with_text=True, teacher_id=uuid.uuid4())
    for name in ("teacher_messages.csv", "teacher_turns.csv", "lesson_activity.csv"):
        assert rows(tmp_path / name) == []
