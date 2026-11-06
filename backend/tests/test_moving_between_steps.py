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
    assert not r.json()["completed"] and r.json()["step_index"] == 0
    assert "already finished, to change or improve" in three.tutor.calls[-1]["system"]

    await write(client, three, "x = 6")
    state = await state_of(db, three)
    # The answer that counts is the latest, and the change is kept in the record.
    assert state.steps[0]["judgment"] == "not_met" and state.steps[0]["changed"]
    again = await write(client, three, "x = 5 after all")
    assert again["completed"]
    state = await state_of(db, three)
    assert state.steps[0]["judgment"] == "met"


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
