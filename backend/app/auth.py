"""Identity and the cross-student isolation boundary.

Identity is pseudonymous by construction: the caller presents a pseudonym and
nothing in this system can map it to a person.

    THIS IS NOT AUTHENTICATION. The development header below trusts whatever it
    is given. It exists so that school-managed identity can be dropped into one
    seam -- `get_current_user` -- without touching any route. It must be
    replaced before the platform is exposed to anyone (concept note S4).

Everything else here is the isolation boundary, and that *is* real: a student
reaches only their own session and their own evidence, and a teacher reaches
only classes they teach. Breaches answer 404 rather than 403 so that probing
cannot confirm another student's session exists.
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.enums import Role, SessionStatus
from app.models import Class, Session, SessionParticipant, User

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(request: Request, db: DbSession) -> User:
    header = get_settings().dev_identity_header
    pseudonym = request.headers.get(header)
    if not pseudonym:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing {header}.",
        )
    user = await db.scalar(select(User).where(User.pseudonym == pseudonym))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown pseudonym.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_student(user: CurrentUser) -> User:
    if user.role != Role.STUDENT.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Students only.")
    return user


async def require_teacher(user: CurrentUser) -> User:
    if user.role != Role.TEACHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teachers only.")
    return user


CurrentStudent = Annotated[User, Depends(require_student)]
CurrentTeacher = Annotated[User, Depends(require_teacher)]

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")


async def student_session(session_id: uuid.UUID, student: User, db: AsyncSession) -> Session:
    """The session this student may work in, or 404.

    Non-participation and non-existence are deliberately indistinguishable.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise _NOT_FOUND
    participant = await db.scalar(
        select(SessionParticipant).where(
            SessionParticipant.session_id == session_id,
            SessionParticipant.student_id == student.id,
        )
    )
    if participant is None:
        raise _NOT_FOUND
    return session


async def open_student_session(session_id: uuid.UUID, student: User, db: AsyncSession) -> Session:
    """As `student_session`, and currently accepting work.

    A paused or closed session is a 409: the student is entitled to know their
    own session has been paused by the teacher.
    """
    session = await student_session(session_id, student, db)
    if session.status != SessionStatus.OPEN.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is {session.status}.",
        )
    return session


async def teacher_session(session_id: uuid.UUID, teacher: User, db: AsyncSession) -> Session:
    """The session this teacher governs, or 404."""
    session = await db.get(Session, session_id)
    if session is None:
        raise _NOT_FOUND
    klass = await db.get(Class, session.class_id)
    if klass is None or klass.teacher_id != teacher.id:
        raise _NOT_FOUND
    return session
