"""Signing in and out: teachers by email and password, students by join code."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import CurrentUser, DbSession, end_sign_in, start_sign_in
from app.config import get_settings
from app.demo_sign_in import NameTaken, demo_user
from app.enums import Role
from app.models import User
from app.security import join_code_digest, normalise_email, verify_password

router = APIRouter(prefix="/api/auth", tags=["account"])


class Me(BaseModel):
    pseudonym: str
    role: str
    email: str | None


class LoginIn(BaseModel):
    email: str
    password: str


class JoinIn(BaseModel):
    code: str


def _me(user: User) -> Me:
    return Me(pseudonym=user.pseudonym, role=user.role, email=user.email)


@router.post("/login", response_model=Me)
async def login(body: LoginIn, response: Response, db: DbSession) -> Me:
    user = await db.scalar(
        select(User).where(
            User.email == normalise_email(body.email), User.role == Role.TEACHER.value
        )
    )
    # One message whether the email or the password was wrong.
    if not verify_password(body.password, user.password_hash if user else None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That email and password do not match an account.",
        )
    await start_sign_in(db, response, user)
    return _me(user)


@router.post("/join", response_model=Me)
async def join(body: JoinIn, response: Response, db: DbSession) -> Me:
    user = await db.scalar(
        select(User).where(
            User.join_code_digest == join_code_digest(body.code),
            User.role == Role.STUDENT.value,
        )
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That code was not recognised. Check it with your teacher.",
        )
    await start_sign_in(db, response, user)
    return _me(user)


class SignInConfig(BaseModel):
    demo_sign_in: bool


class DemoIn(BaseModel):
    role: Role
    username: str = Field(min_length=1, max_length=64)
    password: str
    # For a student: the teacher whose class they join. Any class when not given.
    teacher: str | None = Field(default=None, max_length=64)


@router.get("/config", response_model=SignInConfig)
async def config() -> SignInConfig:
    """Which sign-in the pages should offer."""
    return SignInConfig(demo_sign_in=get_settings().demo_sign_in)


@router.post("/demo", response_model=Me)
async def demo(body: DemoIn, response: Response, db: DbSession) -> Me:
    """Any username and password, creating the account on first use."""
    if not get_settings().demo_sign_in:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=422, detail="Type a username.")
    try:
        user = await demo_user(db, username, body.role, body.teacher)
    except NameTaken as taken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{username}' is already a {taken} name. Pick another.",
        ) from taken
    await start_sign_in(db, response, user)
    return _me(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, db: DbSession, role: Role | None = None
) -> Response:
    """Sign out of one role, or of both when no role is given."""
    await end_sign_in(db, request, response, role)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=Me)
async def me(user: CurrentUser) -> Me:
    return _me(user)
