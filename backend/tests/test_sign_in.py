"""Signing in: teachers by email and password, students by join code.

These tests use the real cookie and never the development header, except where
a teacher issues codes (the header is simply how that teacher is set up).
"""

from sqlalchemy import select

from app.auth import COOKIE_NAME, COOKIES
from app.config import get_settings
from app.enums import TeacherAction
from app.models import AuthSession, TeacherAccessLog, User
from app.security import hash_password

PASSWORD = "correct horse battery"


async def give_password(db, classroom):
    classroom.teacher.email = "teacher-01@school.test"
    classroom.teacher.password_hash = hash_password(PASSWORD)
    await db.commit()


async def sign_in(client, email="teacher-01@school.test", password=PASSWORD):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


async def test_a_teacher_signs_in_and_reaches_their_dashboard(client, classroom, db):
    await give_password(db, classroom)

    response = await sign_in(client)
    assert response.status_code == 200
    assert response.json() == {
        "pseudonym": "teacher-01",
        "role": "teacher",
        "email": "teacher-01@school.test",
    }
    assert COOKIE_NAME in response.cookies

    assert (await client.get("/api/auth/me")).json()["pseudonym"] == "teacher-01"
    assert (await client.get("/api/teacher/today")).status_code == 200


async def test_email_is_not_case_sensitive(client, classroom, db):
    await give_password(db, classroom)
    assert (await sign_in(client, email="  Teacher-01@School.TEST ")).status_code == 200


async def test_a_wrong_password_and_an_unknown_email_look_the_same(client, classroom, db):
    await give_password(db, classroom)
    wrong_password = await sign_in(client, password="not the password")
    unknown_email = await sign_in(client, email="nobody@school.test")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert COOKIE_NAME not in wrong_password.cookies


async def test_a_teacher_without_a_password_cannot_sign_in(client, classroom, db):
    classroom.teacher.email = "teacher-01@school.test"
    await db.commit()
    assert (await sign_in(client, password="")).status_code == 401


async def test_nothing_is_reachable_without_signing_in(client, classroom, monkeypatch):
    monkeypatch.setattr(get_settings(), "dev_identity_enabled", False)
    for path in ("/api/auth/me", "/api/teacher/today", "/api/learn"):
        response = await client.get(path)
        assert response.status_code == 401, path


async def test_the_development_header_is_ignored_when_switched_off(client, classroom, monkeypatch):
    monkeypatch.setattr(get_settings(), "dev_identity_enabled", False)
    response = await client.get("/api/teacher/today", headers=classroom.headers(classroom.teacher))
    assert response.status_code == 401


async def test_signing_out_ends_the_session_on_the_server(client, classroom, db):
    await give_password(db, classroom)
    token = (await sign_in(client)).cookies[COOKIE_NAME]

    assert (await client.post("/api/auth/logout")).status_code == 204

    # Even a copy of the old cookie no longer works.
    client.cookies.set(COOKIE_NAME, token)
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    assert "expired" in response.json()["detail"]


async def test_only_a_digest_of_the_token_is_stored(client, classroom, db):
    await give_password(db, classroom)
    token = (await sign_in(client)).cookies[COOKIE_NAME]
    [row] = (await db.scalars(select(AuthSession))).all()
    assert token not in row.token_digest


async def issue_codes(client, classroom, student=None):
    params = {"student_id": str(student.id)} if student else {}
    return await client.post(
        f"/api/teacher/classes/{classroom.klass.id}/join-codes",
        params=params,
        headers=classroom.headers(classroom.teacher),
    )


async def test_a_student_joins_with_the_code_their_teacher_issued(client, classroom):
    codes = {c["pseudonym"]: c["code"] for c in (await issue_codes(client, classroom)).json()}
    assert set(codes) == {"10B-01", "10B-02"}

    response = await client.post("/api/auth/join", json={"code": codes["10B-01"]})
    assert response.status_code == 200
    assert response.json() == {"pseudonym": "10B-01", "role": "student", "email": None}

    [session] = (await client.get("/api/learn")).json()
    assert session["session_id"] == str(classroom.session.id)


async def test_a_join_code_forgives_case_and_spacing(client, classroom):
    [first, *_] = (await issue_codes(client, classroom)).json()
    sloppy = first["code"].lower().replace("-", " ")
    assert (await client.post("/api/auth/join", json={"code": sloppy})).status_code == 200


async def test_a_made_up_code_is_refused(client, classroom):
    await issue_codes(client, classroom)
    response = await client.post("/api/auth/join", json={"code": "AAAA-BBBB"})
    assert response.status_code == 401


async def test_a_student_cannot_open_the_teacher_side(client, classroom):
    [first, *_] = (await issue_codes(client, classroom)).json()
    await client.post("/api/auth/join", json={"code": first["code"]})
    assert (await client.get("/api/teacher/today")).status_code == 403


async def test_a_new_code_replaces_the_old_one_and_signs_the_student_out(client, classroom):
    [old] = (await issue_codes(client, classroom, student=classroom.alice)).json()
    await client.post("/api/auth/join", json={"code": old["code"]})
    assert (await client.get("/api/auth/me")).status_code == 200

    # The teacher acts from their own browser, not the student's.
    student_cookie = client.cookies[COOKIES["student"]]
    client.cookies.clear()
    await issue_codes(client, classroom, student=classroom.alice)
    client.cookies.set(COOKIES["student"], student_cookie)

    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.post("/api/auth/join", json={"code": old["code"]})).status_code == 401


async def test_codes_are_stored_as_digests_and_issuing_is_logged(client, classroom, db):
    issued = (await issue_codes(client, classroom)).json()

    for entry in issued:
        student = await db.get(User, entry["student_id"])
        await db.refresh(student)
        assert student.join_code_digest
        assert entry["code"].replace("-", "") not in student.join_code_digest

    [log] = (await db.scalars(select(TeacherAccessLog))).all()
    assert log.action == TeacherAction.ISSUE_JOIN_CODES.value
    assert all(entry["code"] not in str(log.detail) for entry in issued)


async def test_a_teacher_cannot_issue_codes_for_another_teachers_class(client, classroom):
    response = await client.post(
        f"/api/teacher/classes/{classroom.klass.id}/join-codes",
        headers=classroom.headers(classroom.other_teacher),
    )
    assert response.status_code == 404


async def test_the_roster_shows_who_has_a_code_without_showing_it(client, classroom):
    await issue_codes(client, classroom, student=classroom.alice)
    roster = (
        await client.get(
            f"/api/teacher/classes/{classroom.klass.id}/students",
            headers=classroom.headers(classroom.teacher),
        )
    ).json()
    assert [(r["pseudonym"], r["has_join_code"]) for r in roster] == [
        ("10B-01", True),
        ("10B-02", False),
    ]
    assert all("code" not in r for r in roster)
