"""Where this lesson stands: what the server knows about the activity, written into each turn's
prompt, and the one check on the reply that follows from it.

The server is certain about what was pressed and what the lesson in focus has. The model judges
only the teacher's words: whether they name just a topic ("gave"), and which kind it is. A reply
that drafts a new lesson from a topic alone, with nothing pressed, is sent back once.
"""

from sqlalchemy import select

from app.models import AgentTurn
from tests.test_activity_box import ASKS, TOPIC, box, picked
from tests.test_activity_in_the_lesson import _drafted, _stored, scripted
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


# ---------- nothing pressed ----------


async def test_with_nothing_pressed_the_agent_is_told_to_ask_when_given_only_a_topic(
    app, client, classroom
):
    model = scripted(app, TOPIC)
    sent = await say(client, classroom, "A lesson on fractions.")
    block = stands(model)
    assert "Nothing is pressed in the activity box." in block
    assert "do not draft" in block and "gave" in block
    assert box(sent) == {"ask": True}


async def test_a_new_lesson_drafted_from_a_topic_alone_is_sent_back_once(
    app, client, classroom, db
):
    model = scripted(app, topic_drafted(new=True), TOPIC)
    sent = await say(client, classroom, "A lesson on fractions.")
    assert len(model.calls) == 2
    # The second reply asked, so nothing was drafted.
    assert box(sent) == {"ask": True}
    turn = await latest_turn(db)
    assert "only a topic" in turn.request["retry_reason"]


async def test_a_second_draft_from_a_topic_alone_is_kept_rather_than_lost(
    app, client, classroom, db
):
    model = scripted(app, topic_drafted(new=True), topic_drafted(new=True))
    sent = await say(client, classroom, "A lesson on fractions.")
    assert (sent.status_code, len(model.calls)) == (200, 2)
    _, brief = await _stored(db, last_card(sent))
    assert brief.title == "Linear equations"


async def test_a_change_to_a_lesson_that_has_a_heading_is_never_sent_back(app, client, classroom):
    model = scripted(app, _drafted(heading="maths"), topic_drafted(heading="maths"))
    await say(client, classroom, "A lesson on linear equations.")
    await say(client, classroom, "Make it about simultaneous equations instead.")
    assert len(model.calls) == 2


# ---------- pressed ----------


async def test_a_heading_pressed_is_named_as_the_teachers_and_the_draft_stands(
    app, client, classroom
):
    model = scripted(app, topic_drafted(True, heading="maths"))
    await picked(client, classroom, "A lesson on fractions.", "maths")
    block = stands(model)
    assert "They pressed Mathematics tasks in the activity box: that is theirs." in block
    assert "name the mismatch" in block
    # Pressed, a topic is enough to draft from.
    assert len(model.calls) == 1


async def test_several_headings_pressed_are_all_named_with_a_heading_for_each_step(
    app, client, classroom
):
    model = scripted(app, _drafted(heading="maths"))
    await picked(client, classroom, "A lesson on fractions.", "maths", "writing")
    block = stands(model)
    assert "Writing tasks, Mathematics tasks" in block and "each step its own heading" in block


async def test_a_heading_pressed_after_the_agent_asked_is_named_as_the_answer(
    app, client, classroom
):
    model = scripted(app, TOPIC, _drafted(heading="maths"))
    await say(client, classroom, "A lesson on fractions.")
    await picked(client, classroom, "", "maths")
    assert "answering your question" in stands(model)


async def test_a_heading_pressed_over_the_lessons_own_asks_for_a_redraft_keeping_their_words(
    app, client, classroom
):
    model = scripted(app, _drafted(heading="maths"), _drafted(heading="writing"))
    await say(client, classroom, "A lesson on linear equations.")
    await picked(client, classroom, "", "writing")
    block = stands(model)
    assert "takes the place of Mathematics tasks" in block
    assert "keep the title, the subject, the age, the length" in block


# ---------- the lesson in focus ----------


async def test_a_heading_the_agent_worked_out_is_named_as_its_guess(app, client, classroom):
    essay = _drafted(heading="writing", activity_kind="an argumentative essay")
    model = scripted(app, essay, ASKS)
    await say(client, classroom, "An essay on school uniform.")
    await say(client, classroom, "For 14 year olds.")
    block = stands(model)
    assert "The lesson in focus is Writing tasks, your guess" in block
    assert '"an argumentative essay"' in block


async def test_a_heading_the_teacher_pressed_is_named_as_theirs_on_the_lesson(
    app, client, classroom
):
    model = scripted(app, _drafted(heading="maths", activity_kind="multi-step problems"), ASKS)
    await picked(client, classroom, "A lesson on fractions.", "maths")
    await say(client, classroom, "For 12 year olds.")
    block = stands(model)
    assert "The lesson in focus is Mathematics tasks, which they pressed" in block
    assert "Nothing is pressed" in block


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
    scripted(app, TOPIC, _drafted(heading="maths"))
    await say(client, classroom, "A lesson on fractions.")
    assert (await latest_turn(db)).context_manifest["stands"] == "nothing pressed"
    await picked(client, classroom, "", "maths")
    assert (await latest_turn(db)).context_manifest["stands"] == "answered"
