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


async def test_demo_sign_in_is_off_unless_switched_on(client):
    assert (await demo(client, "teacher", "1")).status_code == 404
    assert (await client.get("/api/auth/config")).json() == {"demo_sign_in": False}


async def test_a_new_teacher_gets_sample_lessons_and_one_running(client, demo_on):
    response = await demo(client, "teacher", "1")
    assert response.status_code == 200
    assert response.json()["role"] == "teacher"
    assert COOKIE_NAME in response.cookies

    lessons = (await client.get("/api/teacher/designs")).json()
    assert {lesson["title"] for lesson in lessons} >= {
        "Photosynthesis",
        "Argumentative paragraphs: choosing a career",
    }
    assert all(lesson["status"] == "active" for lesson in lessons)
    [running] = (await client.get("/api/teacher/today")).json()["coming_up"]
    assert (running["status"], running["class_label"]) == ("open", "1's class")


async def test_a_new_student_can_talk_to_the_agent_in_a_demo_lesson(client, demo_on):
    await demo(client, "teacher", "ms-k")
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

    [running] = (await client.get("/api/teacher/today")).json()["coming_up"]
    live = (await client.get(f"/api/teacher/live/{running['lesson_id']}")).json()
    assert [s["pseudonym"] for s in live["students"]] == ["alex"]


async def test_the_same_name_signs_back_in_as_the_same_person(client, demo_on):
    first = (await demo(client, "teacher", "1", password="1")).json()
    client.cookies.clear()
    again = (await demo(client, "teacher", "1", password="different")).json()
    assert first == again
    assert len((await client.get("/api/teacher/today")).json()["coming_up"]) == 1


async def test_a_name_cannot_be_both_teacher_and_student(client, demo_on):
    await demo(client, "teacher", "1")
    response = await demo(client, "student", "1")
    assert response.status_code == 409
    assert "teacher" in response.json()["detail"]


async def test_a_blank_name_is_refused(client, demo_on):
    assert (await demo(client, "student", "   ")).status_code == 422
