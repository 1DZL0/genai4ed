"""Classes: any size, pseudonymous from the start, students added and removed."""

import re

from app.models import User


def headers(classroom, who=None):
    return classroom.headers(who or classroom.teacher)


async def roster(client, classroom, class_id):
    return (
        await client.get(f"/api/teacher/classes/{class_id}/students", headers=headers(classroom))
    ).json()


# Five characters from an alphabet with no 0/O or 1/I: random, so a name says nothing about
# the class, the teacher or the order pupils were added in.
NAME = re.compile(r"^[A-HJ-NP-Z2-9]{5}$")


async def test_a_new_class_gets_random_pseudonyms(client, classroom):
    response = await client.post(
        "/api/teacher/classes",
        json={"label": "9B English", "students": 3},
        headers=headers(classroom),
    )
    assert response.status_code == 201
    klass = response.json()
    assert klass["students"] == 3
    names = [r["pseudonym"] for r in await roster(client, classroom, klass["id"])]
    assert len(names) == 3 and len(set(names)) == 3
    assert all(NAME.match(n) for n in names), names
    assert not any(n.startswith("9B") for n in names)


async def test_classes_can_be_different_sizes(client, classroom):
    await client.post(
        "/api/teacher/classes", json={"label": "7C", "students": 27}, headers=headers(classroom)
    )
    sizes = {
        c["label"]: c["students"]
        for c in (await client.get("/api/teacher/classes", headers=headers(classroom))).json()
    }
    assert sizes == {"10B": 2, "7C": 27}


async def test_pseudonyms_already_taken_are_never_reissued(client, classroom, monkeypatch):
    """A random name that is already someone's is drawn again."""
    from app.routers import teacher as teacher_router

    draws = iter(["AAAAA", "AAAAA", "BBBBB", "CCCCC"])
    monkeypatch.setattr(teacher_router, "_random_name", lambda: next(draws))
    klass = (
        await client.post(
            "/api/teacher/classes", json={"label": "10B", "students": 3}, headers=headers(classroom)
        )
    ).json()
    names = [r["pseudonym"] for r in await roster(client, classroom, klass["id"])]
    assert sorted(names) == ["AAAAA", "BBBBB", "CCCCC"]


async def test_adding_a_student_takes_the_next_number(client, classroom):
    response = await client.post(
        f"/api/teacher/classes/{classroom.klass.id}/students", headers=headers(classroom)
    )
    assert response.status_code == 201
    assert NAME.match(response.json()["pseudonym"])
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
