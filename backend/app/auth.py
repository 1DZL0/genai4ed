"""Who is signed in, and the isolation boundary: a student reaches only their own session, a
teacher only their own classes. Breaches answer 404 so probing cannot confirm a session exists."""

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

# A cookie per role, so one browser can be a teacher in one tab and a student in another.
COOKIES = {Role.TEACHER.value: "genai4ed_teacher", Role.STUDENT.value: "genai4ed_student"}
COOKIE_NAME = COOKIES[Role.TEACHER.value]


async def _user_for(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    return await db.scalar(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            AuthSession.token_digest == token_digest(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )


async def get_current_user(request: Request, db: DbSession, role: Role | None = None) -> User:
    """The user behind the cookie for `role` (either role when not given), or the
    development header when that is enabled."""
    names = [COOKIES[role.value]] if role else list(COOKIES.values())
    token = None
    for name in names:
        token = request.cookies.get(name) or token
        user = await _user_for(db, request.cookies.get(name))
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
        COOKIES[user.role],
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


async def end_sign_in(
    db: AsyncSession, request: Request, response: Response, role: Role | None = None
) -> None:
    """Sign out of `role`, or of both roles when none is given."""
    names = [COOKIES[role.value]] if role else list(COOKIES.values())
    for name in names:
        token = request.cookies.get(name)
        if token:
            await db.execute(
                update(AuthSession)
                .where(AuthSession.token_digest == token_digest(token))
                .values(revoked_at=datetime.now(UTC))
            )
        response.delete_cookie(name, path="/")
    await db.commit()


async def revoke_sign_ins(db: AsyncSession, user_ids: list[uuid.UUID]) -> None:
    """Sign these users out everywhere. The caller commits."""
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id.in_(user_ids), AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


CurrentUser = Annotated[User, Depends(get_current_user)]


async def _require(request: Request, db: AsyncSession, role: Role) -> User:
    """The user signed in as `role`. Someone signed in only as the other role gets 403."""
    try:
        user = await get_current_user(request, db, role)
    except HTTPException as exc:
        other = await get_current_user(request, db) if exc.status_code == 401 else None
        if other is None or other.role == role.value:
            raise
        user = other
    return check_role(user, role)


def check_role(user: User, role: Role) -> User:
    if user.role != role.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"{role.value.title()}s only."
        )
    return user


async def require_student(request: Request, db: DbSession) -> User:
    return await _require(request, db, Role.STUDENT)


async def require_teacher(request: Request, db: DbSession) -> User:
    return await _require(request, db, Role.TEACHER)


CurrentStudent = Annotated[User, Depends(require_student)]
CurrentTeacher = Annotated[User, Depends(require_teacher)]

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")


async def student_session(session_id: uuid.UUID, student: User, db: AsyncSession) -> Session:
    """The session this student is in, or 404; not being in it looks the same as it not existing."""
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
    """As `student_session`, and open; a paused or closed session is a 409 the student may see."""
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
    """As `student_session`, and not ended; paused still counts, the teacher can be asked for."""
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
