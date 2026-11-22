"""Asking first: the part of it the server holds, for every teacher.

A lesson that is not drafted yet waits for three things from the teacher: an objective, the
students' age and the length. The prompt says so (tests.test_one_wording); here the server says
it again in the block it writes each turn, and sends a draft back once when one of the three is
not in it or the objectives are marked as the agent's own. A change to a lesson that is already
drafted and the follow-up button are left as they were.
"""

import pytest
from sqlalchemy import func, select

from app.agent import thread
from app.models import LessonContract
from tests.test_activity_in_the_lesson import ASKS, _drafted, _stored, scripted
from tests.test_thread import last_card, press, say
from tests.test_where_the_lesson_stands import latest_turn, stands

# What the server tells the agent to ask about a lesson that cannot be approved yet.
FIRST_TWO = "Ask about the first two"


async def lessons_of(db, teacher) -> int:
    """How many lessons a teacher has, drafts included."""
    return await db.scalar(
        select(func.count())
        .select_from(LessonContract)
        .where(LessonContract.teacher_id == teacher.id)
    )


# ---------- a lesson that is not drafted yet ----------


async def test_a_draft_with_no_objectives_is_sent_back_and_nothing_is_saved(
    app, client, classroom, db
):
    other = classroom.other_teacher
    model = scripted(app, _drafted(objectives=[]), ASKS)

    sent = await say(client, classroom, "A lesson on fractions.", teacher=other)

    assert (sent.status_code, len(model.calls)) == (200, 2)
    # The second reply asked, so no lesson was made.
    assert await lessons_of(db, other) == 0
    assert "no objective" in (await latest_turn(db)).request["retry_reason"]


@pytest.mark.parametrize(
    ("lacking", "named"), [({"age": None}, "no age"), ({"duration_minutes": None}, "no length")]
)
async def test_a_draft_without_the_age_or_the_length_is_sent_back(
    app, client, classroom, db, lacking, named
):
    other = classroom.other_teacher
    model = scripted(app, _drafted(**lacking), ASKS)

    await say(client, classroom, "They should solve equations with x on both sides.", teacher=other)

    assert len(model.calls) == 2
    assert await lessons_of(db, other) == 0
    assert named in (await latest_turn(db)).request["retry_reason"]


@pytest.mark.parametrize("marked", [["objectives", "step 2 criteria"], ["Learning objectives"]])
async def test_objectives_the_agent_marked_as_its_own_are_sent_back(
    app, client, classroom, db, marked
):
    other = classroom.other_teacher
    model = scripted(app, _drafted(to_check=marked), ASKS)

    await say(client, classroom, "Fractions for my 13 year olds, 30 minutes.", teacher=other)

    assert len(model.calls) == 2
    assert await lessons_of(db, other) == 0
    assert "to_check" in (await latest_turn(db)).request["retry_reason"]


async def test_a_draft_that_breaks_both_rules_is_told_both_in_full(app, client, classroom, db):
    """What a draft is sent back with reaches the agent cut short, so the two have to fit."""
    other = classroom.other_teacher
    scripted(app, _drafted(age=None, duration_minutes=None, to_check=["objectives"]), ASKS)

    await say(client, classroom, "Fractions: they should add two fractions.", teacher=other)

    reason = (await latest_turn(db)).request["retry_reason"]
    assert "no age or length" in reason
    assert reason.endswith(thread.NOT_AGREED)


async def test_a_message_that_says_everything_is_drafted_at_once(app, client, classroom, db):
    other = classroom.other_teacher
    # What the agent filled in is marked, and none of it is the lesson's objectives.
    model = scripted(app, _drafted(to_check=["steps", "step 2 criteria", "step 2 objective"]))

    sent = await say(
        client,
        classroom,
        "They should solve equations with the unknown on both sides. They are 13, 30 minutes.",
        teacher=other,
    )

    assert len(model.calls) == 1
    card = last_card(sent)
    assert (card["type"], card["title"]) == ("lesson", "Linear equations")
    assert not (await latest_turn(db)).request["retry_reason"]


async def test_a_second_draft_is_kept_rather_than_lost(app, client, classroom, db):
    other = classroom.other_teacher
    model = scripted(app, _drafted(objectives=[]), _drafted(objectives=[]))

    sent = await say(client, classroom, "A lesson on fractions.", teacher=other)

    assert (sent.status_code, len(model.calls)) == (200, 2)
    _, brief = await _stored(db, last_card(sent))
    assert brief.title == "Linear equations"


async def test_an_empty_draft_in_focus_is_held_to_the_same(app, client, classroom, db):
    empty = last_card(await press(client, classroom, "start_approach", text="inquiry"))
    model = scripted(app, _drafted(objectives=[]), ASKS)

    await say(client, classroom, "A lesson on fractions.")

    assert len(model.calls) == 2
    _, brief = await _stored(db, empty)
    assert (brief.title, brief.steps) == ("", [])


@pytest.mark.parametrize("ref", [None, "Photosynthesis"])
async def test_a_draft_of_another_lesson_is_held_to_the_same(app, client, classroom, db, ref):
    """A different lesson is a new one whether or not the agent called it new, and whether or
    not it filed it under the title it is giving it."""
    other = classroom.other_teacher
    another = _drafted(title="Photosynthesis", subject="biology", topics=["plants"], age=None)
    model = scripted(app, _drafted(), {**another, "lesson_ref": ref}, ASKS)
    await say(client, classroom, "Solve equations with x on both sides. 13, 30 min.", teacher=other)

    await say(
        client, classroom, "Now one on photosynthesis: name what a plant needs.", teacher=other
    )

    assert len(model.calls) == 3
    assert await lessons_of(db, other) == 1


# ---------- what is left as it was ----------


async def test_a_change_to_a_drafted_lesson_is_not_sent_back(app, client, classroom, db):
    other = classroom.other_teacher
    changed = _drafted(objectives=[], to_check=["objectives"])
    model = scripted(app, _drafted(), changed)
    await say(client, classroom, "Solve equations with x on both sides. 13, 30 min.", teacher=other)

    sent = await say(client, classroom, "Take the objective off for now.", teacher=other)

    assert len(model.calls) == 2
    _, brief = await _stored(db, last_card(sent))
    assert (brief.objectives, brief.to_check) == ([], ["objectives"])


async def test_a_change_to_another_lesson_of_theirs_is_not_sent_back(app, client, classroom, db):
    other = classroom.other_teacher
    plants = {"title": "Photosynthesis", "subject": "biology", "topics": ["plants"]}
    changed = {**_drafted(**plants, objectives=[]), "lesson_ref": "Photosynthesis"}
    model = scripted(app, _drafted(**plants), _drafted(), changed)
    await say(client, classroom, "Name what a plant needs to grow. 13, 30 min.", teacher=other)
    await say(client, classroom, "A new lesson: solve equations. 13, 30 min.", teacher=other)

    sent = await say(client, classroom, "Take the objective off the plants one.", teacher=other)

    assert len(model.calls) == 3
    _, brief = await _stored(db, last_card(sent))
    assert (brief.title, brief.objectives) == ("Photosynthesis", [])


async def test_a_change_the_agent_called_new_is_not_sent_back(app, client, classroom, db):
    """As when it is written: a reply that keeps the title is a change, whatever it is called."""
    other = classroom.other_teacher
    longer = {**_drafted(age=None, duration_minutes=45), "new_lesson": True}
    # A lesson drafted without the age: sent back once, and the second draft is kept.
    model = scripted(app, _drafted(age=None), _drafted(age=None), longer)
    await say(client, classroom, "A lesson on linear equations.", teacher=other)

    sent = await say(client, classroom, "Make it 45 minutes.", teacher=other)

    assert len(model.calls) == 3
    _, brief = await _stored(db, last_card(sent))
    assert brief.duration_minutes == 45


async def test_the_follow_up_button_drafts_at_once(app, client, classroom, db):
    guessed = _drafted(age=None, duration_minutes=None, to_check=["objectives"])
    model = scripted(app, guessed)

    drafted = await press(client, classroom, "follow_up", text="subtracting the denominators")

    assert (drafted.status_code, len(model.calls)) == (200, 1)
    assert last_card(drafted)["type"] == "lesson"
    assert "follow up a shared difficulty" in stands(model)


# ---------- what the agent is told each turn ----------


async def test_the_agent_is_told_what_a_new_lesson_waits_for(app, client, classroom):
    other = classroom.other_teacher
    model = scripted(app, ASKS)

    await say(client, classroom, "A lesson on fractions.", teacher=other)

    block = stands(model)
    assert "Nothing is pressed" not in block
    assert "an objective, the students' age and the length" in block
    assert "two questions at most" in block
    assert "say your guess at the heading and kind" in block
    # The kind of activity is the agent's to guess, so it is not told to ask for it.
    assert "what kind of activity" not in block


async def test_an_empty_draft_is_not_asked_about_its_title_first(app, client, classroom):
    await press(client, classroom, "start_approach", text="inquiry")
    model = scripted(app, ASKS)

    await say(client, classroom, "A lesson on fractions.")

    assert FIRST_TWO not in model.calls[-1]["system"]


async def test_a_drafted_lesson_is_still_asked_about_what_it_lacks(app, client, classroom):
    other = classroom.other_teacher
    # Drafted without the age: sent back once, and the second draft is kept.
    model = scripted(app, _drafted(age=None), _drafted(age=None), ASKS)
    await say(client, classroom, "A lesson on linear equations.", teacher=other)

    await say(client, classroom, "Thanks.", teacher=other)

    system = model.calls[-1]["system"]
    assert "the students' age" in system and FIRST_TWO in system


async def test_a_drafted_lesson_takes_what_it_is_given_as_it_comes(app, client, classroom):
    # Runs v26-ask-3 and v26-ask-old-gaps: told the length of a lesson drafted without the
    # age, the agent thanked the teacher and saved nothing while it waited for the age.
    other = classroom.other_teacher
    gaps = _drafted(age=None, duration_minutes=None)
    model = scripted(app, gaps, gaps, ASKS)
    await say(client, classroom, "A lesson on linear equations.", teacher=other)

    await say(client, classroom, "It's a 50 minute lesson.", teacher=other)

    block = stands(model)
    assert thread.STANDS_THREE in block
    # Said last of the lesson, before what the screen does not have.
    assert block.endswith(f"{thread.STANDS_DRAFTED} {thread.STANDS_IN_WORDS}")
    assert "goes into brief in this reply" in thread.STANDS_DRAFTED


async def test_a_lesson_with_nothing_drafted_is_not_told_it_is_drafted(app, client, classroom):
    other = classroom.other_teacher
    model = scripted(app, ASKS, ASKS)

    await say(client, classroom, "A lesson on fractions.", teacher=other)
    assert thread.STANDS_THREE in stands(model)
    assert thread.STANDS_DRAFTED not in stands(model)

    # An empty draft in focus waits as a new lesson does.
    await press(client, classroom, "start_approach", text="inquiry")
    await say(client, classroom, "A lesson on fractions.")
    assert thread.STANDS_THREE in stands(model)
    assert thread.STANDS_DRAFTED not in stands(model)
