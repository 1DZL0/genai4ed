"""Lessons: booking, starting, phases, today, history and review.

The concept note keeps AI work to bounded intervals, so the headline check is
that a student cannot use their tutor while the lesson is in a phase with
tutors off - enforced by the server, not by a hidden button.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.enums import SessionStatus, TeacherAction
from app.models import Enrolment, LessonContract, TeacherAccessLog, User

TIMELINE = [
    {"name": "Explanation", "minutes": 10, "tutors_on": False},
    {"name": "Tutor time", "minutes": 30, "tutors_on": True},
    {"name": "Class discussion", "minutes": 5, "tutors_on": False},
]


async def with_timeline(db, classroom):
    contract = await db.get(LessonContract, classroom.contract.id)
    contract.timeline = TIMELINE
    await db.commit()


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


async def phase(client, classroom, lesson_id, index):
    return await client.post(
        f"/api/teacher/lessons/{lesson_id}/phase", json={"index": index}, headers=teacher(classroom)
    )


async def attempt(client, classroom, lesson_id, answer="5", student=None):
    return await client.post(
        f"/api/sessions/{lesson_id}/attempts",
        json={"item_id": str(classroom.item.id), "answer": answer},
        headers=classroom.headers(student or classroom.alice),
    )


async def test_booking_needs_an_approved_plan_and_your_own_class(client, classroom, db):
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

    # Not admitted yet, so the student cannot reach it at all.
    response = await client.get(
        f"/api/sessions/{lesson['lesson_id']}", headers=classroom.headers(classroom.alice)
    )
    assert response.status_code == 404


async def test_starting_admits_the_class_as_it_is_now(client, classroom, db):
    lesson = (await book(client, classroom)).json()
    # A student joins the class after the lesson was booked.
    late = User(pseudonym="10B-09", role="student")
    db.add(late)
    await db.flush()
    db.add(Enrolment(class_id=classroom.klass.id, student_id=late.id))
    await db.commit()

    started = (await start(client, classroom, lesson["lesson_id"])).json()
    assert started["status"] == SessionStatus.OPEN.value
    assert started["students"] == 3


async def test_the_clock_runs_for_the_length_of_the_timeline(client, classroom, db):
    await with_timeline(db, classroom)
    lesson = (await book(client, classroom)).json()
    started = (await start(client, classroom, lesson["lesson_id"])).json()
    opened = datetime.fromisoformat(started["opened_at"])
    closes = datetime.fromisoformat(started["closes_at"])
    assert closes - opened == timedelta(minutes=45)
    assert (await start(client, classroom, lesson["lesson_id"])).status_code == 409


async def test_tutors_follow_the_phase_on_the_server(client, classroom, db):
    await with_timeline(db, classroom)
    lesson_id = (await book(client, classroom)).json()["lesson_id"]
    started = (await start(client, classroom, lesson_id)).json()
    assert (started["phase_name"], started["tutors_on"]) == ("Explanation", False)

    blocked = await attempt(client, classroom, lesson_id)
    assert blocked.status_code == 409
    assert "Tutors are off" in blocked.json()["detail"]

    moved = (await phase(client, classroom, lesson_id, 1)).json()
    assert (moved["phase_name"], moved["tutors_on"]) == ("Tutor time", True)
    assert (await attempt(client, classroom, lesson_id)).status_code == 200

    await phase(client, classroom, lesson_id, 2)
    assert (await attempt(client, classroom, lesson_id)).status_code == 409


async def test_changing_phase_is_checked_and_logged(client, classroom, db):
    await with_timeline(db, classroom)
    lesson_id = (await book(client, classroom)).json()["lesson_id"]
    assert (await phase(client, classroom, lesson_id, 1)).status_code == 409  # not started
    await start(client, classroom, lesson_id)
    assert (await phase(client, classroom, lesson_id, 7)).status_code == 422
    await phase(client, classroom, lesson_id, 1)

    actions = [log.action for log in (await db.scalars(select(TeacherAccessLog))).all()]
    for action in (
        TeacherAction.SCHEDULE_LESSON,
        TeacherAction.START_LESSON,
        TeacherAction.CHANGE_PHASE,
    ):
        assert action.value in actions


async def test_plans_written_before_timelines_keep_tutors_on(client, classroom):
    """The fixture's session has no timeline; its students must not be locked out."""
    assert (await attempt(client, classroom, classroom.session.id)).status_code == 200


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


async def test_the_review_summarises_the_class(client, classroom):
    lesson_id = classroom.session.id
    await attempt(client, classroom, lesson_id, "4")
    await attempt(client, classroom, lesson_id, "5")
    await client.post(
        f"/api/sessions/{lesson_id}/request-teacher", headers=classroom.headers(classroom.bob)
    )

    body = (
        await client.get(f"/api/teacher/lessons/{lesson_id}/review", headers=teacher(classroom))
    ).json()
    assert body["students"] == 2
    assert body["started"] == 1
    assert body["finished_all"] == 1
    assert body["times_needed_you"] == 1
    alice, bob = body["progress"]
    assert (alice["pseudonym"], alice["correct"], alice["attempts"]) == ("10B-01", 1, 2)
    assert bob["times_needed_you"] == 1


async def test_opening_a_students_work_shows_their_timeline_and_is_logged(client, classroom, db):
    lesson_id = classroom.session.id
    await attempt(client, classroom, lesson_id, "4")
    response = await client.get(
        f"/api/teacher/lessons/{lesson_id}/students/{classroom.alice.id}",
        headers=teacher(classroom),
    )
    assert response.status_code == 200
    kinds = [event["kind"] for event in response.json()["events"]]
    assert kinds[:2] == ["attempt", "hint"]

    logs = (await db.scalars(select(TeacherAccessLog))).all()
    assert logs[-1].action == TeacherAction.REVIEW_STUDENT.value
    assert logs[-1].student_id == classroom.alice.id


async def test_another_teacher_cannot_review_the_lesson(client, classroom):
    other = teacher(classroom, classroom.other_teacher)
    lesson_id = classroom.session.id
    assert (
        await client.get(f"/api/teacher/lessons/{lesson_id}/review", headers=other)
    ).status_code == 404
    assert (
        await client.get(
            f"/api/teacher/lessons/{lesson_id}/students/{classroom.alice.id}", headers=other
        )
    ).status_code == 404
