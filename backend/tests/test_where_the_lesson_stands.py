"""Where this lesson stands: what the server knows about the lesson in focus, written into each
turn's prompt.

The server is certain about the lesson in focus: its heading, whose it is, and whether anything
is drafted in it. The model judges only the teacher's words. The screen has no activity box, so
nothing is pressed and the kind of activity is said in words.
"""

from sqlalchemy import select

from app.agent import thread
from app.agent.brief import ActivityRecord
from app.models import AgentTurn
from tests.test_activity_in_the_lesson import ASKS, _drafted, _stored, scripted
from tests.test_thread import last_card, press, say

OPENS = "Where this lesson stands:"


def stands(model, call=-1) -> str:
    """The block in the prompt of one of the model's calls."""
    lines = model.calls[call]["system"].split("\n")
    return next((line for line in lines if line.startswith(OPENS)), "")


def topic_drafted(new: bool = False, **changes) -> dict:
    """A reply that drafts a lesson, `new` or not, while judging that the teacher gave only a
    topic."""
    return _drafted(**changes) | {"gave": "topic", "new_lesson": new}


async def latest_turn(db) -> AgentTurn:
    return (await db.scalars(select(AgentTurn).order_by(AgentTurn.created_at.desc()))).first()


# ---------- what the block says ----------


async def test_nothing_in_the_block_is_about_pressing(app, client, classroom):
    model = scripted(app, ASKS)
    await say(client, classroom, "A lesson on fractions.", teacher=classroom.other_teacher)
    block = stands(model)
    assert block == " ".join(
        [OPENS, "No lesson is in focus.", thread.STANDS_THREE, thread.STANDS_THEN_GUESS]
        + [thread.STANDS_IN_WORDS]
    )
    for gone in ("pressed", "activity box:", "Build for it", "do not draft"):
        assert gone not in block.replace(thread.STANDS_IN_WORDS, ""), gone


async def test_a_change_to_a_lesson_that_has_a_heading_is_never_sent_back(app, client, classroom):
    model = scripted(app, _drafted(heading="maths"), topic_drafted(heading="maths"))
    await say(client, classroom, "A lesson on linear equations.")
    await say(client, classroom, "Make it about simultaneous equations instead.")
    assert len(model.calls) == 2


# ---------- the lesson in focus ----------


async def test_a_heading_the_agent_worked_out_is_named_as_its_guess(app, client, classroom):
    essay = _drafted(heading="writing", activity_kind="an argumentative essay")
    model = scripted(app, essay, ASKS)
    await say(client, classroom, "An essay on school uniform.")
    await say(client, classroom, "For 14 year olds.")
    block = stands(model)
    assert "The lesson in focus is Writing tasks, your guess" in block
    assert '"an argumentative essay"' in block


async def test_a_heading_the_teacher_pressed_on_a_lesson_from_before_is_still_named_as_theirs(
    app, client, classroom, db
):
    model = scripted(app, _drafted(heading="maths", activity_kind="multi-step problems"), ASKS)
    card = last_card(await say(client, classroom, "A lesson on fractions."))
    # As the server wrote it when a teacher could still press a heading.
    lesson, brief = await _stored(db, card)
    brief.record = ActivityRecord(picked=["maths"], picked_when="before")
    lesson.brief = brief.model_dump(mode="json")
    await db.commit()

    await say(client, classroom, "For 12 year olds.")

    block = stands(model)
    assert "The lesson in focus is Mathematics tasks, which they pressed" in block
    assert "They pressed" not in block


async def test_a_kind_on_no_list_is_kept_in_the_agents_own_words(app, client, classroom, db):
    scripted(app, _drafted(heading="other", activity_kind="a structured debate"))
    sent = await say(client, classroom, "A debate on school uniform, in two teams.")
    _, brief = await _stored(db, last_card(sent))
    assert (brief.listed_kind, brief.kind_from) == ("", "own_words")


# ---------- the follow-up button, and the record ----------


async def test_a_follow_up_pressed_is_drafted_without_asking(app, client, classroom):
    model = scripted(app, topic_drafted(title="Where plants get food", topics=["plant food"]))
    drafted = await press(client, classroom, "follow_up", text="plants get food from the soil")
    assert last_card(drafted)["type"] == "lesson"
    assert len(model.calls) == 1
    assert "follow up a shared difficulty" in stands(model)


async def test_what_the_server_told_the_agent_is_kept_with_the_turn(app, client, classroom, db):
    scripted(app, ASKS, ASKS, topic_drafted(title="Where plants get food", topics=["plant food"]))
    await say(client, classroom, "A lesson on fractions.", teacher=classroom.other_teacher)
    assert (await latest_turn(db)).context_manifest["stands"] == "not drafted"
    await say(client, classroom, "Make it 40 minutes.")
    assert (await latest_turn(db)).context_manifest["stands"] == "drafted"
    await press(client, classroom, "follow_up", text="plants get food from the soil")
    assert (await latest_turn(db)).context_manifest["stands"] == "follow-up"
