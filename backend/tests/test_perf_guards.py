"""Query budgets for the reads the teacher's page makes on every open. A read whose query count
grows with the number of lessons or runs is one query per row waiting to happen; it shows up
here, on a small seed, before it shows up as a slow page after a term."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import event

from app.demo import MATHS
from app.enums import ContractStatus, SessionStatus
from app.models import LessonContract, Session, SessionParticipant


class _Queries:
    """Counts the statements the engine runs inside the block."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.n = 0

    def __enter__(self):
        event.listen(self.engine.sync_engine, "before_cursor_execute", self._tick)
        return self

    def __exit__(self, *_) -> None:
        event.remove(self.engine.sync_engine, "before_cursor_execute", self._tick)

    def _tick(self, *_, **__) -> None:
        self.n += 1


async def _add_lessons(db, classroom, *, lessons: int, runs: int) -> None:
    now = datetime.now(UTC)
    for n in range(lessons):
        contract = LessonContract(
            plan_id=uuid.uuid4(),
            teacher_id=classroom.teacher.id,
            title=f"Lesson {n}",
            subject=MATHS.subject,
            status=ContractStatus.ACTIVE.value,
            version=1,
            brief=MATHS.model_dump(mode="json"),
            activated_at=now,
            activated_by=classroom.teacher.id,
        )
        db.add(contract)
        await db.flush()
        for r in range(runs):
            opened = now - timedelta(days=1 + n * runs + r)
            session = Session(
                contract_id=contract.id,
                class_id=classroom.klass.id,
                status=SessionStatus.CLOSED.value,
                opened_at=opened,
                closes_at=opened + timedelta(minutes=50),
                closed_at=opened + timedelta(minutes=50),
            )
            db.add(session)
            await db.flush()
            db.add_all(
                SessionParticipant(session_id=session.id, student_id=s.id)
                for s in (classroom.alice, classroom.bob)
            )
    await db.commit()


async def test_the_lessons_list_reads_the_same_number_of_queries_however_many_lessons(
    db, client, engine, classroom
):
    headers = classroom.headers(classroom.teacher)
    await _add_lessons(db, classroom, lessons=2, runs=1)
    with _Queries(engine) as few:
        assert (await client.get("/api/teacher/thread/lessons", headers=headers)).status_code == 200
    await _add_lessons(db, classroom, lessons=6, runs=3)
    with _Queries(engine) as many:
        assert (await client.get("/api/teacher/thread/lessons", headers=headers)).status_code == 200
    assert many.n == few.n
    assert many.n <= 15


async def test_class_progress_reads_the_same_number_of_queries_however_many_runs(
    db, client, engine, classroom
):
    headers = classroom.headers(classroom.teacher)
    path = f"/api/teacher/classes/{classroom.klass.id}/progress"
    await _add_lessons(db, classroom, lessons=1, runs=1)
    with _Queries(engine) as few:
        assert (await client.get(path, headers=headers)).status_code == 200
    await _add_lessons(db, classroom, lessons=3, runs=3)
    with _Queries(engine) as many:
        assert (await client.get(path, headers=headers)).status_code == 200
    assert many.n == few.n
    assert many.n <= 15
