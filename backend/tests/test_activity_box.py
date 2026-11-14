"""The activity box: the headings a teacher presses, on their page and in the chat.

What is pressed travels beside the teacher's words, never typed into them. It is kept on the
message as the headings themselves, and shown to the teacher and the agent as one plain line
under what the teacher wrote.
"""

from sqlalchemy import select

from app.agent import activities
from app.models import Message
from tests.test_activity_in_the_lesson import OLD, _drafted, _stored, scripted
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


# ---------- the box in the chat, under the agent's words ----------

# The agent's reading of a message that names what the lesson is about and nothing more.
TOPIC = {"reply": "What kind of activity is it?", "show": "nothing", "gave": "topic"}


def box(response):
    """The activity box under the newest thing the agent said."""
    return response.json()["messages"][-1]["activity"]


async def test_a_topic_and_nothing_pressed_brings_the_headings_into_the_chat(
    app, client, classroom
):
    scripted(app, TOPIC)
    sent = await say(client, classroom, "A lesson on fractions.")
    assert box(sent) == {"ask": True}
    # Under the agent's words only: the teacher's own message carries no box.
    assert sent.json()["messages"][-2]["activity"] is None


async def test_a_topic_with_a_heading_pressed_is_not_asked_for_one(app, client, classroom):
    scripted(app, TOPIC)
    assert box(await picked(client, classroom, "A lesson on fractions.", "maths")) is None


async def test_a_whole_lesson_and_nothing_pressed_comes_back_with_its_heading_as_a_guess(
    app, client, classroom
):
    scripted(app, {**_drafted(heading="maths", activity_kind="equations"), "gave": "whole"})
    sent = await say(client, classroom, "Three steps on linear equations: solve, check, explain.")
    assert box(sent) == {
        "headings": ["maths"],
        "guess": True,
        "lesson_id": last_card(sent)["lesson_id"],
    }


async def test_a_reply_with_nothing_to_say_about_the_activity_carries_no_box(
    app, client, classroom
):
    scripted(app, ASKS, {**_drafted(), "gave": "whole"})
    assert box(await say(client, classroom, "Hello.")) is None
    # A lesson the agent gave no heading has none to show.
    assert box(await say(client, classroom, "Three steps on linear equations.")) is None


async def test_beside_a_lesson_with_a_heading_the_headings_come_only_when_the_agent_asks(
    app, client, classroom
):
    scripted(app, _drafted(heading="maths"), ASKS, TOPIC)
    await say(client, classroom, "A lesson on linear equations.")
    assert box(await say(client, classroom, "It is about equations.")) is None
    # The agent asks only when the lesson asked for has no heading: the box goes with it.
    assert box(await say(client, classroom, "Next: photosynthesis.")) == {"ask": True}


async def test_the_box_is_said_again_only_when_the_heading_changes(app, client, classroom):
    scripted(
        app,
        _drafted(heading="maths"),
        _drafted(heading="maths", duration_minutes=30),
        _drafted(heading="writing", duration_minutes=30),
    )
    assert box(await say(client, classroom, "A lesson on linear equations."))["headings"] == [
        "maths"
    ]
    assert box(await say(client, classroom, "Make it half an hour.")) is None
    assert box(await say(client, classroom, "They write it up as a report."))["headings"] == [
        "writing"
    ]


# ---------- a pick is a fact ----------


async def test_a_heading_the_agent_names_does_not_change_what_was_pressed(
    app, client, classroom, db
):
    scripted(
        app,
        _drafted(heading="writing", activity_kind="a report"),
        _drafted(heading="choice", duration_minutes=30),
    )
    sent = await picked(client, classroom, "They write up an experiment.", "maths")
    card = last_card(sent)
    _, brief = await _stored(db, card)
    # The pick is kept as pressed. The lesson's heading is what the agent read in their words.
    assert (brief.record.picked, brief.record.picked_when) == (["maths"], "before")
    assert (brief.heading, brief.heading_from) == ("writing", "worked_out")
    # Both are shown: the agent's reading as a guess, beside what the teacher pressed.
    assert box(sent) == {
        "headings": ["writing"],
        "guess": True,
        "picked": ["maths"],
        "lesson_id": card["lesson_id"],
    }
    assert sent.json()["focus"]["picked"] == ["maths"]
    # Nor does a later reply that names another one.
    await say(client, classroom, "Make it half an hour.")
    _, later = await _stored(db, card)
    assert (later.heading, later.record.picked, later.record.picked_when) == (
        "choice",
        ["maths"],
        "before",
    )


async def test_a_pressed_heading_the_agent_agrees_with_is_the_teachers_own(
    app, client, classroom, db
):
    scripted(app, _drafted(heading="maths"))
    sent = await picked(client, classroom, "A lesson on linear equations.", "maths")
    card = last_card(sent)
    _, brief = await _stored(db, card)
    assert brief.heading_from == "picked_before"
    assert box(sent) == {
        "headings": ["maths"],
        "guess": False,
        "picked": ["maths"],
        "lesson_id": card["lesson_id"],
    }


async def test_a_lesson_the_agent_gives_no_heading_takes_the_one_pressed(
    app, client, classroom, db
):
    scripted(app, _drafted())
    sent = await picked(client, classroom, "A lesson on linear equations.", "maths", "writing")
    _, brief = await _stored(db, last_card(sent))
    # With several pressed, the first on the screen.
    assert (brief.heading, brief.record.picked) == ("writing", ["writing", "maths"])


async def test_a_pick_stands_until_a_lesson_takes_it_up(app, client, classroom, db):
    scripted(app, ASKS, _drafted())
    asked = await picked(client, classroom, "A lesson on fractions.", "maths")
    # No lesson yet: the page is told what stands pressed, so it is still shown after a reload.
    assert asked.json()["picked"] == ["maths"]
    sent = await say(client, classroom, "Forty minutes.")
    _, brief = await _stored(db, last_card(sent))
    assert (brief.heading, brief.record.picked, brief.record.picked_when) == (
        "maths",
        ["maths"],
        "before",
    )
    # Taken up: it is the lesson's now, and nothing stands pressed beside it.
    assert sent.json()["picked"] == []
    assert sent.json()["focus"]["picked"] == ["maths"]


async def test_a_heading_pressed_after_the_agent_asked_is_recorded_as_asked(
    app, client, classroom, db
):
    scripted(app, TOPIC, _drafted(heading="maths"))
    await say(client, classroom, "A lesson on fractions.")
    sent = await picked(client, classroom, "", "maths")
    _, brief = await _stored(db, last_card(sent))
    assert (brief.record.picked, brief.record.picked_when) == (["maths"], "asked")
    assert brief.heading_from == "picked_in_chat"


async def test_a_heading_pressed_over_the_one_a_lesson_has_is_recorded_as_later(
    app, client, classroom, db
):
    scripted(app, _drafted(heading="maths"), _drafted(heading="writing"))
    card = last_card(await say(client, classroom, "A lesson on linear equations."))
    sent = await picked(client, classroom, "", "writing")
    _, brief = await _stored(db, card)
    assert (brief.heading, brief.record.picked, brief.record.picked_when) == (
        "writing",
        ["writing"],
        "later",
    )
    assert box(sent) == {
        "headings": ["writing"],
        "guess": False,
        "picked": ["writing"],
        "lesson_id": card["lesson_id"],
    }


async def test_pressing_the_agents_guess_makes_it_the_teachers_own(app, client, classroom):
    scripted(app, _drafted(heading="maths"), _drafted(heading="maths"))
    first = await say(client, classroom, "A lesson on linear equations.")
    assert box(first)["guess"] is True
    sent = await picked(client, classroom, "", "maths")
    # Said again: the heading is the same, and it is no longer a guess.
    assert box(sent) == {
        "headings": ["maths"],
        "guess": False,
        "picked": ["maths"],
        "lesson_id": last_card(first)["lesson_id"],
    }


async def test_a_heading_that_still_stands_goes_to_the_next_lesson_written(
    app, client, classroom, db
):
    scripted(
        app,
        _drafted(heading="maths"),
        ASKS,
        _drafted(title="Volcanoes", subject="Geography", topics=["volcanoes"]),
    )
    first = last_card(await say(client, classroom, "A lesson on linear equations."))
    # Pressed beside the first lesson, and the agent answers without redrafting it: the page
    # still shows it pressed when the teacher asks for another lesson.
    await picked(client, classroom, "", "writing")
    other = last_card(await say(client, classroom, "A new lesson on volcanoes."))
    assert other["lesson_id"] != first["lesson_id"]
    _, brief = await _stored(db, other)
    assert (brief.heading, brief.record.picked, brief.record.picked_when) == (
        "writing",
        ["writing"],
        "before",
    )
    _, untouched = await _stored(db, first)
    assert (untouched.heading, untouched.record.picked) == ("maths", [])


async def test_a_heading_that_stands_is_not_put_on_another_lesson_the_teacher_names(
    app, client, classroom, db
):
    scripted(app, _drafted(heading="maths"), ASKS, _drafted(duration_minutes=30))
    first = last_card(await say(client, classroom, "A lesson on linear equations."))
    await press(client, classroom, "new_lesson")
    # Pressed for a lesson that is not written yet.
    asked = await picked(client, classroom, "A lesson on fractions.", "writing")
    assert asked.json()["picked"] == ["writing"]
    # The lesson they go on to name by its title is another one: it keeps its own heading.
    sent = await say(client, classroom, "Make the linear equations lesson half an hour.")
    assert last_card(sent)["lesson_id"] == first["lesson_id"]
    _, brief = await _stored(db, first)
    assert (brief.heading, brief.record.picked) == ("maths", [])


async def test_a_heading_pressed_with_a_message_goes_to_the_lesson_that_message_makes(
    app, client, classroom, db
):
    scripted(
        app,
        _drafted(heading="maths"),
        _drafted(title="Volcanoes", subject="Geography", topics=["volcanoes"], heading="writing"),
    )
    first = last_card(await say(client, classroom, "A lesson on linear equations."))
    other = last_card(await picked(client, classroom, "A new lesson on volcanoes.", "writing"))
    assert other["lesson_id"] != first["lesson_id"]
    _, brief = await _stored(db, other)
    assert (brief.record.picked, brief.record.picked_when) == (["writing"], "before")
    _, untouched = await _stored(db, first)
    assert untouched.record.picked == []


async def test_a_teacher_who_has_pressed_a_heading_is_not_asked_for_one_later(
    app, client, classroom
):
    scripted(app, ASKS, TOPIC)
    await picked(client, classroom, "A lesson on fractions.", "maths")
    assert box(await say(client, classroom, "For twelve year olds.")) is None


# ---------- the demo agent, with no model ----------

BLITZ = "Teach my 13 year olds to write an essay on the Blitz."


async def test_the_demo_agent_asks_for_the_activity_when_given_only_a_topic(client, classroom):
    headers = classroom.headers(classroom.teacher)
    before = (await client.get("/api/teacher/thread", headers=headers)).json()["lessons"]
    sent = await say(client, classroom, "A lesson on fractions.")
    assert box(sent) == {"ask": True}
    # Nothing is drafted until they say what kind of activity it is.
    assert sent.json()["lessons"] == before


async def test_the_demo_agent_drafts_the_topic_once_a_heading_is_pressed(client, classroom, db):
    await say(client, classroom, "A lesson on fractions, for 11 year olds.")
    sent = await picked(client, classroom, "", "maths")
    _, brief = await _stored(db, last_card(sent))
    assert (brief.title, brief.age, brief.heading) == ("Fractions", 11, "maths")
    assert (brief.record.picked, brief.record.picked_when) == (["maths"], "asked")
    words = sent.json()["messages"][-1]["text"]
    assert "I've called it 'Fractions'" in words and "How long is the lesson?" in words
    assert "I'm guessing it is " in words


async def test_the_demo_agent_works_out_the_heading_from_what_students_will_do(
    client, classroom, db
):
    sent = await say(client, classroom, BLITZ)
    _, brief = await _stored(db, last_card(sent))
    assert (brief.heading, brief.listed_kind) == ("writing", "essay writing")
    assert box(sent)["guess"] is True
    assert "I'm guessing it is essay writing." in sent.json()["messages"][-1]["text"]


async def test_the_demo_agent_takes_a_heading_pressed_over_the_lessons_own(client, classroom, db):
    card = last_card(await say(client, classroom, BLITZ))
    sent = await picked(client, classroom, "", "reading")
    _, brief = await _stored(db, card)
    assert (brief.heading, brief.record.picked) == ("reading", ["reading"])
    assert box(sent)["guess"] is False


def test_the_demo_agent_reads_the_words_of_a_message_that_carries_a_picture():
    from app.agent.brief import LessonBrief
    from app.agent.scripted import demo_responder

    picture = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
    content = [{"type": "text", "text": BLITZ}, picture]
    reply = demo_responder("teacher_thread", "", [{"role": "user", "content": content}])
    assert LessonBrief.model_validate(reply["brief"]).heading == "writing"
