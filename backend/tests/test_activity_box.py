"""The activity box: the headings a teacher presses, on their page and in the chat.

What is pressed travels beside the teacher's words, never typed into them. It is kept on the
message as the headings themselves, and shown to the teacher and the agent as one plain line
under what the teacher wrote.
"""

from sqlalchemy import select

from app.agent import activities
from app.models import Message
from tests.test_activity_in_the_lesson import OLD, _drafted, scripted
from tests.test_thread import last_card, press, say

LINE = "The activity I picked: "
ASKS = {"reply": "How long is the lesson?", "show": "nothing"}


async def picked(client, classroom, text, *picks):
    return await client.post(
        "/api/teacher/thread/messages",
        json={"text": text, "picks": list(picks)},
        headers=classroom.headers(classroom.teacher),
    )


async def test_what_the_teacher_pressed_goes_with_their_next_message(app, client, classroom, db):
    agent = scripted(app, ASKS)
    sent = await picked(client, classroom, "A lesson on fractions.", "maths", "writing")
    assert sent.status_code == 200
    # Under their own words, in the order and the words of the screen.
    shown = f"A lesson on fractions.\n\n{LINE}Writing tasks, Mathematics tasks."
    assert sent.json()["messages"][-2]["text"] == shown
    # The agent reads the same line.
    assert agent.calls[-1]["messages"][-1] == {"role": "user", "content": shown}
    # The message keeps the headings themselves, beside the words.
    kept = (await db.scalars(select(Message).where(Message.role == "teacher"))).one()
    assert kept.data["picks"] == ["writing", "maths"]


async def test_a_message_with_nothing_pressed_says_nothing_about_the_activity(
    app, client, classroom, db
):
    scripted(app, ASKS)
    sent = await picked(client, classroom, "A lesson on fractions.")
    assert sent.json()["messages"][-2]["text"] == "A lesson on fractions."
    kept = (await db.scalars(select(Message).where(Message.role == "teacher"))).one()
    assert "picks" not in kept.data


async def test_the_words_of_a_heading_are_not_read_as_the_teachers_own(app, client, classroom):
    """A teacher who names a lesson by its title means that lesson. Pressing "Reading
    comprehension" names nothing: the lesson called that is not pulled into focus."""
    agent = scripted(app, _drafted(title="Reading comprehension"), ASKS, ASKS)
    card = last_card(await say(client, classroom, "A lesson on reading."))
    await press(client, classroom, "new_lesson")
    await picked(client, classroom, "Something on the water cycle.", "reading")
    assert "The lesson in focus is id" not in agent.calls[-1]["system"]
    # Typed, the same words do name it.
    await say(client, classroom, "Open reading comprehension again.")
    assert f"The lesson in focus is id {card['lesson_id']}" in agent.calls[-1]["system"]


async def test_a_pick_alone_is_a_message(app, client, classroom):
    scripted(app, ASKS)
    sent = await picked(client, classroom, "", "choice")
    assert sent.status_code == 200
    assert sent.json()["messages"][-2]["text"] == f"{LINE}Multiple-choice / Cloze tasks."
    # Nothing typed and nothing pressed is still nothing to send.
    assert (await picked(client, classroom, "  ")).status_code == 422


async def test_only_what_the_screen_offers_can_be_picked(app, client, classroom):
    assert (await picked(client, classroom, "A lesson.", "essays")).status_code == 422
    assert (await picked(client, classroom, "A lesson.", "maths", "essays")).status_code == 422
    # A heading pressed twice is one pick.
    scripted(app, ASKS)
    twice = await picked(client, classroom, "A lesson.", "other", "maths", "maths")
    assert twice.json()["messages"][-2]["text"].endswith(
        f"{LINE}Mathematics tasks, Something else."
    )


async def test_the_page_is_sent_what_can_be_pressed_and_none_of_the_kinds(client, classroom):
    read = await client.get("/api/teacher/thread", headers=classroom.headers(classroom.teacher))
    offered = read.json()["activities"]
    assert offered == activities.for_screen()
    assert [a["label"] for a in offered][-1] == "Something else"
    assert len(offered) == 8
    assert all(set(a) == {"key", "label"} for a in offered)


async def test_the_focus_says_the_lessons_headings_and_where_they_came_from(app, client, classroom):
    steps = [dict(s) for s in OLD["steps"]]
    steps[2] = {**steps[2], "heading": "writing"}
    scripted(app, _drafted(heading="maths", activity_kind="equations", steps=steps))
    focus = (await say(client, classroom, "A lesson on linear equations.")).json()["focus"]
    # The lesson's own heading first, then a step's. Nothing was pressed: the agent worked it out.
    assert focus["headings"] == ["maths", "writing"]
    assert focus["heading_from"] == "worked_out"


async def test_a_lesson_from_before_has_no_heading_in_the_focus(app, client, classroom):
    scripted(app, _drafted())
    focus = (await say(client, classroom, "A lesson on linear equations.")).json()["focus"]
    assert (focus["headings"], focus["heading_from"]) == ([], "")
