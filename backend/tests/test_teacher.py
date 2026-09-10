"""The teacher console.

The console's job is to stay quiet and then be right when it speaks, so these
tests cover both halves: nothing in the queue during ordinary work, correct
priority ordering when something happens, and an audit trail for every look at
a named student's work.
"""

from sqlalchemy import select

from app.enums import EvidenceKind, ExceptionStatus, SessionStatus, TeacherAction
from app.models import EvidenceRecord, TeacherAccessLog


async def submit(client, classroom, answer, student=None):
    student = student or classroom.alice
    return await client.post(
        f"/api/sessions/{classroom.session.id}/attempts",
        json={"item_id": str(classroom.item.id), "answer": answer},
        headers=classroom.headers(student),
    )


async def console(client, classroom, teacher=None):
    return await client.get(
        f"/api/teacher/sessions/{classroom.session.id}/console",
        headers=classroom.headers(teacher or classroom.teacher),
    )


async def test_the_console_starts_empty_and_quiet(client, classroom):
    body = (await console(client, classroom)).json()
    assert body["queue"] == []
    assert body["title"] == classroom.contract.title
    assert {p["pseudonym"] for p in body["progress"]} == {"10B-01", "10B-02"}


async def test_ordinary_work_does_not_fill_the_queue(client, classroom):
    await submit(client, classroom, "5")
    await submit(client, classroom, "4")
    body = (await console(client, classroom)).json()
    assert body["queue"] == []
    assert body["progress"][0]["attempts"] == 2
    assert body["progress"][0]["correct"] == 1


async def test_the_queue_orders_a_students_own_request_above_an_inferred_signal(
    client, classroom
):
    for answer in ("4", "6", "7"):
        await submit(client, classroom, answer)
    await client.post(
        f"/api/sessions/{classroom.session.id}/request-teacher",
        headers=classroom.headers(classroom.bob),
    )

    queue = (await console(client, classroom)).json()["queue"]
    assert [q["kind"] for q in queue] == ["teacher_requested", "repeated_incorrect"]
    assert queue[0]["pseudonym"] == "10B-02"


async def test_acknowledging_clears_an_item_from_the_queue(client, classroom):
    for answer in ("4", "6", "7"):
        await submit(client, classroom, answer)
    [item] = (await console(client, classroom)).json()["queue"]

    response = await client.post(
        f"/api/teacher/exceptions/{item['id']}/acknowledge",
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 200
    assert (await console(client, classroom)).json()["queue"] == []


async def test_drilling_into_a_transcript_is_logged(client, classroom, db):
    await submit(client, classroom, "4")

    response = await client.get(
        f"/api/teacher/sessions/{classroom.session.id}"
        f"/students/{classroom.alice.id}/transcript",
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 200
    assert [line["kind"] for line in response.json()] == [
        EvidenceKind.ATTEMPT.value,
        EvidenceKind.HINT.value,
    ]

    logs = (await db.scalars(select(TeacherAccessLog))).all()
    assert [log.action for log in logs] == [TeacherAction.TRANSCRIPT_DRILLDOWN.value]
    assert logs[0].student_id == classroom.alice.id


async def test_a_teacher_cannot_read_another_teachers_classroom(client, classroom):
    response = await console(client, classroom, teacher=classroom.other_teacher)
    assert response.status_code == 404


async def test_a_student_cannot_open_the_console(client, classroom):
    response = await client.get(
        f"/api/teacher/sessions/{classroom.session.id}/console",
        headers=classroom.headers(classroom.alice),
    )
    assert response.status_code == 403


async def test_pausing_stops_the_class_and_is_logged(client, classroom, db):
    response = await client.post(
        f"/api/teacher/sessions/{classroom.session.id}/state",
        params={"to": SessionStatus.PAUSED.value},
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 200
    assert response.json()["status"] == SessionStatus.PAUSED.value

    # The student is told their own session is paused, not given a bare error.
    blocked = await submit(client, classroom, "5")
    assert blocked.status_code == 409
    assert "paused" in blocked.json()["detail"]

    actions = [log.action for log in (await db.scalars(select(TeacherAccessLog))).all()]
    assert TeacherAction.PAUSE_SESSION.value in actions


async def test_messaging_a_student_lands_in_their_evidence_and_the_access_log(
    client, classroom, db
):
    response = await client.post(
        f"/api/teacher/sessions/{classroom.session.id}"
        f"/students/{classroom.alice.id}/message",
        json={"text": "Come and see me when you finish this one."},
        headers=classroom.headers(classroom.teacher),
    )
    assert response.status_code == 202

    records = (
        await db.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.kind == EvidenceKind.TEACHER_FEEDBACK.value
            )
        )
    ).all()
    assert records[0].provenance["source"] == "teacher"

    actions = [log.action for log in (await db.scalars(select(TeacherAccessLog))).all()]
    assert TeacherAction.MESSAGE_STUDENT.value in actions


async def test_an_acknowledged_concern_can_come_back(client, classroom, db):
    """One live exception per student and item keeps the console quiet, but a
    resolved concern must be able to reappear if the student is still stuck."""
    for answer in ("4", "6", "7"):
        await submit(client, classroom, answer)
    [item] = (await console(client, classroom)).json()["queue"]
    await client.post(
        f"/api/teacher/exceptions/{item['id']}/acknowledge",
        headers=classroom.headers(classroom.teacher),
    )

    await submit(client, classroom, "8")
    kinds = [q["kind"] for q in (await console(client, classroom)).json()["queue"]]
    assert "repeated_incorrect" in kinds


async def test_exception_status_is_recorded_against_the_teacher(client, classroom, db):
    for answer in ("4", "6", "7"):
        await submit(client, classroom, answer)
    [item] = (await console(client, classroom)).json()["queue"]
    await client.post(
        f"/api/teacher/exceptions/{item['id']}/acknowledge",
        headers=classroom.headers(classroom.teacher),
    )

    from app.models import Exception_

    exc = await db.get(Exception_, item["id"])
    await db.refresh(exc)
    assert exc.status == ExceptionStatus.ACKNOWLEDGED.value
    assert exc.acknowledged_by == classroom.teacher.id
