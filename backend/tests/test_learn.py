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
