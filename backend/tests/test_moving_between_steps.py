"""A pupil can leave a step for later, go back to one, and change an answer: the record keeps
every attempt, and the tutor is handed the step the pupil is on, its own talk and its own
counts, every time."""

import pytest
from sqlalchemy import select

from app.agent import scaffold
from app.agent import steps as step_rows
from app.agent.brief import LessonBrief
from app.agent.policy import PolicyRules, from_teachers_words
from app.agent.student_mode import learning_state
from app.enums import EvidenceKind, ExceptionKind
from app.models import EvidenceRecord, Exception_

from .lessons import THREE


def turn(message, move="ask", **extra):
    return {"message": message, "move": move, **extra}


OPEN = turn("Hi! Solve 3x + 4 = 19.", task="Solve 3x + 4 = 19")


def wrong(said):
    return turn(
        "Not yet: what do you do with the 4?",
        move="hint",
        student_attempted=True,
        disclosure="hint",
        assessment={"judgment": "not_met", "evidence_quote": said},
    )


def met(said, task="Next question"):
    return turn(
        "Yes, that's it.",
        move="advance",
        student_attempted=True,
        step_done=True,
        task=task,
        assessment={"judgment": "met", "evidence_quote": said},
    )


def script(c, *replies):
    c.tutor._replies.extend(replies)


def url(c, tail=""):
    return f"/api/learn/{c.session.id}{tail}"


async def start(client, c):
    r = await client.post(url(c, "/start"), headers=c.headers(c.alice))
    assert r.status_code == 200, r.text
    return r.json()


async def write(client, c, text):
    r = await client.post(url(c, "/messages"), json={"text": text}, headers=c.headers(c.alice))
    assert r.status_code == 200, r.text
    return r.json()


async def move(client, c, **body):
    return await client.post(url(c, "/move"), json=body, headers=c.headers(c.alice))


async def state_of(db, c):
    return await learning_state(db, session_id=c.session.id, student_id=c.alice.id, steps=3)


# ---------- leaving a step for later ----------


async def test_leaving_a_step_for_later_parks_it_and_the_tutor_opens_the_next(db, client, three):
    script(
        three,
        OPEN,
        wrong("x is 7"),
        wrong("x is 8"),
        turn("Part 2 now: solve 5x - 7 = 2x + 8.", task="Solve 5x - 7 = 2x + 8"),
    )
    await start(client, three)
    await write(client, three, "x is 7")
    await write(client, three, "x is 8")
    r = await move(client, three, leave=0)
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["step_index"] == 1
    assert [s["state"] for s in view["steps"]] == ["parked", "current", "todo"]
    assert any(line["who"] == "note" and "for later" in line["text"] for line in view["lines"])

    state = await state_of(db, three)
    assert state.steps[0]["parked"] and state.steps[0]["wrong"] == 2
    assert state.attempts_on_step == 0
    opened = three.tutor.calls[-1]
    assert "leaving the last one for later" in opened["system"]
    # The tutor opening part 2 is handed part 2's talk, not part 1's.
    assert not any("x is 7" in m["content"] for m in opened["messages"])
    # The arrival is told once: the next turn is an ordinary one.
    assert not state.steps[1].get("arrived")
    moved = (
        await db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.kind == EvidenceKind.STEP_CHANGE.value)
            .order_by(EvidenceRecord.created_at)
        )
    ).all()
    assert (moved[-1].payload["move"], moved[-1].payload["from"], moved[-1].payload["to"]) == (
        "parked",
        0,
        1,
    )


async def test_coming_back_restores_the_wrong_tries_and_the_talk_of_that_step(db, client, three):
    script(
        three,
        OPEN,
        wrong("x is 7"),
        wrong("x is 8"),
        turn("Part 2 now: solve 5x - 7 = 2x + 8.", task="Solve 5x - 7 = 2x + 8"),
        wrong("my step two working"),
        turn("Back to part 1. You had the 4 to deal with.", task="Solve 3x + 4 = 19"),
    )
    await start(client, three)
    await write(client, three, "x is 7")
    await write(client, three, "x is 8")
    await move(client, three, leave=0)
    await write(client, three, "my step two working")
    r = await move(client, three, to=0)
    assert r.status_code == 200, r.text
    view = r.json()
    assert [s["state"] for s in view["steps"]] == ["current", "parked", "todo"]
    # Two wrong tries on part 1 are still two: the help the rules allow carries on from there.
    assert view["wrong_tries"] == 2 and view["help"]["worked_step_in"] == 0

    state = await state_of(db, three)
    assert (state.step_index, state.attempts_on_step) == (0, 2)
    assert state.steps[1]["parked"] and state.steps[1]["wrong"] == 1
    back = three.tutor.calls[-1]
    assert "come back to this step" in back["system"]
    said = [m["content"] for m in back["messages"]]
    assert "x is 7" in said and "my step two working" not in said


async def test_in_order_a_pupil_cannot_jump_past_a_part_not_reached(db, client, three):
    script(three, OPEN, turn("Part 2 now.", task="Solve 5x - 7 = 2x + 8"))
    view = await start(client, three)
    assert [s["reachable"] for s in view["steps"]] == [True, True, False]
    assert view["can_leave"] and not view["free_movement"]
    refused = await move(client, three, to=2)
    assert refused.status_code == 409
    # The next part not done is always open; the one left unfinished is parked.
    went = await move(client, three, to=1)
    assert went.status_code == 200
    assert [s["state"] for s in went.json()["steps"]] == ["parked", "current", "todo"]


async def test_with_free_movement_a_pupil_can_go_to_any_part(db, client, three):
    brief = LessonBrief.model_validate(three.contract.brief)
    brief.rules = brief.rules.model_copy(update={"free_movement": True})
    three.contract.brief = brief.model_dump(mode="json")
    await db.commit()
    script(three, OPEN, turn("Part 3: solve 2(x - 3) = 18.", task="Solve 2(x - 3) = 18"))
    view = await start(client, three)
    assert view["free_movement"] and all(s["reachable"] for s in view["steps"])
    went = await move(client, three, to=2)
    assert went.status_code == 200 and went.json()["step_index"] == 2
    assert "has just chosen to start this step" in three.tutor.calls[-1]["system"]


# ---------- finishing, and changing an answer ----------


async def test_meeting_the_last_part_with_one_parked_sends_them_back_to_it(db, client, three):
    script(
        three,
        OPEN,
        turn("Part 2 now.", task="Solve 5x - 7 = 2x + 8"),
        met("x = 5, 3x = 15"),
        met("x = 12"),
        met("3x = 15 so x = 5"),
    )
    await start(client, three)
    await move(client, three, leave=0)
    await write(client, three, "x = 5, 3x = 15")
    on_last = await write(client, three, "x = 12")
    # Part 3 is not the end while part 1 waits: the tutor was told part 1 comes next.
    told = three.tutor.calls[-1]["system"]
    assert 'Coming next: step 1, "Warm up"' in told and "This is the last step" not in told
    assert on_last["step_index"] == 0 and not on_last["completed"]
    finished = await write(client, three, "3x = 15 so x = 5")
    assert finished["completed"]
    assert [s["state"] for s in finished["steps"]] == ["done", "done", "done"]


async def test_going_back_to_a_finished_part_lets_them_change_the_answer(db, client, three):
    script(
        three,
        OPEN,
        met("3x = 15 so x = 5"),
        met("x = 5, 3x = 15"),
        met("x = 12"),
        turn("Back to part 1. What would you change?", task="Solve 3x + 4 = 19"),
        wrong("x = 6"),
        met("x = 5 after all"),
    )
    await start(client, three)
    await write(client, three, "3x = 15 so x = 5")
    await write(client, three, "x = 5, 3x = 15")
    done = await write(client, three, "x = 12")
    assert done["completed"]
    r = await move(client, three, to=0)
    assert r.status_code == 200, r.text
    # Still finished: going back to look or to improve does not undo it. The part they are
    # revising shows as the one they are on.
    assert r.json()["completed"] and r.json()["step_index"] == 0
    assert [s["state"] for s in r.json()["steps"]] == ["current", "done", "done"]
    assert "already finished, to change or improve" in three.tutor.calls[-1]["system"]

    changed = await write(client, three, "x = 6")
    # A wrong answer now counts: that part is no longer met, so the lesson is not finished.
    assert not changed["completed"]
    state = await state_of(db, three)
    # The answer that counts is the latest, and the change is kept in the record.
    assert state.steps[0]["judgment"] == "not_met" and state.steps[0]["changed"]
    again = await write(client, three, "x = 5 after all")
    assert again["completed"]
    state = await state_of(db, three)
    assert state.steps[0]["judgment"] == "met"
    # Finished again, the part is no longer the one they are on: the strip shows every part done.
    assert [s["state"] for s in again["steps"]] == ["done", "done", "done"]


async def assessments(db):
    return (
        await db.scalars(
            select(EvidenceRecord).where(EvidenceRecord.kind == EvidenceKind.ASSESSMENT.value)
        )
    ).all()


async def test_coming_back_to_change_an_answer_judges_nothing_until_they_write(db, client, three):
    """Seen live: on reopening a finished part the tutor judged the old answer as a new one
    and said the lesson was finished. The arrival has nothing new from the pupil, so whatever
    the model returns, nothing is judged, counted or moved, and the tutor is told so."""
    script(
        three,
        OPEN,
        met("3x = 15 so x = 5"),
        met("x = 5, 3x = 15"),
        met("x = 12"),
        # The arrival, written as if the old answer had just been sent.
        met("x = 5, 3x = 15", task="Solve 5x - 7 = 2x + 8"),
    )
    await start(client, three)
    for said in ("3x = 15 so x = 5", "x = 5, 3x = 15", "x = 12"):
        await write(client, three, said)
    judged = len(await assessments(db))
    before = await state_of(db, three)
    attempts = before.steps[1].get("attempts", 0)

    r = await move(client, three, to=1)
    assert r.status_code == 200, r.text
    assert r.json()["step_index"] == 1 and r.json()["completed"]
    assert len(await assessments(db)) == judged
    state = await state_of(db, three)
    assert state.steps[1].get("attempts", 0) == attempts
    assert not state.steps[1].get("changed")
    assert "have not written anything new yet" in three.tutor.calls[-1]["system"]
    # Seen live: the system line alone was not enough, because the part's talk ended with the
    # old answer and the model replied to that. The last message now says what happened.
    last = three.tutor.calls[-1]["messages"][-1]
    assert last["role"] == "user" and last["content"].startswith("(Not from the student")
    assert "have not written anything since" in last["content"]


async def test_the_tutor_opening_a_part_cannot_finish_it(db, client, three):
    """Leaving a part for later opens the next with no words from the pupil: a reply that
    judges and moves on anyway leaves them on the part just opened, with nothing judged."""
    script(
        three,
        OPEN,
        wrong("x is 7"),
        met("x = 5, 3x = 15", task="Solve 2(x + 3) = 14"),
    )
    await start(client, three)
    await write(client, three, "x is 7")
    judged = len(await assessments(db))
    r = await move(client, three, leave=0)
    assert r.status_code == 200, r.text
    assert r.json()["step_index"] == 1
    assert [s["state"] for s in r.json()["steps"]] == ["parked", "current", "todo"]
    assert len(await assessments(db)) == judged
    # The question it opened with is still the part's task.
    assert (await state_of(db, three)).steps[1]["task"] == "Solve 2(x + 3) = 14"


async def test_looking_back_at_a_finished_part_keeps_the_lesson_finished(db, client, three):
    """A pupil who finished and taps a part to read it again is still finished, whether they
    write nothing more or confirm the same answer, and the finish is not recorded twice."""
    from app.models import EvidenceRecord

    script(
        three,
        OPEN,
        met("3x = 15 so x = 5"),
        met("x = 5, 3x = 15"),
        met("x = 12"),
        turn("Back to part 1. What would you change?", task="Solve 3x + 4 = 19"),
        met("I'd keep x = 5"),
    )
    await start(client, three)
    for said in ("3x = 15 so x = 5", "x = 5, 3x = 15", "x = 12"):
        await write(client, three, said)
    looked = (await move(client, three, to=0)).json()
    assert looked["completed"]
    assert (await client.get(url(three), headers=three.headers(three.alice))).json()["completed"]
    kept = await write(client, three, "I'd keep x = 5")
    assert kept["completed"]

    finishes = [
        e
        for e in (await db.scalars(select(EvidenceRecord))).all()
        if e.kind == EvidenceKind.STEP_CHANGE.value and e.payload.get("completed")
    ]
    assert len(finishes) == 1


async def test_the_last_part_left_cannot_be_left_for_later(db, client, three):
    script(three, OPEN, met("3x = 15 so x = 5"), met("x = 5, 3x = 15"))
    await start(client, three)
    await write(client, three, "3x = 15 so x = 5")
    view = await write(client, three, "x = 5, 3x = 15")
    assert view["step_index"] == 2 and not view["can_leave"]
    assert (await move(client, three, leave=2)).status_code == 409


async def test_leaving_a_part_clears_a_struggling_alert_about_it(db, client, three):
    db.add(
        Exception_(
            session_id=three.session.id,
            student_id=three.alice.id,
            kind=ExceptionKind.STRUGGLING.value,
            priority=2,
            summary="Not getting there on part 1.",
            payload={"step_index": 0},
        )
    )
    await db.commit()
    script(three, OPEN, turn("Part 2 now.", task="Solve 5x - 7 = 2x + 8"))
    await start(client, three)
    await move(client, three, leave=0)
    alert = (await db.scalars(select(Exception_))).one()
    assert alert.status == "resolved"
    assert alert.payload["cleared_because"] == "left step 1 for later"


# ---------- the teacher's setting and the tutor's words ----------


def test_free_movement_is_a_teachers_setting_read_literally():
    assert from_teachers_words(PolicyRules(), "Pupils move freely between steps.").free_movement
    free = PolicyRules(free_movement=True)
    assert not from_teachers_words(free, "Pupils move in order.").free_movement
    assert "Pupils move freely" in free.labels()["pills"]
    assert "Pupils move freely" not in PolicyRules().labels()["pills"]
    assert "Pupils can move freely between the parts." in free.describe()


def test_a_teacher_who_rules_out_moving_freely_keeps_the_parts_in_order():
    """Said in the negative, moving freely is ruled out, not switched on; and when the words
    say it more than once, the latest saying counts."""
    for said in (
        "Pupils must not move freely between the parts.",
        "They shouldn't move freely, keep them in order.",
        "Students can never move freely.",
    ):
        assert not from_teachers_words(PolicyRules(), said).free_movement, said
    changed_mind = "Pupils move in order. Actually, pupils move freely between steps."
    assert from_teachers_words(PolicyRules(), changed_mind).free_movement
    back = "Pupils move freely between steps. Pupils move in order."
    assert not from_teachers_words(PolicyRules(free_movement=True), back).free_movement


def test_the_tutor_may_mention_the_later_button_after_two_wrong_tries():
    offered = scaffold.noticed_block(scaffold.Noticed(attempts=2, can_leave=True))
    assert "Come back to this later" in offered
    assert "Come back to this later" not in scaffold.noticed_block(
        scaffold.Noticed(attempts=1, can_leave=True)
    )
    assert "Come back to this later" not in scaffold.noticed_block(
        scaffold.Noticed(attempts=3, can_leave=False)
    )


def test_the_step_block_names_the_part_that_really_comes_next():
    wrapped = scaffold.step_block(THREE, 2, task=None, after=[0])
    assert 'Coming next: step 1, "Warm up"' in wrapped and "last step" not in wrapped
    alone = scaffold.step_block(THREE, 1, task=None, after=[])
    assert "This is the last step: a met answer ends the lesson." in alone
    # Without an order given, it is the lesson's order, as before.
    assert 'Coming next: step 3, "Brackets"' in scaffold.step_block(THREE, 1, task=None)
    met, todo = {"judgment": "met"}, {"judgment": None}
    assert step_rows.still_to_do([todo, met, todo], 2, 3) == [0]
    assert step_rows.still_to_do([todo, todo, todo], 0, 3) == [1, 2]
    assert step_rows.still_to_do([met, todo, {"skipped": True}], 1, 3) == []


def test_the_panels_moving_sentences_are_taken_literally():
    from app.agent.policy import PANEL_PREFIX, literal_rules

    free = literal_rules(PolicyRules(), f"{PANEL_PREFIX} Pupils move freely between steps.")
    assert free.free_movement
    back = literal_rules(free, f"{PANEL_PREFIX} Pupils move in order.")
    assert not back.free_movement


async def test_leaving_a_part_twice_leaves_only_that_part(db, client, three):
    """The request names the part being left, so a repeat (a second device, a retry after a
    dropped connection) cannot park the next part as well, and costs no model call."""
    script(three, OPEN, turn("Part 2 now.", task="Solve 5x - 7 = 2x + 8"))
    await start(client, three)
    first = await move(client, three, leave=0)
    calls = len(three.tutor.calls)
    again = await move(client, three, leave=0)
    assert again.status_code == 200, again.text
    assert again.json()["step_index"] == 1 == first.json()["step_index"]
    assert [s["state"] for s in again.json()["steps"]] == ["parked", "current", "todo"]
    assert len(three.tutor.calls) == calls


async def test_going_to_the_part_you_are_on_asks_nothing_of_the_tutor(db, client, three):
    script(three, OPEN)
    await start(client, three)
    calls = len(three.tutor.calls)
    r = await move(client, three, to=0)
    assert r.status_code == 200 and r.json()["step_index"] == 0
    assert len(three.tutor.calls) == calls


@pytest.mark.parametrize("body", [{}, {"to": 1, "leave": 0}, {"to": None, "leave": None}])
async def test_a_move_says_either_where_to_go_or_which_part_to_leave(db, client, three, body):
    script(three, OPEN)
    await start(client, three)
    assert (await move(client, three, **body)).status_code == 422


async def test_a_right_line_with_a_step_back_does_not_finish_the_part(db, client, three):
    """The tutor sends the pupil back a step while saying the line was right: the part they
    were on is part met, not done, so they are brought back to it later."""
    script(
        three,
        OPEN,
        met("3x = 15 so x = 5"),
        turn(
            "Right so far. Let's look at part 1 again first.",
            move="revisit",
            student_attempted=True,
            assessment={"judgment": "met", "evidence_quote": "5x - 2x = 15"},
        ),
    )
    await start(client, three)
    await write(client, three, "3x = 15 so x = 5")
    view = await write(client, three, "5x - 2x = 15")
    assert view["step_index"] == 0
    state = await state_of(db, three)
    assert state.steps[1]["judgment"] == "partial"
    assert view["steps"][1]["state"] != "done"


async def test_a_pupil_who_never_moved_has_only_the_recent_talk_read(
    db, client, three, monkeypatch
):
    """The whole conversation is read only once the pupil has moved between parts, to pick
    out the talk of the part they are on; otherwise the last window is enough."""
    import sys

    from app.agent import context, store

    asked = []
    real = store.messages

    async def spy(db, conversation_id, **kwargs):
        # Only the tutor's read; the pupil's page reads its own lines separately.
        if sys._getframe(1).f_code.co_name == "_gather":
            asked.append(kwargs.get("limit"))
        return await real(db, conversation_id, **kwargs)

    monkeypatch.setattr(store, "messages", spy)
    script(three, OPEN, wrong("x is 7"), turn("Part 2 now.", task="Solve 5x - 7 = 2x + 8"))
    await start(client, three)
    await write(client, three, "x is 7")
    assert asked and set(asked) == {context.CONVERSATION_WINDOW}
    asked.clear()
    await move(client, three, leave=0)
    assert None in asked
