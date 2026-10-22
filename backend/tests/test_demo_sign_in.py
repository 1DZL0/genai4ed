"""Demo sign-in: any username and password, for trying the platform out."""

import pytest

from app.auth import COOKIE_NAME
from app.config import get_settings


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_sign_in", True)
    # Prove the cookie does the work, not the test-only header.
    monkeypatch.setattr(get_settings(), "dev_identity_enabled", False)


async def demo(client, role, username, password="1", teacher=None):
    return await client.post(
        "/api/auth/demo",
        json={"role": role, "username": username, "password": password, "teacher": teacher},
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


async def test_a_new_teacher_gets_the_sample_lesson_ready_to_start(client, demo_on):
    response = await demo(client, "teacher", "1")
    assert response.status_code == 200
    assert response.json()["role"] == "teacher"
    assert COOKIE_NAME in response.cookies

    shown = await client.post("/api/teacher/thread/actions", json={"action": "show_lessons"})
    lessons = shown.json()["showing"]["lessons"]
    assert [lesson["title"] for lesson in lessons] == ["Linear equations: unknown on both sides"]
    assert all(lesson["status"] == "active" for lesson in lessons)
    assert (await client.get("/api/teacher/thread")).json()["strip"] == []


async def test_a_new_student_can_talk_to_the_agent_in_a_demo_lesson(client, demo_on):
    await demo(client, "teacher", "ms-k")
    await start_first_lesson(client)
    client.cookies.clear()

    assert (
        await demo(client, "student", "alex", password="anything", teacher="ms-k")
    ).status_code == 200
    [lesson] = (await client.get("/api/learn")).json()
    opened = (await client.post(f"/api/learn/{lesson['session_id']}/start")).json()
    assert opened["lines"][0]["who"] == "agent"
    answered = await client.post(
        f"/api/learn/{lesson['session_id']}/messages",
        json={"text": "The chloroplast, because it has chlorophyll to capture light"},
    )
    assert answered.status_code == 200


async def test_a_new_teachers_class_starts_empty(client, demo_on):
    """Students already signed in belong to their own teacher; a new teacher doesn't get them."""
    await demo(client, "student", "alex", teacher="teacher-1")
    client.cookies.clear()
    await demo(client, "teacher", "ms-k")
    session_id = await start_first_lesson(client)

    shown = await client.post(
        "/api/teacher/thread/actions",
        json={"action": "show_class", "session_id": session_id},
    )
    assert shown.json()["showing"]["students"] == []


async def test_the_same_name_signs_back_in_as_the_same_person(client, demo_on):
    first = (await demo(client, "teacher", "1", password="1")).json()
    client.cookies.clear()
    again = (await demo(client, "teacher", "1", password="different")).json()
    assert first == again
    lessons = (await client.get("/api/teacher/thread/lessons")).json()["lessons"]
    assert len(lessons) == 1  # the sample was made once, not twice


async def test_a_name_cannot_be_both_teacher_and_student(client, demo_on):
    await demo(client, "teacher", "1")
    response = await demo(client, "student", "1")
    assert response.status_code == 409
    assert "teacher" in response.json()["detail"]


async def test_a_blank_name_is_refused(client, demo_on):
    assert (await demo(client, "student", "   ")).status_code == 422


async def test_a_browser_can_be_a_teacher_and_a_student_at_the_same_time(client, demo_on):
    await demo(client, "teacher", "1")
    await demo(client, "student", "kid", teacher="1")
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


async def test_two_students_in_one_browser_each_keep_their_own_tab(client, demo_on):
    """One student signing in must not take over another's tab: each tab has its own sign-in."""
    first, second, fresh = ({"x-tab": t} for t in ("tabfirst1", "tabsecond2", "tabfresh3"))

    async def who(tab):
        r = await client.get("/api/auth/me", params={"role": "student"}, headers=tab)
        return r.json()["pseudonym"] if r.status_code == 200 else r.status_code

    for tab, name in ((first, "pupil-a"), (second, "pupil-b")):
        r = await client.post(
            "/api/auth/demo",
            json={"role": "student", "username": name, "password": "1", "teacher": "teacher-1"},
            headers=tab,
        )
        assert r.status_code == 200
    assert (await who(first), await who(second)) == ("pupil-a", "pupil-b")
    # A new tab can't tell which of the two it is, so it signs in for itself.
    assert await who(fresh) == 401

    await client.post("/api/auth/logout", params={"role": "student"}, headers=second)
    assert await who(first) == "pupil-a"
    # The tab that signed out is signed out: it does not become the other student.
    assert await who(second) == 401
    # With one student left in this browser, a new tab is them: no second sign-in needed.
    assert await who(fresh) == "pupil-a"


async def test_a_new_student_names_their_teacher_and_a_returning_one_keeps_their_classes(
    client, demo_on
):
    await demo(client, "teacher", "ms-k")
    await start_first_lesson(client)
    client.cookies.clear()
    refused = await demo(client, "student", "wanderer")
    assert refused.status_code == 422 and "teacher" in refused.json()["detail"]
    assert (await demo(client, "student", "pupil-k", teacher="ms-k")).status_code == 200
    client.cookies.clear()
    # Back with no teacher named: still in ms-k's class, and put in nobody else's.
    assert (await demo(client, "student", "pupil-k")).status_code == 200
    assert len((await client.get("/api/learn")).json()) == 1


async def test_the_standing_teacher_names_are_kept_and_a_lookalike_student_blocks_nobody(
    client, demo_on
):
    taken = await demo(client, "student", "Teacher-1", teacher="teacher-2")
    assert taken.status_code == 409
    await demo(client, "teacher", "Bob")
    client.cookies.clear()
    # A student whose name differs from the teacher's only in case.
    assert (await demo(client, "student", "bob", teacher="Bob")).status_code == 200
    client.cookies.clear()
    assert (await demo(client, "student", "pupil-b", teacher="bob")).status_code == 200


async def test_a_long_teacher_name_signs_in_and_a_control_character_is_refused(client, demo_on):
    # The class is named after the teacher; its label must still fit.
    assert (await demo(client, "teacher", "t" * 64)).status_code == 200
    assert (await demo(client, "teacher", "bad\x00name")).status_code == 422


async def test_a_mistyped_teacher_is_refused_and_the_case_of_the_name_does_not_matter(
    client, demo_on
):
    await demo(client, "teacher", "Ms-Kay")
    client.cookies.clear()
    wrong = await demo(client, "student", "pupil-q", teacher="ms-kai")
    assert wrong.status_code == 404 and "no teacher called" in wrong.json()["detail"]
    assert (await demo(client, "student", "pupil-q", teacher="ms-kay")).status_code == 200
    # The standing demo teachers are made the first time a student names one.
    assert (await demo(client, "student", "pupil-r", teacher="Teacher-2")).status_code == 200


async def test_naming_a_student_as_the_teacher_is_refused_and_spaces_are_ignored(client, demo_on):
    await demo(client, "teacher", "ms-k")
    client.cookies.clear()
    await demo(client, "student", "pupil-z", teacher="ms-k")
    client.cookies.clear()
    refused = await demo(client, "student", "pupil-y", teacher="pupil-z")
    assert refused.status_code == 404 and "pupil-z" in refused.json()["detail"]
    ok = await demo(client, "student", "pupil-x", teacher="  ms-k ")
    assert ok.status_code == 200
    # No second teacher called "  ms-k " was made.
    taken = await demo(client, "student", "ms-k ")
    assert taken.status_code == 409
