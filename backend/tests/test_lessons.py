"""Lessons: booking, starting, today and history.

Students are admitted when a lesson starts, so a student who joins the class
after it was booked still gets in, and nobody can reach a lesson before then.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.enums import SessionStatus, TeacherAction
from app.models import Enrolment, LessonContract, TeacherAccessLog, User


def teacher(classroom, who=None):
    return classroom.headers(who or classroom.teacher)


async def book(client, classroom, **extra):
    return await client.post(
        "/api/teacher/lessons",
        json={
            "plan_version_id": str(classroom.contract.id),
            "class_id": str(classroom.klass.id),
            **extra,
        },
        headers=teacher(classroom),
    )


async def start(client, classroom, lesson_id):
    return await client.post(f"/api/teacher/lessons/{lesson_id}/start", headers=teacher(classroom))


async def test_booking_needs_an_approved_lesson_and_your_own_class(client, classroom, db):
    other_class = await client.post(
        "/api/teacher/lessons",
        json={"plan_version_id": str(classroom.contract.id), "class_id": str(classroom.klass.id)},
        headers=teacher(classroom, classroom.other_teacher),
    )
    assert other_class.status_code == 404

    contract = await db.get(LessonContract, classroom.contract.id)
    contract.status = "draft"
    await db.commit()
    assert (await book(client, classroom)).status_code == 409


async def test_a_booked_lesson_waits_and_admits_nobody_yet(client, classroom):
    lesson = (await book(client, classroom)).json()
    assert lesson["status"] == SessionStatus.SCHEDULED.value
    assert lesson["closes_at"] is None
    assert lesson["students"] == 2  # the class size, shown before it starts
    assert lesson["steps"] == 3

    response = await client.get(
        f"/api/learn/{lesson['lesson_id']}", headers=classroom.headers(classroom.alice)
    )
    assert response.status_code == 404


async def test_starting_admits_the_class_as_it_is_now(client, classroom, db):
    lesson = (await book(client, classroom)).json()
    late = User(pseudonym="10B-09", role="student")
    db.add(late)
    await db.flush()
    db.add(Enrolment(class_id=classroom.klass.id, student_id=late.id))
    await db.commit()

    started = (await start(client, classroom, lesson["lesson_id"])).json()
    assert started["status"] == SessionStatus.OPEN.value
    assert started["students"] == 3


async def test_the_clock_runs_for_the_length_in_the_brief(client, classroom, db):
    lesson = (await book(client, classroom)).json()
    started = (await start(client, classroom, lesson["lesson_id"])).json()
    opened = datetime.fromisoformat(started["opened_at"])
    closes = datetime.fromisoformat(started["closes_at"])
    assert closes - opened == timedelta(minutes=20)
    assert (await start(client, classroom, lesson["lesson_id"])).status_code == 409

    actions = [log.action for log in (await db.scalars(select(TeacherAccessLog))).all()]
    assert {TeacherAction.SCHEDULE_LESSON.value, TeacherAction.START_LESSON.value} <= set(actions)


async def test_today_lists_whats_coming_and_whats_finished(client, classroom, db):
    booked = (await book(client, classroom)).json()
    tomorrow = (
        await book(
            client, classroom, scheduled_for=(datetime.now(UTC) + timedelta(days=1)).isoformat()
        )
    ).json()

    classroom.session.status = SessionStatus.CLOSED.value
    classroom.session.closed_at = datetime.now(UTC)
    await db.commit()

    body = (await client.get("/api/teacher/today", headers=teacher(classroom))).json()
    coming = [lesson["lesson_id"] for lesson in body["coming_up"]]
    assert booked["lesson_id"] in coming
    assert tomorrow["lesson_id"] not in coming
    assert [lesson["lesson_id"] for lesson in body["finished"]] == [str(classroom.session.id)]

    theirs = (
        await client.get("/api/teacher/today", headers=teacher(classroom, classroom.other_teacher))
    ).json()
    assert theirs == {"coming_up": [], "finished": []}


async def test_past_lessons_can_be_filtered_by_class(client, classroom, db):
    classroom.session.status = SessionStatus.CLOSED.value
    classroom.session.closed_at = datetime.now(UTC) - timedelta(days=30)
    await db.commit()
    everything = (await client.get("/api/teacher/lessons/past", headers=teacher(classroom))).json()
    assert [lesson["lesson_id"] for lesson in everything] == [str(classroom.session.id)]
    other = await client.get(
        "/api/teacher/lessons/past",
        params={"class_id": "00000000-0000-0000-0000-000000000000"},
        headers=teacher(classroom),
    )
    assert other.json() == []
