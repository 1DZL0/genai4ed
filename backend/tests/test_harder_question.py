"""A harder question for a pupil who is finding it easy: when the teacher switches it on, the
tutor may keep a pupil who got a step right first time on that step for one harder question of
its own, before they move on. The step is already theirs: the extra question takes one try,
changes no mark, and the pupil moves on whatever they answer. A scripted tutor plays both
sides; the prompt it was handed and the record it left are read back. No model is called."""

from sqlalchemy import select

from app import study
from app.agent import classroom, harder
from app.agent import steps as step_rows
from app.agent.student_mode import StudentAgent, learning_state
from app.enums import EvidenceKind
from app.models import AgentTurn, EvidenceRecord
from tests.lessons import THREE
from tests.test_memory_across_lessons import EARLIER, end, line, next_lesson, shown_at_the_start
from tests.test_memory_settings import MEMORY, set_memory
from tests.test_what_the_record_shows import lesson, met, turn, wrong

OFFER = "A harder question: allowed on this step, once."
ANSWERING = "Your last question was a harder one of your own"
WHY = "Why does taking 4 from both sides keep the equation true?"
FIRST = "3x = 15 so x = 5"
BECAUSE = "because both sides lose the same amount"
BOTH_SIDES = "Solve 5x - 7 = 2x + 8"


def asks_harder(said, question=WHY):
    """The tutor judges the answer met and keeps the pupil for a harder question of its own."""
    return turn(
        f"Yes, that is right. One extra, just for you: {question}",
        move="harder",
        student_attempted=True,
        task=question,
        assessment={"judgment": "met", "evidence_quote": said},
    )


def closes(said, judgment="partial", **more):
    """The tutor's reply to the pupil's one try at the harder question, opening the next step."""
    return turn(
        f"Good thinking. A full answer says both sides stay equal. Now: {BOTH_SIDES}",
        move="advance",
        student_attempted=True,
        task=BOTH_SIDES,
        assessment={"judgment": judgment, "evidence_quote": said, **more},
    )


async def switched_on(client, c):
    return await set_memory(client, c, harder_questions=True)


async def where(db, c):
    """Alice's place in the lesson and her record of each step."""
    state = await learning_state(db, session_id=c.session.id, student_id=c.alice.id, steps=3)
    return state, step_rows.padded(state.steps, 3)


async def records(db, c, kind):
    return (
        await db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.session_id == c.session.id, EvidenceRecord.kind == kind.value)
            .order_by(EvidenceRecord.created_at)
        )
    ).all()


async def page(client, c):
    r = await client.get(f"/api/learn/{c.session.id}", headers=c.headers(c.alice))
    assert r.status_code == 200, r.text
    return r.json()


def handed(c) -> str:
    """The prompt the tutor was handed for its latest reply."""
    return c.tutor.calls[-1]["system"]


# ---------- the switch ----------


async def test_the_switch_is_off_until_the_teacher_turns_it_on(client, three):
    r = await client.get(MEMORY, headers=three.headers(three.teacher))
    assert r.json()["settings"]["harder_questions"] is False
    assert (await switched_on(client, three))["settings"]["harder_questions"] is True
    r = await client.get(MEMORY, headers=three.headers(three.teacher))
    assert r.json()["settings"]["harder_questions"] is True


async def test_switched_off_the_tutor_is_told_nothing_of_it_and_holds_nobody(db, client, three):
    await lesson(client, three, (FIRST, asks_harder(FIRST)))
    assert "harder question" not in handed(three).lower()
    state, rows = await where(db, three)
    # As before the switch existed: a right line without moving on is part met, on the step.
    assert (state.step_index, rows[0]["judgment"]) == (0, "partial")
    assert "harder" not in rows[0]


# ---------- when it is offered ----------


async def test_a_first_typed_answer_is_offered_it_and_the_opening_is_not(db, client, three):
    await switched_on(client, three)
    await lesson(client, three, (FIRST, met(FIRST, task=BOTH_SIDES)))
    opening, answer = (call["system"] for call in three.tutor.calls)
    assert OFFER not in opening
    assert OFFER in answer
    # Under what is allowed now, above the teacher's guidance, which outranks it.
    assert (
        answer.index("Allowed right now") < answer.index(OFFER) < answer.index("Teacher's guidance")
    )
    turns = (await db.scalars(select(AgentTurn).order_by(AgentTurn.created_at))).all()
    assert [t.context_manifest["harder"] for t in turns] == [None, "offered"]


async def test_it_is_not_offered_after_a_wrong_try(client, three):
    await switched_on(client, three)
    await lesson(client, three, ("x = 7", wrong("x = 7")), (FIRST, met(FIRST, task=BOTH_SIDES)))
    assert OFFER not in handed(three)


async def test_it_is_not_offered_on_a_help_button(client, three):
    await switched_on(client, three)
    await lesson(client, three)
    three.tutor._replies.append(turn("It asks you to find x.", move="explain"))
    r = await client.post(
        f"/api/learn/{three.session.id}/messages",
        json={"text": "", "intent": "dont_understand"},
        headers=three.headers(three.alice),
    )
    assert r.status_code == 200, r.text
    assert OFFER not in handed(three)


async def test_it_is_not_offered_on_the_last_step_to_do(client, three):
    await switched_on(client, three)
    await lesson(
        client,
        three,
        (FIRST, met(FIRST, task=BOTH_SIDES)),
        ("3x = 15, x = 5", met("3x = 15, x = 5", task="Solve 2(x - 3) = 18")),
        ("x = 12", met("x = 12")),
    )
    first, second, last = (call["system"] for call in three.tutor.calls[1:])
    assert OFFER in first and OFFER in second
    assert OFFER not in last


async def test_it_is_not_offered_in_a_study_arm(db, client, three):
    await switched_on(client, three)
    await next_lesson(db, three, THREE, condition=study.condition_for(three.alice.id, 1))
    await lesson(client, three, (FIRST, met(FIRST, task=BOTH_SIDES)))
    assert OFFER not in handed(three)


def test_what_rules_it_out_on_a_step():
    fresh = {"judgment": None, "attempts": 0, "task": "Solve 3x + 4 = 19"}

    def offered(row=fresh, **changed):
        said = {"on": True, "answering": True, "wrong": 0, "left": [1, 2], **changed}
        return harder.offered(row, **said)

    assert offered()
    assert not offered(on=False)
    assert not offered(answering=False)
    assert not offered(wrong=1)
    assert not offered(left=[])
    assert not offered(in_study=True)
    assert not offered(finished=True)
    for mark in (
        {"attempts": 1},
        {"hints": 1},
        {"examples": 1},
        {"worked": 1},
        {"returns": 1},
        {"skipped": True},
        {"judgment": "met"},
        {"harder": {"question": WHY, "open": False, "judgment": "met"}},
    ):
        assert not offered({**fresh, **mark}), mark


# ---------- the tutor asks one ----------


async def test_a_harder_question_keeps_the_pupil_on_a_step_that_is_already_theirs(
    db, client, three
):
    await switched_on(client, three)
    await lesson(client, three, (FIRST, asks_harder(FIRST)))
    state, rows = await where(db, three)
    assert state.step_index == 0
    assert rows[0]["judgment"] == "met"
    assert rows[0]["harder"] == {"question": WHY, "open": True}
    # The step keeps its own question; the harder one is beside it, not in its place.
    assert rows[0]["task"] == "Solve 3x + 4 = 19"
    judged = await records(db, three, EvidenceKind.ASSESSMENT)
    assert [r.payload["judgment"] for r in judged] == ["met"]


async def test_the_pupil_sees_the_harder_question_above_the_box(client, three):
    await switched_on(client, three)
    await lesson(client, three, (FIRST, asks_harder(FIRST)))
    view = await page(client, three)
    assert view["step_index"] == 0
    assert view["steps"][0]["state"] == "current"
    assert (view["steps"][0]["question"], view["task"]) == (WHY, WHY)


# ---------- the pupil's one try ----------


async def test_their_answer_moves_them_on_and_is_kept_apart_from_the_step(db, client, three):
    await switched_on(client, three)
    await lesson(client, three, (FIRST, asks_harder(FIRST)), (BECAUSE, closes(BECAUSE)))
    state, rows = await where(db, three)
    assert state.step_index == 1
    assert rows[0]["judgment"] == "met"
    assert rows[0]["harder"] == {"question": WHY, "open": False, "judgment": "partial"}
    assert rows[0]["attempts"] == 1
    assert rows[1]["task"] == BOTH_SIDES

    (kept,) = await records(db, three, EvidenceKind.HARDER_QUESTION)
    assert kept.student_id == three.alice.id
    assert {
        "step_index": 0,
        "step_name": "Warm up",
        "question": WHY,
        "judgment": "partial",
        "evidence_quote": BECAUSE,
    }.items() <= kept.payload.items()
    # The step's own record holds the one answer that met it and nothing of the extra.
    judged = await records(db, three, EvidenceKind.ASSESSMENT)
    assert [r.payload["evidence_quote"] for r in judged] == [FIRST]

    view = await page(client, three)
    assert view["steps"][1]["question"] == BOTH_SIDES
    assert view["steps"][0]["question"] == "Solve 3x + 4 = 19"


async def test_a_wrong_answer_to_it_costs_nothing(db, client, three):
    """Not a wrong try, no struggle, no misconception raised, and the reply is not held back
    for moving on without a met answer."""
    await switched_on(client, three)
    reply = closes("no idea", judgment="not_met", misconception="Thinks it only works for 4")
    await lesson(client, three, (FIRST, asks_harder(FIRST)), ("no idea", reply))
    state, rows = await where(db, three)
    assert (state.step_index, state.attempts_on_step, state.struggle_turns) == (1, 0, 0)
    assert rows[0]["judgment"] == "met"
    assert not rows[0].get("skipped")
    assert rows[0]["harder"]["judgment"] == "not_met"
    assert await records(db, three, EvidenceKind.SIGNAL) == []
    assert await records(db, three, EvidenceKind.POLICY_EVENT) == []
    view = await page(client, three)
    assert view["lines"][-1]["text"] == reply["message"]


async def test_the_tutor_is_told_it_is_their_one_try_at_its_own_question(db, client, three):
    await switched_on(client, three)
    await lesson(client, three, (FIRST, asks_harder(FIRST)), (BECAUSE, closes(BECAUSE)))
    system = handed(three)
    assert ANSWERING in system
    assert f'The question on screen now: "{WHY}"' in system
    assert OFFER not in system
    turns = (await db.scalars(select(AgentTurn).order_by(AgentTurn.created_at))).all()
    assert [t.context_manifest["harder"] for t in turns] == [None, "offered", "answering"]


async def test_one_to_a_step_and_the_next_step_can_have_its_own(client, three):
    await switched_on(client, three)
    second = "3x = 15, x = 5"
    await lesson(
        client,
        three,
        (FIRST, asks_harder(FIRST)),
        (BECAUSE, closes(BECAUSE)),
        (second, met(second, task="Solve 2(x - 3) = 18")),
    )
    assert OFFER in handed(three)


async def test_a_help_button_on_it_leaves_it_open(db, client, three):
    await switched_on(client, three)
    await lesson(client, three, (FIRST, asks_harder(FIRST)))
    three.tutor._replies.append(turn("Think about a pair of scales.", move="explain"))
    r = await client.post(
        f"/api/learn/{three.session.id}/messages",
        json={"text": "", "intent": "dont_understand"},
        headers=three.headers(three.alice),
    )
    assert r.status_code == 200, r.text
    state, rows = await where(db, three)
    assert state.step_index == 0
    assert rows[0]["harder"] == {"question": WHY, "open": True}
    # Help with the extra question is not help the step needed.
    assert not any(rows[0].get(k) for k in ("hints", "examples", "worked"))
    system = handed(three)
    assert ANSWERING not in system
    assert "It is about your harder question" in system
    assert await records(db, three, EvidenceKind.HARDER_QUESTION) == []


# ---------- moving away from it ----------


async def test_leaving_the_step_closes_it_unanswered(db, client, three):
    await switched_on(client, three)
    await lesson(client, three, (FIRST, asks_harder(FIRST)))
    three.tutor._replies.append(turn(f"Part 2 now: {BOTH_SIDES}", task=BOTH_SIDES))
    r = await client.post(
        f"/api/learn/{three.session.id}/move", json={"leave": 0}, headers=three.headers(three.alice)
    )
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["step_index"] == 1
    assert [s["state"] for s in view["steps"]] == ["done", "current", "todo"]
    # The step is done, so it was not "left for later".
    assert not any("for later" in said["text"] for said in view["lines"])
    state, rows = await where(db, three)
    assert rows[0]["harder"] == {"question": WHY, "open": False, "judgment": None}
    assert rows[0]["judgment"] == "met"
    assert await records(db, three, EvidenceKind.HARDER_QUESTION) == []


async def test_the_teacher_moving_them_on_closes_it_too(db, client, three):
    await switched_on(client, three)
    await lesson(client, three, (FIRST, asks_harder(FIRST)))
    three.tutor._replies.append(
        turn(f"Your teacher asked me to move you on. {BOTH_SIDES}", move="advance", task=BOTH_SIDES)
    )
    await StudentAgent(three.tutor).respond(
        db,
        session=three.session,
        contract=three.contract,
        student=three.alice,
        text=None,
        guidance="Move her on to part 2.",
    )
    state, rows = await where(db, three)
    assert state.step_index == 1
    assert rows[0]["harder"] == {"question": WHY, "open": False, "judgment": None}
    assert (rows[0]["judgment"], rows[0].get("skipped")) == ("met", None)


# ---------- who is told afterwards ----------


async def test_the_teacher_sees_it_among_the_pupils_evidence(db, client, three):
    await switched_on(client, three)
    await lesson(client, three, (FIRST, asks_harder(FIRST)), (BECAUSE, closes(BECAUSE)))
    view = await classroom.student_view(db, three.session, three.alice)
    (shown,) = [e for e in view["evidence"] if e["kind"] == EvidenceKind.HARDER_QUESTION.value]
    assert shown["text"] == "A harder question on “Warm up”: partly right"
    assert WHY in shown["detail"] and BECAUSE in shown["detail"]
    assert view["steps"][0]["judgment"] == "met"
    assert view["summary"][0] == "1 of 3 steps met."


async def test_the_next_lessons_tutor_is_told_how_it_went(db, client, three):
    await switched_on(client, three)
    await lesson(client, three, (FIRST, asks_harder(FIRST)), (BECAUSE, closes(BECAUSE)))
    await end(client, three)
    await next_lesson(db, three)
    recalled = line(await shown_at_the_start(client, three), EARLIER)
    assert "right first time" in recalled
    assert "Then a harder question of the tutor's own: partly right" in recalled
