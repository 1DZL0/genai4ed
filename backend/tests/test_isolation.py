"""Cross-student isolation.

The concept note makes strict cross-student isolation a minimum requirement, so
it is asserted rather than assumed. Probing another student's session must be
indistinguishable from probing one that does not exist.
"""

import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import (
    check_role,
    get_current_user,
    open_student_session,
    student_session,
    teacher_session,
)
from app.enums import Role, SessionStatus


def make_request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


async def test_missing_identity_header_is_rejected(db):
    with pytest.raises(HTTPException) as exc:
        await get_current_user(make_request({}), db)
    assert exc.value.status_code == 401


async def test_unknown_pseudonym_is_rejected(db, classroom):
    request = make_request({"X-GenAI4ED-Pseudonym": "10B-99"})
    with pytest.raises(HTTPException) as exc:
        await get_current_user(request, db)
    assert exc.value.status_code == 401


async def test_known_pseudonym_resolves(db, classroom):
    request = make_request({"X-GenAI4ED-Pseudonym": "10B-01"})
    user = await get_current_user(request, db)
    assert user.id == classroom.alice.id


async def test_roles_do_not_cross(classroom):
    with pytest.raises(HTTPException) as as_student:
        check_role(classroom.teacher, Role.STUDENT)
    assert as_student.value.status_code == 403

    with pytest.raises(HTTPException) as as_teacher:
        check_role(classroom.alice, Role.TEACHER)
    assert as_teacher.value.status_code == 403


async def test_participant_reaches_own_session(db, classroom):
    session = await student_session(classroom.session.id, classroom.alice, db)
    assert session.id == classroom.session.id


async def test_non_participant_cannot_reach_another_students_session(db, classroom):
    """The headline isolation case: 10C-01 is a real student, but not in this
    session. The answer must be 404, not 403 - a 403 would confirm it exists."""
    with pytest.raises(HTTPException) as exc:
        await student_session(classroom.session.id, classroom.outsider, db)
    assert exc.value.status_code == 404


async def test_unknown_session_is_indistinguishable_from_a_forbidden_one(db, classroom):
    with pytest.raises(HTTPException) as unknown:
        await student_session(uuid.uuid4(), classroom.alice, db)
    with pytest.raises(HTTPException) as forbidden:
        await student_session(classroom.session.id, classroom.outsider, db)
    assert unknown.value.status_code == forbidden.value.status_code == 404
    assert unknown.value.detail == forbidden.value.detail


async def test_paused_session_reports_itself_to_its_own_student(db, classroom):
    """A student may know their own session is paused - that is the teacher's
    intervention working, not an information leak."""
    classroom.session.status = SessionStatus.PAUSED.value
    db.add(classroom.session)
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await open_student_session(classroom.session.id, classroom.alice, db)
    assert exc.value.status_code == 409
    assert "paused" in exc.value.detail


async def test_teacher_reaches_own_class_session(db, classroom):
    session = await teacher_session(classroom.session.id, classroom.teacher, db)
    assert session.id == classroom.session.id


async def test_teacher_cannot_reach_another_teachers_session(db, classroom):
    with pytest.raises(HTTPException) as exc:
        await teacher_session(classroom.session.id, classroom.other_teacher, db)
    assert exc.value.status_code == 404
