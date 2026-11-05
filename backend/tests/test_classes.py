"""Classes: any size, pseudonymous from the start, students added and removed."""

from app.models import User


def headers(classroom, who=None):
    return classroom.headers(who or classroom.teacher)


async def roster(client, classroom, class_id):
    return (
        await client.get(f"/api/teacher/classes/{class_id}/students", headers=headers(classroom))
    ).json()


async def test_a_new_class_gets_numbered_pseudonyms(client, classroom):
    response = await client.post(
        "/api/teacher/classes",
        json={"label": "9B English", "students": 3},
        headers=headers(classroom),
    )
    assert response.status_code == 201
    klass = response.json()
    assert klass["students"] == 3
    assert [r["pseudonym"] for r in await roster(client, classroom, klass["id"])] == [
        "9B-01",
        "9B-02",
        "9B-03",
    ]


async def test_classes_can_be_different_sizes(client, classroom):
    await client.post(
        "/api/teacher/classes", json={"label": "7C", "students": 27}, headers=headers(classroom)
    )
    sizes = {
        c["label"]: c["students"]
        for c in (await client.get("/api/teacher/classes", headers=headers(classroom))).json()
    }
    assert sizes == {"10B": 2, "7C": 27}


async def test_pseudonyms_already_taken_are_skipped(client, classroom):
    """The fixture already has 10B-01 and 10B-02, so a second 10B starts at 03."""
    klass = (
        await client.post(
            "/api/teacher/classes", json={"label": "10B", "students": 2}, headers=headers(classroom)
        )
    ).json()
    assert [r["pseudonym"] for r in await roster(client, classroom, klass["id"])] == [
        "10B-03",
        "10B-04",
    ]


async def test_adding_a_student_takes_the_next_number(client, classroom):
    response = await client.post(
        f"/api/teacher/classes/{classroom.klass.id}/students", headers=headers(classroom)
    )
    assert response.status_code == 201
    assert response.json()["pseudonym"] == "10B-03"
    assert len(await roster(client, classroom, classroom.klass.id)) == 3


async def test_removing_a_student_keeps_their_account_and_work(client, classroom, db):
    response = await client.delete(
        f"/api/teacher/classes/{classroom.klass.id}/students/{classroom.bob.id}",
        headers=headers(classroom),
    )
    assert response.status_code == 204
    assert [r["pseudonym"] for r in await roster(client, classroom, classroom.klass.id)] == [
        "10B-01"
    ]
    assert await db.get(User, classroom.bob.id) is not None


async def test_another_teacher_cannot_change_your_class(client, classroom):
    other = headers(classroom, classroom.other_teacher)
    assert (
        await client.post(f"/api/teacher/classes/{classroom.klass.id}/students", headers=other)
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/teacher/classes/{classroom.klass.id}/students/{classroom.alice.id}",
            headers=other,
        )
    ).status_code == 404


async def test_a_class_size_is_limited(client, classroom):
    response = await client.post(
        "/api/teacher/classes", json={"label": "Hall", "students": 400}, headers=headers(classroom)
    )
    assert response.status_code == 422


async def test_consent_is_recorded_per_student_and_shown_on_the_roster(client, db, classroom):
    """Research consent lives on the enrolment, set by the teacher, and is on the roster."""
    from sqlalchemy import select

    from app.models import TeacherAccessLog

    cid, sid = classroom.klass.id, classroom.alice.id
    assert {r["consent"] for r in await roster(client, classroom, cid)} == {"unknown"}
    url = f"/api/teacher/classes/{cid}/students/{sid}/consent"
    given = await client.post(url, json={"status": "given"}, headers=headers(classroom))
    assert given.status_code == 200, given.text
    assert given.json()["consent"] == "given"
    after = {r["pseudonym"]: r["consent"] for r in await roster(client, classroom, cid)}
    assert after[classroom.alice.pseudonym] == "given"
    assert after[classroom.bob.pseudonym] == "unknown"
    maybe = await client.post(url, json={"status": "maybe"}, headers=headers(classroom))
    assert maybe.status_code == 422
    other = headers(classroom, classroom.other_teacher)
    assert (await client.post(url, json={"status": "given"}, headers=other)).status_code == 404
    logged = (
        await db.scalars(
            select(TeacherAccessLog).where(
                TeacherAccessLog.action == "record_consent", TeacherAccessLog.student_id == sid
            )
        )
    ).all()
    assert len(logged) == 1 and logged[0].detail["status"] == "given"


async def test_erasing_a_student_removes_everything_about_them(client, db, classroom):
    """Withdrawal with erasure: the pupil, their words, their turns and their marks go; the
    access log keeps one line saying a pupil was erased, by pseudonym only."""
    from sqlalchemy import select

    from app.models import (
        AgentTurn,
        Conversation,
        Enrolment,
        EvidenceRecord,
        LearningState,
        SessionParticipant,
        TeacherAccessLog,
    )

    cid, sid, name = classroom.klass.id, classroom.alice.id, classroom.alice.pseudonym
    bob = classroom.bob.pseudonym
    wrote = await client.post(
        f"/api/learn/{classroom.session.id}/messages",
        json={"text": "x = 9"},
        headers=classroom.headers(classroom.alice),
    )
    assert wrote.status_code == 200
    assert (await db.scalars(select(AgentTurn).where(AgentTurn.student_id == sid))).all()

    other = headers(classroom, classroom.other_teacher)
    url = f"/api/teacher/classes/{cid}/students/{sid}/records"
    assert (await client.delete(url, headers=other)).status_code == 404
    gone = await client.delete(url, headers=headers(classroom))
    assert gone.status_code == 204, gone.text

    assert await db.get(User, sid) is None
    tables = (AgentTurn, Conversation, Enrolment, EvidenceRecord, LearningState, SessionParticipant)
    for model in tables:
        rows = (await db.scalars(select(model).where(model.student_id == sid))).all()
        assert rows == [], model.__name__
    left = [r["pseudonym"] for r in await roster(client, classroom, cid)]
    assert left == [bob]
    logged = (
        await db.scalars(select(TeacherAccessLog).where(TeacherAccessLog.action == "erase_student"))
    ).all()
    assert len(logged) == 1
    assert logged[0].student_id is None and logged[0].detail == {"pseudonym": name}
