"""The end-of-lesson review for a full class. On 22 November a 30-pupil review asked for the
summary and every pupil's outcome in one reply, ran past its reply limit and was cut off: ten
pupils got no outcome and no memory lines. A bigger class is now reviewed in batches, with the
class summary asked for on its own, and a pupil a batch left out is asked for once more.

The fixture's class has two pupils, so these tests make a batch one pupil."""

import json
import uuid

from sqlalchemy import select

from app.agent import classroom, learner, llm
from app.models import AgentTurn, ClassInsight, LessonOutcome
from tests.test_memory_across_lessons import end
from tests.test_what_the_record_shows import OPEN, lesson, wrong

WHOLE_CLASS = "The whole class got as far as the second step."


async def both_wrote(client, c):
    """Alice and Bob each write once in the lesson, and the teacher ends it."""
    sid = c.session.id
    await lesson(client, c, ("x = 5", wrong("x = 5")))
    c.tutor._replies.extend([OPEN, wrong("x is 7")])
    bob = c.headers(c.bob)
    assert (await client.post(f"/api/learn/{sid}/start", headers=bob)).status_code == 200
    typed = await client.post(f"/api/learn/{sid}/messages", json={"text": "x is 7"}, headers=bob)
    assert typed.status_code == 200, typed.text
    await end(client, c)


def handed(system: str) -> dict:
    """The lesson as one review call was handed it."""
    value, _ = json.JSONDecoder().raw_decode(system.split("The lesson:\n", 1)[1])
    return value


def asked_ids(call: dict) -> list[str]:
    return [s["student_id"] for s in handed(call["system"])["students"]]


def is_summary_call(messages: list[dict]) -> bool:
    return messages[0]["content"] == classroom.REVIEW_ASK_SUMMARY


def outcome(student_id: str, keep: str = "You kept going.") -> dict:
    return {
        "student_id": student_id,
        "criteria": [],
        "keep": keep,
        "develop": [],
        "learns": [f"Line on {student_id[:8]}."],
    }


class Model(llm.ScriptedClient):
    """A scripted review model that answers each call for exactly the students it was given,
    leaving out any student `drop` says to on that asking, and keeps the room each call asked
    for. The summary call gets a summary, and an outcome it was told not to send."""

    def __init__(self, drop=lambda student_id, asked: False) -> None:
        super().__init__(self.answer)
        self.drop = drop
        self.asked: dict[str, int] = {}
        self.room: list[int] = []

    def answer(self, purpose: str, system: str, messages: list[dict]) -> dict:
        students = [s["student_id"] for s in handed(system)["students"]]
        if is_summary_call(messages):
            return {
                "summary": WHOLE_CLASS,
                "outcomes": [outcome(s, keep="From the summary call.") for s in students],
            }
        kept = []
        for s in students:
            self.asked[s] = self.asked.get(s, 0) + 1
            if not self.drop(s, self.asked[s]):
                kept.append(outcome(s))
        return {"summary": "One pupil's part.", "outcomes": kept}

    async def complete(self, *, max_tokens: int, **kwargs) -> llm.LLMResult:
        self.room.append(max_tokens)
        return await super().complete(max_tokens=max_tokens, **kwargs)


def outcome_calls(model: Model) -> list[dict]:
    return [c for c in model.calls if not is_summary_call(c["messages"])]


async def outcomes_by_student(db, c) -> dict[uuid.UUID, LessonOutcome]:
    rows = await db.scalars(select(LessonOutcome).where(LessonOutcome.session_id == c.session.id))
    return {o.student_id: o for o in rows.all()}


async def test_a_big_class_is_reviewed_in_batches_and_every_pupil_gets_an_outcome(
    db, client, three, monkeypatch
):
    monkeypatch.setattr(classroom, "REVIEW_BATCH", 1)
    await both_wrote(client, three)
    model = Model()

    created = await classroom.suggest_outcomes(db, model, session=three.session)

    alice, bob = str(three.alice.id), str(three.bob.id)
    # One call per batch of at most one pupil, and one summary call over the whole class.
    summaries = [c for c in model.calls if is_summary_call(c["messages"])]
    assert len(summaries) == 1 and sorted(asked_ids(summaries[0])) == sorted([alice, bob])
    batches = outcome_calls(model)
    assert len(batches) == 2
    assert all(len(asked_ids(c)) <= classroom.REVIEW_BATCH for c in batches)
    assert sorted(i for c in batches for i in asked_ids(c)) == sorted([alice, bob])
    # Every pupil gets an outcome, from their batch, and their memory lines.
    by_student = await outcomes_by_student(db, three)
    assert set(by_student) == {three.alice.id, three.bob.id} == {o.student_id for o in created}
    assert {o.suggested["keep"] for o in by_student.values()} == {"You kept going."}
    assert (await learner.latest(db, three.alice.id)).written == [f"Line on {alice[:8]}."]
    assert (await learner.latest(db, three.bob.id)).written == [f"Line on {bob[:8]}."]
    # Each model call is kept as its own turn.
    turns = (await db.scalars(select(AgentTurn).where(AgentTurn.mode == "review"))).all()
    assert len(turns) == 3
    assert {t.prompt_version for t in turns} == {classroom.REVIEW_PROMPT_VERSION}


async def test_the_class_summary_comes_from_the_summary_call(db, client, three, monkeypatch):
    monkeypatch.setattr(classroom, "REVIEW_BATCH", 1)
    await both_wrote(client, three)

    await classroom.suggest_outcomes(db, Model(), session=three.session)

    [insight] = (await db.scalars(select(ClassInsight))).all()
    assert insight.summary == WHOLE_CLASS
    # What the summary call sent as outcomes anyway is not used.
    by_student = await outcomes_by_student(db, three)
    assert "From the summary call." not in {o.suggested["keep"] for o in by_student.values()}


async def test_a_pupil_left_out_of_their_batch_is_asked_for_once_more(
    db, client, three, monkeypatch
):
    monkeypatch.setattr(classroom, "REVIEW_BATCH", 1)
    await both_wrote(client, three)
    bob = str(three.bob.id)
    model = Model(drop=lambda student_id, asked: student_id == bob and asked == 1)

    await classroom.suggest_outcomes(db, model, session=three.session)

    # The second try is one more call, holding only Bob.
    batches = outcome_calls(model)
    assert len(batches) == 3 and asked_ids(batches[-1]) == [bob]
    assert model.asked[bob] == 2
    assert set(await outcomes_by_student(db, three)) == {three.alice.id, three.bob.id}
    assert len((await db.scalars(select(AgentTurn).where(AgentTurn.mode == "review"))).all()) == 4


async def test_a_pupil_still_left_out_after_the_second_try_has_no_outcome(
    db, client, three, monkeypatch
):
    monkeypatch.setattr(classroom, "REVIEW_BATCH", 1)
    await both_wrote(client, three)
    bob = str(three.bob.id)
    model = Model(drop=lambda student_id, asked: student_id == bob)

    created = await classroom.suggest_outcomes(db, model, session=three.session)

    assert model.asked[bob] == 2
    assert [o.student_id for o in created] == [three.alice.id]
    assert set(await outcomes_by_student(db, three)) == {three.alice.id}
    note = await learner.latest(db, three.bob.id)
    assert note is None or note.written == []


async def test_every_review_call_asks_for_the_full_reply_room(db, client, three, monkeypatch):
    assert classroom.REVIEW_MAX_TOKENS == 12000
    await both_wrote(client, three)
    small = Model()
    await classroom.suggest_outcomes(db, small, session=three.session)
    monkeypatch.setattr(classroom, "REVIEW_BATCH", 1)
    batched = Model(drop=lambda student_id, asked: asked == 1)

    await classroom.suggest_outcomes(db, batched, session=three.session)

    assert small.room == [classroom.REVIEW_MAX_TOKENS]
    # A summary call, two batches, and a second try for both pupils, itself in batches.
    assert batched.room == [classroom.REVIEW_MAX_TOKENS] * 5
    assert all(len(asked_ids(c)) <= classroom.REVIEW_BATCH for c in outcome_calls(batched))


async def test_a_small_class_is_still_reviewed_in_one_call(db, client, three):
    await both_wrote(client, three)
    model = llm.ScriptedClient(
        [
            {
                "summary": WHOLE_CLASS,
                "outcomes": [outcome(str(three.alice.id)), outcome(str(three.bob.id))],
            }
        ]
    )

    created = await classroom.suggest_outcomes(db, model, session=three.session)

    [call] = model.calls
    assert sorted(asked_ids(call)) == sorted([str(three.alice.id), str(three.bob.id)])
    assert call["messages"] == [
        {"role": "user", "content": "Summarise the lesson and suggest outcomes."}
    ]
    assert {o.student_id for o in created} == {three.alice.id, three.bob.id}
    [insight] = (await db.scalars(select(ClassInsight))).all()
    assert insight.summary == WHOLE_CLASS
