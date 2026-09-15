"""Identity and the cross-student isolation boundary.

Identity is pseudonymous by construction: a signed-in user is a pseudonym and a
role, and nothing in this system can map a student's pseudonym to a person.

Sign-in is a server-side session carried in an HttpOnly cookie. Teachers get
one from email and password, students from a join code (`routers/account.py`).
`get_current_user` is the single seam: school-managed identity replaces it
without touching any route.

The development header is still here for the test suite and the scripted demo,
and is off unless `DEV_IDENTITY_ENABLED` is set.

Everything else is the isolation boundary: a student reaches only their own
session and their own evidence, and a teacher reaches only classes they teach.
Breaches answer 404 rather than 403 so that probing cannot confirm another
student's session exists.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.enums import Role, SessionStatus
from app.lifecycle import close_expired
from app.models import AuthSession, Class, Session, SessionParticipant, User
from app.security import new_token, token_digest

DbSession = Annotated[AsyncSession, Depends(get_session)]

COOKIE_NAME = "genai4ed_session"


async def get_current_user(request: Request, db: DbSession) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        user = await db.scalar(
            select(User)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                AuthSession.token_digest == token_digest(token),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
            )
        )
        if user is not None:
            return user

    settings = get_settings()
    pseudonym = request.headers.get(settings.dev_identity_header)
    if settings.dev_identity_enabled and pseudonym:
        user = await db.scalar(select(User).where(User.pseudonym == pseudonym))
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown pseudonym."
            )
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Your sign-in has expired." if token else "Not signed in.",
    )


async def start_sign_in(db: AsyncSession, response: Response, user: User) -> None:
    """Open a server-side session for `user` and hand the browser its cookie."""
    settings = get_settings()
    token = new_token()
    lifetime = timedelta(hours=settings.sign_in_hours)
    db.add(
        AuthSession(
            token_digest=token_digest(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + lifetime,
        )
    )
    await db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


async def end_sign_in(db: AsyncSession, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await db.execute(
            update(AuthSession)
            .where(AuthSession.token_digest == token_digest(token))
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


async def revoke_sign_ins(db: AsyncSession, user_ids: list[uuid.UUID]) -> None:
    """Sign these users out everywhere. The caller commits."""
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id.in_(user_ids), AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


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
    await close_expired(db, session_id)
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


async def unclosed_student_session(
    session_id: uuid.UUID, student: User, db: AsyncSession
) -> Session:
    """As `student_session`, and not yet ended. A paused session still counts:
    the teacher is in the room and can be asked for."""
    session = await student_session(session_id, student, db)
    if session.status == SessionStatus.CLOSED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is closed.")
    return session


async def teacher_session(session_id: uuid.UUID, teacher: User, db: AsyncSession) -> Session:
    """The session this teacher governs, or 404."""
    await close_expired(db, session_id)
    session = await db.get(Session, session_id)
    if session is None:
        raise _NOT_FOUND
    klass = await db.get(Class, session.class_id)
    if klass is None or klass.teacher_id != teacher.id:
        raise _NOT_FOUND
    return session
