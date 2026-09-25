"""Demo sign-in: any username and password, for trying the platform out."""

import pytest

from app.auth import COOKIE_NAME
from app.config import get_settings


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_sign_in", True)
    # Prove the cookie does the work, not the test-only header.
    monkeypatch.setattr(get_settings(), "dev_identity_enabled", False)


async def demo(client, role, username, password="1"):
    return await client.post(
        "/api/auth/demo", json={"role": role, "username": username, "password": password}
    )


async def start_first_lesson(client) -> str:
    """The signed-in teacher starts their first sample lesson with their class; its session id."""
    have = (await client.get("/api/teacher/thread/lessons")).json()
    run = await client.post(
        "/api/teacher/thread/actions",
        json={
            "action": "run",
            "lesson_id": have["lessons"][-1]["lesson_id"],
            "class_id": have["classes"][0]["id"],
        },
    )
    assert run.status_code == 200, run.text
    return run.json()["showing"]["session_id"]


async def test_demo_sign_in_is_off_unless_switched_on(client):
    assert (await demo(client, "teacher", "1")).status_code == 404
    assert (await client.get("/api/auth/config")).json() == {"demo_sign_in": False}


async def test_a_new_teacher_gets_sample_lessons_ready_to_start(client, demo_on):
    response = await demo(client, "teacher", "1")
    assert response.status_code == 200
    assert response.json()["role"] == "teacher"
    assert COOKIE_NAME in response.cookies

    shown = await client.post("/api/teacher/thread/actions", json={"action": "show_lessons"})
    lessons = shown.json()["showing"]["lessons"]
    assert {lesson["title"] for lesson in lessons} >= {
        "Photosynthesis",
        "Argumentative paragraphs: choosing a career",
    }
    assert all(lesson["status"] == "active" for lesson in lessons)
    assert (await client.get("/api/teacher/thread")).json()["strip"] == []


async def test_a_new_student_can_talk_to_the_agent_in_a_demo_lesson(client, demo_on):
    await demo(client, "teacher", "ms-k")
    await start_first_lesson(client)
    client.cookies.clear()

    assert (await demo(client, "student", "alex", password="anything")).status_code == 200
    [lesson] = (await client.get("/api/learn")).json()
    opened = (await client.post(f"/api/learn/{lesson['session_id']}/start")).json()
    assert opened["lines"][0]["who"] == "agent"
    answered = await client.post(
        f"/api/learn/{lesson['session_id']}/messages",
        json={"text": "The chloroplast, because it has chlorophyll to capture light"},
    )
    assert answered.status_code == 200


async def test_existing_students_join_a_new_teachers_class(client, demo_on):
    await demo(client, "student", "alex")
    client.cookies.clear()
    await demo(client, "teacher", "ms-k")
    session_id = await start_first_lesson(client)

    shown = await client.post(
        "/api/teacher/thread/actions",
        json={"action": "show_class", "session_id": session_id},
    )
    board = shown.json()["showing"]
    assert [s["pseudonym"] for s in board["students"]] == ["alex"]


async def test_the_same_name_signs_back_in_as_the_same_person(client, demo_on):
    first = (await demo(client, "teacher", "1", password="1")).json()
    client.cookies.clear()
    again = (await demo(client, "teacher", "1", password="different")).json()
    assert first == again
    lessons = (await client.get("/api/teacher/thread/lessons")).json()["lessons"]
    assert len(lessons) == 3  # the samples were made once, not twice


async def test_a_name_cannot_be_both_teacher_and_student(client, demo_on):
    await demo(client, "teacher", "1")
    response = await demo(client, "student", "1")
    assert response.status_code == 409
    assert "teacher" in response.json()["detail"]


async def test_a_blank_name_is_refused(client, demo_on):
    assert (await demo(client, "student", "   ")).status_code == 422


async def test_a_browser_can_be_a_teacher_and_a_student_at_the_same_time(client, demo_on):
    await demo(client, "teacher", "1")
    await demo(client, "student", "kid")
    assert (await client.get("/api/auth/me?role=teacher")).json()["role"] == "teacher"
    assert (await client.get("/api/auth/me?role=student")).json()["role"] == "student"
    assert (await client.get("/api/teacher/thread")).status_code == 200
    assert (await client.get("/api/learn")).status_code == 200
    assert (await client.post("/api/auth/logout?role=student")).status_code == 204
    assert (await client.get("/api/auth/me?role=student")).status_code == 401
    assert (await client.get("/api/auth/me?role=teacher")).status_code == 200


async def test_a_student_of_one_teacher_is_not_in_the_others_class(client, demo_on):
    await demo(client, "teacher", "1")
    await start_first_lesson(client)
    await demo(client, "teacher", "2")
    kid = await client.post(
        "/api/auth/demo",
        json={"role": "student", "username": "kid-of-1", "password": "x", "teacher": "1"},
    )
    assert kid.status_code == 200
    mine = (await client.get("/api/learn")).json()
    assert mine and all(lesson["title"] for lesson in mine)
    await demo(client, "teacher", "1")
    assert (await client.get("/api/teacher/thread")).json()["strip"][0]["students"] == 1
    await demo(client, "teacher", "2")
    assert (await client.get("/api/teacher/thread")).json()["strip"] == []


async def test_removing_a_running_lesson_ends_its_run(client, demo_on):
    await demo(client, "teacher", "ms-k")
    await start_first_lesson(client)
    have = (await client.get("/api/teacher/thread/lessons")).json()
    running = next(row for row in have["lessons"] if row["live"])
    gone = await client.post(
        "/api/teacher/thread/actions",
        json={"action": "delete_lesson", "lesson_id": running["lesson_id"]},
    )
    assert gone.status_code == 200
    assert gone.json()["strip"] == []
