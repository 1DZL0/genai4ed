"""What a teacher does around a lesson: teach it again from where it ended, and see every time
it was taught with how each class did."""

# ruff: noqa: F811 - `lesson` is a fixture imported from the student agent tests

from app.agent.llm import ScriptedClient
from app.models import Class
from tests.test_agent_student import lesson, turn  # noqa: F401 - `lesson` is a fixture
from tests.test_agent_student import say as student_says
from tests.test_thread import last_card, press


async def test_the_end_of_the_lesson_offers_to_teach_it_again_with_another_class(
    client, db, lesson
):
    other = Class(teacher_id=lesson.teacher.id, label="10C")
    db.add(other)
    await db.commit()
    running = last_card(await press(client, lesson, "show_class", session_id=lesson.session.id))
    assert running["teach_again"] is None

    ended = last_card(await press(client, lesson, "end", session_id=lesson.session.id))
    again = ended["teach_again"]
    assert again["lesson_id"] == str(lesson.contract.id)
    assert again["taught_class_id"] == str(lesson.klass.id)
    assert {"10C", lesson.klass.label} <= {c["label"] for c in again["classes"]}
    assert again["running"] is None
    board = last_card(await press(client, lesson, "show_class", session_id=lesson.session.id))
    assert board["teach_again"]["lesson_id"] == again["lesson_id"]

    started = await press(client, lesson, "run", lesson_id=again["lesson_id"], class_id=other.id)
    assert started.status_code == 200
    assert last_card(started)["type"] == "class"


async def test_teaching_it_again_says_which_lesson_has_to_end_first(client, db, lesson):
    first = lesson.session.id
    await press(client, lesson, "end", session_id=first)
    restarted = await press(
        client, lesson, "run", lesson_id=lesson.contract.id, class_id=lesson.klass.id
    )
    assert restarted.status_code == 200
    looked_back = last_card(await press(client, lesson, "show_outcomes", session_id=first))
    assert looked_back["teach_again"]["running"] == lesson.klass.label


async def test_the_lesson_card_lists_every_run_with_how_the_class_did(client, db, lesson):
    # Alice only opens the lesson; Bob writes an answer.
    await student_says(db, lesson, ScriptedClient([turn("Hi! Solve 3x + 4 = 19.")]), None)
    wrong = turn(
        "Not quite. What did you do first?",
        move="hint",
        student_attempted=True,
        assessment={"judgment": "not_met", "evidence_quote": "x is 7"},
    )
    await student_says(db, lesson, ScriptedClient([wrong]), "x is 7", student=lesson.bob)
    await press(client, lesson, "end", session_id=lesson.session.id)

    card = last_card(await press(client, lesson, "show_lesson", lesson_id=lesson.contract.id))
    [run] = [r for r in card["runs"] if r["session_id"] == str(lesson.session.id)]
    assert (run["students"], run["took_part"], run["finished"]) == (2, 1, 0)
    assert run["class_id"] == str(lesson.klass.id)
    assert run["status"] == "closed"
