"""A lesson ends: either its time runs out or the teacher closes it.

Closing is final. A timed lesson that could quietly be reopened would make
`closes_at` a suggestion rather than a limit, and the evidence from one lesson
would bleed into the next.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.enums import SessionStatus, TeacherAction
from app.models import Session, TeacherAccessLog


async def say(client, classroom, text="x = 5 because 19 - 4 = 15 and 15 / 3 = 5"):
    return await client.post(
        f"/api/learn/{classroom.session.id}/messages",
        json={"text": text},
        headers=classroom.headers(classroom.alice),
    )


async def set_state(client, classroom, to):
    return await client.post(
        f"/api/teacher/sessions/{classroom.session.id}/state",
        params={"to": to.value},
        headers=classroom.headers(classroom.teacher),
    )


async def run_out_of_time(db, classroom, *, long_ago: bool = False):
    """Just past its time: the pupils wait and the teacher decides. Long ago (past the grace
    period): the clock ends it."""
    ago = timedelta(hours=3) if long_ago else timedelta(minutes=1)
    classroom.session.closes_at = datetime.now(UTC) - ago
    await db.commit()


async def paused_ago(db, classroom, ago: timedelta):
    """As if the teacher had pressed Pause `ago` (after pausing through the API): the pause
    and the deadline as it stood then both move back."""
    await db.refresh(classroom.session)
    classroom.session.paused_at -= ago
    classroom.session.closes_at -= ago
    await db.commit()


def minutes_left(iso: str) -> float:
    return (
        datetime.fromisoformat(iso.replace("Z", "+00:00")) - datetime.now(UTC)
    ).total_seconds() / 60


async def test_a_lesson_accepts_work_until_its_time_is_up(client, classroom, db):
    assert (await say(client, classroom)).status_code == 200

    await run_out_of_time(db, classroom)
    response = await say(client, classroom)
    assert response.status_code == 409
    assert "time" in response.json()["detail"].lower()


async def test_running_out_of_time_is_recorded_as_closing_at_the_deadline(client, classroom, db):
    await run_out_of_time(db, classroom, long_ago=True)
    await say(client, classroom)

    session = await db.scalar(select(Session).where(Session.id == classroom.session.id))
    await db.refresh(session)
    assert session.status == SessionStatus.CLOSED.value
    assert session.closed_at == session.closes_at


async def test_a_lesson_left_paused_ends_on_its_own(client, classroom, db):
    await set_state(client, classroom, SessionStatus.PAUSED)
    await paused_ago(db, classroom, timedelta(hours=3))

    body = (
        await client.get(
            f"/api/learn/{classroom.session.id}", headers=classroom.headers(classroom.alice)
        )
    ).json()
    assert body["status"] == SessionStatus.CLOSED.value


async def test_an_expired_lesson_leaves_the_students_list(client, classroom, db):
    await run_out_of_time(db, classroom, long_ago=True)
    response = await client.get("/api/learn", headers=classroom.headers(classroom.alice))
    assert response.json() == []


async def test_the_teacher_sees_an_expired_lesson_as_finished(client, classroom, db):
    await run_out_of_time(db, classroom, long_ago=True)
    today = (
        await client.get("/api/teacher/today", headers=classroom.headers(classroom.teacher))
    ).json()
    assert today["coming_up"] == []
    assert [lesson["status"] for lesson in today["finished"]] == [SessionStatus.CLOSED.value]


async def test_the_teacher_can_end_a_lesson_early_and_it_is_logged(client, classroom, db):
    response = await set_state(client, classroom, SessionStatus.CLOSED)
    assert response.status_code == 200
    assert response.json()["status"] == SessionStatus.CLOSED.value

    assert (await say(client, classroom)).status_code == 409

    actions = [log.action for log in (await db.scalars(select(TeacherAccessLog))).all()]
    assert TeacherAction.CLOSE_SESSION.value in actions


async def test_a_closed_lesson_cannot_be_reopened_or_paused(client, classroom):
    await set_state(client, classroom, SessionStatus.CLOSED)

    for to in (SessionStatus.OPEN, SessionStatus.PAUSED):
        response = await set_state(client, classroom, to)
        assert response.status_code == 409
        assert "ended" in response.json()["detail"]


async def test_an_expired_lesson_cannot_be_resumed(client, classroom, db):
    await set_state(client, classroom, SessionStatus.PAUSED)
    await paused_ago(db, classroom, timedelta(hours=3))
    assert (await set_state(client, classroom, SessionStatus.OPEN)).status_code == 409


async def test_a_student_cannot_ask_for_the_teacher_after_the_lesson_ends(client, classroom):
    await set_state(client, classroom, SessionStatus.CLOSED)
    response = await client.post(
        f"/api/learn/{classroom.session.id}/request-teacher",
        headers=classroom.headers(classroom.alice),
    )
    assert response.status_code == 409


async def test_both_views_carry_the_deadline(client, classroom):
    student = (
        await client.get(
            f"/api/learn/{classroom.session.id}", headers=classroom.headers(classroom.alice)
        )
    ).json()
    board = (
        await client.post(
            "/api/teacher/thread/actions",
            json={"action": "show_class", "session_id": str(classroom.session.id)},
            headers=classroom.headers(classroom.teacher),
        )
    ).json()["showing"]
    assert student["closes_at"] == board["closes_at"]


async def test_a_pause_stops_the_clock_and_carrying_on_starts_it_where_it_stopped(
    client, classroom, db
):
    classroom.session.closes_at = datetime.now(UTC) + timedelta(minutes=10)
    await db.commit()
    await set_state(client, classroom, SessionStatus.PAUSED)
    # Half an hour later, by the stored deadline the time ran out twenty minutes ago.
    await paused_ago(db, classroom, timedelta(minutes=30))
    student = (
        await client.get(
            f"/api/learn/{classroom.session.id}", headers=classroom.headers(classroom.alice)
        )
    ).json()
    assert student["status"] == SessionStatus.PAUSED.value and not student["time_up"]
    assert 9.5 < minutes_left(student["closes_at"]) <= 10

    assert (await set_state(client, classroom, SessionStatus.OPEN)).status_code == 200
    await db.refresh(classroom.session)
    assert classroom.session.paused_at is None
    assert 9.5 < minutes_left(classroom.session.closes_at.isoformat()) <= 10
    assert (await say(client, classroom)).status_code == 200


async def test_minutes_added_in_a_pause_wait_with_the_clock(client, classroom, db):
    classroom.session.closes_at = datetime.now(UTC) + timedelta(minutes=2)
    await db.commit()
    await set_state(client, classroom, SessionStatus.PAUSED)
    await paused_ago(db, classroom, timedelta(minutes=30))
    added = await client.post(
        "/api/teacher/thread/actions",
        json={"action": "extend", "session_id": str(classroom.session.id), "minutes": 5},
        headers=classroom.headers(classroom.teacher),
    )
    assert added.status_code == 200
    await set_state(client, classroom, SessionStatus.OPEN)
    await db.refresh(classroom.session)
    assert 6.5 < minutes_left(classroom.session.closes_at.isoformat()) <= 7
