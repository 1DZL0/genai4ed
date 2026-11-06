"""A whole class at once, through the app's real database pool.

Every other test shares one database session, so none of them meets the connection pool. Here
thirty pupils open the lesson in the same moment, the model takes a couple of seconds over each
reply, as a hosted model does, and one pupil's page refreshes in the middle. Every opening must
arrive, and the refresh must not wait behind the model calls."""

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app import db as app_db
from app.agent import llm
from app.agent.scripted import demo_responder
from app.demo import MATHS
from app.enums import ContractStatus, Role, SessionStatus
from app.main import create_app
from app.models import Class, Enrolment, LessonContract, Session, SessionParticipant, User

PUPILS = 30
MODEL_SECONDS = 2.0


class SlowModel(llm.ScriptedClient):
    """The demo tutor, as slow as a hosted model."""

    async def complete(self, **kwargs) -> llm.LLMResult:
        await asyncio.sleep(MODEL_SECONDS)
        return await super().complete(**kwargs)


@pytest.fixture
async def full_class(db):
    teacher = User(pseudonym="teacher-load", role=Role.TEACHER.value)
    pupils = [User(pseudonym=f"9L-{i:02d}", role=Role.STUDENT.value) for i in range(PUPILS)]
    db.add_all([teacher, *pupils])
    await db.flush()
    klass = Class(teacher_id=teacher.id, label="9L")
    db.add(klass)
    await db.flush()
    db.add_all([Enrolment(class_id=klass.id, student_id=p.id) for p in pupils])
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
    db.add_all([SessionParticipant(session_id=session.id, student_id=p.id) for p in pupils])
    await db.commit()
    return session, pupils


@pytest.fixture
async def real_pool_client():
    """The app as it runs live: its own engine and pool, no shared test session."""
    application = create_app()
    application.dependency_overrides[llm.get_llm_client] = lambda: SlowModel(demo_responder)
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as c:
        yield c
    await app_db.get_engine().dispose()


async def test_a_class_of_thirty_opens_the_lesson_together(full_class, real_pool_client):
    session, pupils = full_class
    client = real_pool_client

    async def timed(coro):
        started = time.perf_counter()
        response = await coro
        return response, time.perf_counter() - started

    def as_pupil(p: User) -> dict:
        return {"X-GenAI4ED-Pseudonym": p.pseudonym}

    async def refresh_midway():
        # Halfway into the first model calls, one pupil's page polls, as it does every 8 s.
        await asyncio.sleep(MODEL_SECONDS / 2)
        return await timed(client.get(f"/api/learn/{session.id}", headers=as_pupil(pupils[-1])))

    openings = [
        timed(client.post(f"/api/learn/{session.id}/start", headers=as_pupil(p))) for p in pupils
    ]
    *opened, (refresh, refresh_seconds) = await asyncio.gather(*openings, refresh_midway())

    failed = [r.status_code for r, _ in opened if r.status_code != 200]
    assert not failed, f"{len(failed)} of {PUPILS} openings failed: {failed[:5]}"
    slowest = max(seconds for _, seconds in opened)
    # Thirty model calls run side by side, so the class waits about one model call, not thirty.
    assert slowest < MODEL_SECONDS * 3, f"the slowest opening took {slowest:.1f} s"
    assert refresh.status_code == 200
    # A page refresh reads the record; it must not queue behind other pupils' model calls.
    assert refresh_seconds < 1.0, f"a page refresh waited {refresh_seconds:.1f} s"
