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
