"""Test harness.

Runs against a real Postgres database (`genai4ed_test`), because the schema
leans on JSONB and check constraints that SQLite would not reproduce. Tables
are created from the ORM metadata for speed; a separate test asserts the
migrations have not drifted from the models.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

TEST_DATABASE_URL = os.environ.setdefault(
    "GENAI4ED_TEST_DATABASE_URL",
    "postgresql+asyncpg://genai4ed:genai4ed@127.0.0.1:5433/genai4ed_test",
)
# Must be set before app.config caches its settings.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# Most tests act as a pseudonym through the development header; the sign-in
# tests exercise the real cookie path alongside it.
os.environ["DEV_IDENTITY_ENABLED"] = "true"
# Never reach a real model from the test suite, whatever .env says.
os.environ["AGENT_CLIENT"] = "scripted"
os.environ["OPENROUTER_API_KEY"] = ""
# The suite tests the checks, whatever the demo .env says about enforcing them.
os.environ["SUPERVISOR_ENFORCE"] = "true"
os.environ["STUDY_ACTIVE"] = "false"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db import Base, get_session  # noqa: E402
from app.enums import ContractStatus, Role, SessionStatus  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    Class,
    Enrolment,
    LessonContract,
    Session,
    SessionParticipant,
    User,
)
from app.samples import MATHS  # noqa: E402


@pytest.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL)
    async with eng.begin() as conn:
        # Every table, not only today's models: a table removed from the code
        # would otherwise linger and block the drop.
        existing = (
            await conn.execute(text("select tablename from pg_tables where schemaname = 'public'"))
        ).scalars()
        for table in existing:
            await conn.execute(text(f'drop table if exists "{table}" cascade'))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    async with maker() as cleanup:
        tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
        await cleanup.execute(text(f"truncate {tables} cascade"))
        await cleanup.commit()


@pytest.fixture
def app(db):
    application = create_app()
    application.dependency_overrides[get_session] = lambda: db
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class Fixture:
    """A seeded classroom, so tests can name what they need."""

    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)

    def headers(self, user: User) -> dict[str, str]:
        return {"X-GenAI4ED-Pseudonym": user.pseudonym}


@pytest.fixture
async def classroom(db) -> Fixture:
    teacher = User(pseudonym="teacher-01", role=Role.TEACHER.value)
    other_teacher = User(pseudonym="teacher-02", role=Role.TEACHER.value)
    alice = User(pseudonym="10B-01", role=Role.STUDENT.value)
    bob = User(pseudonym="10B-02", role=Role.STUDENT.value)
    outsider = User(pseudonym="10C-01", role=Role.STUDENT.value)
    db.add_all([teacher, other_teacher, alice, bob, outsider])
    await db.flush()

    klass = Class(teacher_id=teacher.id, label="10B")
    db.add(klass)
    await db.flush()
    db.add_all([Enrolment(class_id=klass.id, student_id=s.id) for s in (alice, bob)])

    contract = LessonContract(
        teacher_id=teacher.id,
        title=MATHS.title,
        subject=MATHS.subject,
        status=ContractStatus.ACTIVE.value,
        version=1,
        brief=MATHS.model_dump(mode="json"),
        activated_at=datetime.now(UTC),
        activated_by=teacher.id,
    )
    db.add(contract)
    await db.flush()

    now = datetime.now(UTC)
    session = Session(
        contract_id=contract.id,
        class_id=klass.id,
        status=SessionStatus.OPEN.value,
        opened_at=now,
        closes_at=now + timedelta(minutes=50),
    )
    db.add(session)
    await db.flush()
    db.add_all([SessionParticipant(session_id=session.id, student_id=s.id) for s in (alice, bob)])
    await db.commit()

    return Fixture(
        teacher=teacher,
        other_teacher=other_teacher,
        alice=alice,
        bob=bob,
        outsider=outsider,
        klass=klass,
        contract=contract,
        session=session,
    )
