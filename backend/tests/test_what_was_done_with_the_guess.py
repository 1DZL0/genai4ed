"""What the teacher did with the agent's guess at the activity, recorded for the research.

One of three: kept it by saying so, kept it by carrying on or approving without a word about
it, or corrected it, with their words and the new kind. The first two are kept apart, since
carrying on is weaker proof the guess was right. The model says whether the teacher's message
spoke to the guess; the server compares what was guessed before and after.
"""

from tests.test_activity_in_the_lesson import _drafted, _stored, scripted
from tests.test_thread import last_card, press, say
from tests.test_where_the_lesson_stands import stands

ESSAY = {"heading": "writing", "activity_kind": "an argumentative essay"}
SAID = "I'm guessing students write an argumentative essay. Tell me if you meant something else."


def guessed(**changes) -> dict:
    """The agent's draft, with its guess at the activity said in the reply."""
    return _drafted(**(ESSAY | changes)) | {"guess_said": SAID}


def spoke(reply: dict, answer: str = "kept") -> dict:
    """A reply that says the teacher's message kept the guess in words, or corrected it."""
    return reply | {"guess_answer": answer}


async def _first(app, client, classroom, *later):
    model = scripted(app, guessed(), *later)
    card = last_card(await say(client, classroom, "An essay on school uniform."))
    return model, card


async def test_a_guess_stands_with_the_sentence_that_said_it(app, client, classroom, db):
    _, card = await _first(app, client, classroom)
    _, brief = await _stored(db, card)
    assert (brief.record.guess, brief.record.said) == ("standing", SAID)
    assert card["activity_type"] == {
        "heading": "writing",
        "label": "Writing tasks",
        "kind": "an argumentative essay",
        "guess": True,
    }


async def test_a_guess_kept_in_words_is_recorded_as_kept_by_saying_so(app, client, classroom, db):
    _, card = await _first(app, client, classroom, spoke(_drafted(**ESSAY, duration_minutes=40)))
    sent = await say(client, classroom, "Yes, an argumentative essay. Make it 40 minutes.")
    _, brief = await _stored(db, last_card(sent))
    assert brief.record.guess == "kept_said"
    # Kept, it is no longer marked as a guess, on the card or in the box above the typing box.
    assert last_card(sent)["activity_type"]["guess"] is False
    assert sent.json()["focus"]["guessing"] is False


async def test_carrying_on_without_a_word_keeps_the_guess_silently(app, client, classroom, db):
    await _first(app, client, classroom, _drafted(**ESSAY, duration_minutes=40))
    sent = await say(client, classroom, "Make it 40 minutes.")
    _, brief = await _stored(db, last_card(sent))
    assert brief.record.guess == "kept_silent"


async def test_a_correction_is_recorded_with_the_teachers_words(app, client, classroom, db):
    letter = spoke(_drafted(heading="writing", activity_kind="a persuasive letter"), "corrected")
    await _first(app, client, classroom, letter)
    words = "No, I want them to write a persuasive letter to the head."
    sent = await say(client, classroom, words)
    _, brief = await _stored(db, last_card(sent))
    assert (brief.record.guess, brief.record.correction) == ("corrected", words)
    assert (brief.activity_kind, brief.kind_from) == ("a persuasive letter", "teacher")


async def test_a_kind_the_agent_changes_by_itself_is_a_new_guess(app, client, classroom, db):
    again = "Now I'm guessing a letter."
    await _first(app, client, classroom, guessed(activity_kind="a letter") | {"guess_said": again})
    sent = await say(client, classroom, "Make it shorter.")
    _, brief = await _stored(db, last_card(sent))
    assert (brief.record.guess, brief.record.said) == ("standing", again)


async def test_speaking_to_the_guess_without_a_change_to_the_lesson_keeps_it_in_words(
    app, client, classroom, db
):
    _, card = await _first(
        app, client, classroom, spoke({"reply": "Good, then it stays.", "show": "nothing"})
    )
    await say(client, classroom, "Yes, that's the kind I meant.")
    _, brief = await _stored(db, card)
    assert brief.record.guess == "kept_said"


async def test_approving_while_the_guess_stands_keeps_it_without_a_word(app, client, classroom, db):
    _, card = await _first(app, client, classroom)
    approved = await press(client, classroom, "approve", lesson_id=card["lesson_id"])
    assert approved.status_code == 200
    _, brief = await _stored(db, card)
    assert brief.record.guess == "kept_silent"
    assert last_card(approved)["activity_type"]["guess"] is False


async def test_a_heading_the_teacher_pressed_with_no_kind_is_no_guess(app, client, classroom, db):
    scripted(app, _drafted(heading="maths"))
    sent = await client.post(
        "/api/teacher/thread/messages",
        json={"text": "A lesson on fractions.", "picks": ["maths"]},
        headers=classroom.headers(classroom.teacher),
    )
    _, brief = await _stored(db, last_card(sent))
    assert brief.record.guess == ""
    assert last_card(sent)["activity_type"]["guess"] is False


async def test_the_agent_is_told_whether_the_teacher_has_spoken_to_its_guess(
    app, client, classroom
):
    model, _ = await _first(
        app,
        client,
        classroom,
        _drafted(**ESSAY, duration_minutes=40),
        _drafted(**ESSAY, age=14),
    )
    await say(client, classroom, "Make it 40 minutes.")
    assert "they have not spoken to it yet" in stands(model, call=1)
    await say(client, classroom, "For 14 year olds.")
    assert "which they kept" in stands(model, call=2)


async def test_a_lesson_from_before_the_guess_was_recorded_is_decided_the_same_way(
    app, client, classroom, db
):
    _, card = await _first(app, client, classroom, _drafted(**ESSAY, duration_minutes=40))
    lesson, brief = await _stored(db, card)
    # Drafted before the record kept the guess: a worked-out heading and kind, nothing said.
    brief.record = brief.record.model_copy(update={"guess": "", "said": ""})
    lesson.brief = brief.model_dump(mode="json")
    await db.commit()
    sent = await say(client, classroom, "Make it 40 minutes.")
    _, after = await _stored(db, last_card(sent))
    assert after.record.guess == "kept_silent"


async def test_words_about_the_guess_after_approval_leave_the_approved_lesson_alone(
    app, client, classroom, db
):
    _, card = await _first(app, client, classroom, spoke({"reply": "Good.", "show": "nothing"}))
    await press(client, classroom, "approve", lesson_id=card["lesson_id"])
    await say(client, classroom, "Yes, an essay is right.")
    _, brief = await _stored(db, card)
    assert brief.record.guess == "kept_silent"


LETTER = {"heading": "writing", "activity_kind": "a persuasive letter"}


async def test_a_verdict_stands_until_the_teacher_speaks_again(app, client, classroom, db):
    words = "No, I want them to write a persuasive letter to the head."
    reworded = _drafted(heading="writing", activity_kind="a persuasive letter to the head")
    await _first(app, client, classroom, spoke(_drafted(**LETTER), "corrected"), reworded)
    await say(client, classroom, words)
    # The agent rewords the kind on a later turn the teacher did not speak to it on.
    sent = await say(client, classroom, "Make step 2 harder.")
    _, brief = await _stored(db, last_card(sent))
    assert (brief.record.guess, brief.record.correction) == ("corrected", words)


async def test_a_guess_kept_in_words_is_kept_however_the_agent_rewords_it(
    app, client, classroom, db
):
    reworded = spoke(_drafted(heading="writing", activity_kind="an argumentative essay on uniform"))
    await _first(app, client, classroom, reworded)
    sent = await say(client, classroom, "Yes, that's it. Make it 40 minutes.")
    _, brief = await _stored(db, last_card(sent))
    assert (brief.record.guess, brief.record.correction) == ("kept_said", "")


async def test_a_correction_with_no_new_draft_yet_is_recorded_as_a_correction(
    app, client, classroom, db
):
    asks = spoke({"reply": "What should they do instead?", "show": "nothing"}, "corrected")
    _, card = await _first(app, client, classroom, asks)
    sent = await say(client, classroom, "No, not an essay.")
    _, brief = await _stored(db, card)
    assert (brief.record.guess, brief.record.correction) == ("corrected", "No, not an essay.")
    assert sent.json()["focus"]["guessing"] is False


async def test_a_heading_pressed_after_the_guess_was_kept_is_guessed_again(
    app, client, classroom, db
):
    from tests.test_activity_box import picked

    inference = _drafted(heading="reading", activity_kind="making inferences")
    await _first(app, client, classroom, spoke(_drafted(**ESSAY, age=14)), inference)
    await say(client, classroom, "Yes, an essay. For 14 year olds.")
    sent = await picked(client, classroom, "", "reading")
    _, brief = await _stored(db, last_card(sent))
    assert brief.record.guess == "standing"
