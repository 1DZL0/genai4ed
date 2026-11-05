"""A student's lesson as a conversation with the class agent, through the API."""

import pytest
from sqlalchemy import select

from app.agent.brief import LessonBrief
from app.models import Exception_

BRIEF = LessonBrief.model_validate(
    {
        "title": "Photosynthesis",
        "subject": "science",
        "objectives": ["Explain what plants need to make glucose"],
        "steps": [
            {
                "name": "What plants need",
                "kind": "question",
                "goal": "Name what a plant takes in for photosynthesis",
                "prompt_ideas": ["What does a plant need to make its own food?"],
                "success_criteria": ["Names light, water and carbon dioxide"],
            },
            {"name": "Explain it", "kind": "check", "goal": "Explain photosynthesis"},
        ],
        "topics": ["photosynthesis"],
    }
)


@pytest.fixture
async def lesson(db, classroom):
    classroom.contract.brief = BRIEF.model_dump(mode="json")
    await db.commit()
    return classroom


def url(lesson, tail=""):
    return f"/api/learn/{lesson.session.id}{tail}"


async def test_opening_the_lesson_starts_the_conversation_once(client, lesson):
    alice = lesson.headers(lesson.alice)
    first = (await client.post(url(lesson, "/start"), headers=alice)).json()
    assert [line["who"] for line in first["lines"]] == ["agent"]
    assert first["task"] == "What does a plant need to make its own food?"
    assert [s["state"] for s in first["steps"]] == ["current", "todo"]
    again = (await client.post(url(lesson, "/start"), headers=alice)).json()
    assert len(again["lines"]) == 1


async def test_answering_moves_through_the_activity(client, lesson):
    alice = lesson.headers(lesson.alice)
    await client.post(url(lesson, "/start"), headers=alice)
    r = await client.post(
        url(lesson, "/messages"),
        json={"text": "It needs light from the sun, water from the soil and carbon dioxide"},
        headers=alice,
    )
    view = r.json()
    assert r.status_code == 200, r.text
    assert view["step_index"] == 1
    assert [s["state"] for s in view["steps"]] == ["done", "current"]


async def test_a_button_sends_the_student_s_request(client, lesson):
    alice = lesson.headers(lesson.alice)
    await client.post(url(lesson, "/start"), headers=alice)
    view = (
        await client.post(url(lesson, "/messages"), json={"intent": "example"}, headers=alice)
    ).json()
    assert view["lines"][-2] == {
        **view["lines"][-2],
        "who": "student",
        "text": "Can you give me an example?",
    }


async def test_a_paused_lesson_can_be_read_but_not_talked_to(client, db, lesson):
    alice = lesson.headers(lesson.alice)
    await client.post(url(lesson, "/start"), headers=alice)
    lesson.session.status = "paused"
    await db.commit()
    view = (await client.get(url(lesson), headers=alice)).json()
    assert view["can_talk"] is False
    r = await client.post(url(lesson, "/messages"), json={"text": "hello"}, headers=alice)
    assert r.status_code == 409


async def test_asking_for_the_teacher_always_reaches_them(client, db, lesson):
    alice = lesson.headers(lesson.alice)
    view = (await client.post(url(lesson, "/request-teacher"), headers=alice)).json()
    assert view["lines"][-1]["who"] == "note"
    [alert] = (await db.scalars(select(Exception_))).all()
    assert alert.kind == "teacher_requested"


async def test_a_student_outside_the_lesson_gets_nothing(client, lesson):
    outsider = lesson.headers(lesson.outsider)
    assert (await client.get(url(lesson), headers=outsider)).status_code == 404
    r = await client.post(url(lesson, "/messages"), json={"text": "hi"}, headers=outsider)
    assert r.status_code == 404


async def test_students_see_only_their_own_conversation(client, lesson):
    await client.post(url(lesson, "/start"), headers=lesson.headers(lesson.alice))
    await client.post(
        url(lesson, "/messages"),
        json={"text": "alice private words"},
        headers=lesson.headers(lesson.alice),
    )
    bob = (await client.post(url(lesson, "/start"), headers=lesson.headers(lesson.bob))).json()
    assert all("alice private words" not in line["text"] for line in bob["lines"])


async def test_my_lessons_lists_running_agent_lessons(client, lesson):
    cards = (await client.get("/api/learn", headers=lesson.headers(lesson.alice))).json()
    assert [(c["title"], c["steps"]) for c in cards] == [("Photosynthesis", 2)]


async def test_a_student_can_say_whether_a_reply_helped(client, lesson):
    alice = lesson.headers(lesson.alice)
    view = (await client.post(url(lesson, "/start"), headers=alice)).json()
    # What the rules allow right now, in the student's terms.
    assert view["help"] == {
        "hint": True,
        "worked_step_in": 1,
        "answer_in": None,
        "ladder": False,
    }
    reply = view["lines"][0]
    assert reply["who"] == "agent" and reply["helped"] is None
    rated = await client.post(
        url(lesson, f"/lines/{reply['id']}/helped"), json={"helped": True}, headers=alice
    )
    assert rated.status_code == 200 and rated.json()["lines"][0]["helped"] is True
    # Only the agent's replies, and only by the student they were written to.
    other = await client.post(
        url(lesson, f"/lines/{reply['id']}/helped"),
        json={"helped": False},
        headers=lesson.headers(lesson.bob),
    )
    assert other.status_code == 404


async def test_two_tabs_opening_a_lesson_at_once_share_one_learning_state(engine, classroom):
    """A double tap or a second tab used to race the get-or-create and one of them failed on
    the unique constraint; now both land on the same row."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.agent.student_mode import learning_state

    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def open_once():
        async with maker() as db:
            state = await learning_state(
                db, session_id=classroom.session.id, student_id=classroom.alice.id, steps=2
            )
            await db.commit()
            return state.id

    first, second = await asyncio.gather(open_once(), open_once())
    assert first == second


async def test_a_pupil_has_a_daily_turn_cap(client, db, classroom, monkeypatch):
    """One bored class, or one bot past the gate, must not be an open bill: past the cap the
    pupil is asked to see their teacher and nothing reaches the model."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "student_turns_per_day", 2)
    alice = classroom.headers(classroom.alice)
    url = f"/api/learn/{classroom.session.id}/messages"
    assert (await client.post(url, json={"text": "x = 9"}, headers=alice)).status_code == 200
    assert (await client.post(url, json={"text": "x = 6"}, headers=alice)).status_code == 200
    third = await client.post(url, json={"text": "x = 5"}, headers=alice)
    assert third.status_code == 429
    assert "teacher" in third.json()["detail"].lower()
    # Another pupil is not held back by this one's count.
    bob = classroom.headers(classroom.bob)
    assert (await client.post(url, json={"text": "x = 9"}, headers=bob)).status_code == 200


async def test_when_time_is_up_the_pupil_waits_and_the_teacher_decides(client, db, classroom):
    """At zero the clock stops the pupils and asks the teacher; it no longer ends the lesson.
    Adding minutes opens the boxes again."""
    from datetime import UTC, datetime, timedelta

    from app.models import Session
    from tests.test_thread import press

    sid = classroom.session.id
    alice = classroom.headers(classroom.alice)
    session = await db.get(Session, sid)
    session.closes_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()

    view = (await client.get(f"/api/learn/{sid}", headers=alice)).json()
    assert view["status"] == "open"
    assert view["time_up"] is True and view["can_talk"] is False
    refused = await client.post(f"/api/learn/{sid}/messages", json={"text": "x = 5"}, headers=alice)
    assert refused.status_code == 409
    assert "time" in refused.json()["detail"].lower()

    assert (await press(client, classroom, "extend", session_id=sid, minutes=10)).status_code == 200
    view = (await client.get(f"/api/learn/{sid}", headers=alice)).json()
    assert view["time_up"] is False and view["can_talk"] is True
    again = await client.post(f"/api/learn/{sid}/messages", json={"text": "x = 5"}, headers=alice)
    assert again.status_code == 200


async def test_listing_lessons_writes_nothing(client, db, classroom):
    """Looking at the list must not create state rows for lessons never opened."""
    from app.models import LearningState

    alice = classroom.headers(classroom.alice)
    assert (await client.get("/api/learn", headers=alice)).status_code == 200
    assert (await db.scalars(select(LearningState))).all() == []


async def test_each_step_carries_its_own_question_for_the_header(client, classroom):
    alice = classroom.headers(classroom.alice)
    view = (await client.get(f"/api/learn/{classroom.session.id}", headers=alice)).json()
    assert all(s["question"] for s in view["steps"])
    assert "3x + 4 = 19" in view["steps"][0]["question"]
