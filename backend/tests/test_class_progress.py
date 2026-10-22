"""The class progress grid: every student down the side, every lesson the class has had across,
and how each student did in each, for the class's own teacher only."""

from datetime import UTC, datetime, timedelta

from app.enums import (
    ExceptionKind,
    ExceptionStatus,
    LearningStatus,
    ScoreStatus,
    SessionStatus,
)
from app.models import (
    AgentTurn,
    Exception_,
    LearningState,
    LessonOutcome,
    Session,
    SessionParticipant,
)


def _turn(session, student, request):
    return AgentTurn(
        session_id=session.id,
        student_id=student.id,
        mode="student",
        context_manifest={},
        policy_version="student-agent-v1",
        prompt_version="student-v1",
        provider="scripted",
        model="scripted",
        latency_ms=0,
        validation_outcome="ok",
        leakage_check="passed",
        conflicts=[],
        request=request,
        response={"reply": "Good, what next?"},
    )


def _state(session, student, status=LearningStatus.IN_PROGRESS, step_index=1):
    return LearningState(
        session_id=session.id,
        student_id=student.id,
        status=status.value,
        step_index=step_index,
        turns=3,
        steps=[],
    )


def _outcome(session, student, status, points=(3, 2)):
    criteria = [
        {"name": "Method", "points": points[0], "max": 3, "reason": ""},
        {"name": "Accuracy", "points": points[1], "max": 3, "reason": ""},
    ]
    shape = {"criteria": criteria, "keep": "Clear working.", "develop": []}
    confirmed = status == ScoreStatus.CONFIRMED
    return LessonOutcome(
        session_id=session.id,
        student_id=student.id,
        status=status.value,
        suggested=shape,
        suggested_total=sum(points),
        confirmed=shape if confirmed else None,
        confirmed_total=sum(points) if confirmed else None,
        provider="scripted",
        model="scripted",
        prompt_version="review-v2",
    )


async def _progress(client, classroom, user=None):
    return await client.get(
        f"/api/teacher/classes/{classroom.klass.id}/progress",
        headers=classroom.headers(user or classroom.teacher),
    )


def _cell(body, pseudonym, session):
    row = next(s for s in body["students"] if s["pseudonym"] == pseudonym)
    return next(c for c in row["cells"] if c["session_id"] == str(session.id))


async def test_the_teacher_sees_the_lesson_with_both_students(client, classroom):
    r = await _progress(client, classroom)
    assert r.status_code == 200
    body = r.json()
    assert body["class_id"] == str(classroom.klass.id)
    assert body["label"] == "10B"
    [lesson] = body["lessons"]
    assert lesson["session_id"] == str(classroom.session.id)
    assert lesson["title"] == classroom.contract.title
    assert lesson["status"] == "open"
    assert lesson["steps"] == 3
    assert lesson["date"].endswith("Z")
    assert [s["pseudonym"] for s in body["students"]] == ["10B-01", "10B-02"]
    assert all(len(s["cells"]) == 1 for s in body["students"])


async def test_a_student_who_wrote_has_part_done_and_one_who_never_opened_has_not_started(
    client, classroom, db
):
    db.add(_turn(classroom.session, classroom.alice, {"text": "I take 4 from both sides."}))
    db.add(_state(classroom.session, classroom.alice, step_index=1))
    await db.commit()
    body = (await _progress(client, classroom)).json()
    alice = _cell(body, "10B-01", classroom.session)
    assert alice["state"] == "part"
    assert (alice["steps_done"], alice["steps_total"]) == (1, 3)
    bob = _cell(body, "10B-02", classroom.session)
    assert bob["state"] == "not_started"
    assert bob["steps_done"] == 0
    assert bob["mark"] is None and bob["outcome"] is None


async def test_finishing_counts_every_step(client, classroom, db):
    db.add(_turn(classroom.session, classroom.alice, {"text": "x = 4"}))
    db.add(_state(classroom.session, classroom.alice, LearningStatus.COMPLETED, step_index=2))
    await db.commit()
    alice = _cell((await _progress(client, classroom)).json(), "10B-01", classroom.session)
    assert alice["state"] == "finished"
    assert (alice["steps_done"], alice["steps_total"]) == (3, 3)


async def test_a_student_who_only_saw_the_agents_opening_has_opened_only(client, classroom, db):
    # The agent's opening is a turn for the student, but not the student taking part.
    db.add(_turn(classroom.session, classroom.bob, {}))
    await db.commit()
    bob = _cell((await _progress(client, classroom)).json(), "10B-02", classroom.session)
    assert bob["state"] == "opened"


async def test_a_confirmed_mark_shows_and_a_suggested_one_does_not(client, classroom, db):
    for student in (classroom.alice, classroom.bob):
        db.add(_turn(classroom.session, student, {"text": "x = 5"}))
    db.add(_outcome(classroom.session, classroom.alice, ScoreStatus.CONFIRMED, points=(3, 2)))
    db.add(_outcome(classroom.session, classroom.bob, ScoreStatus.SUGGESTED, points=(1, 1)))
    await db.commit()
    body = (await _progress(client, classroom)).json()
    alice = _cell(body, "10B-01", classroom.session)
    assert alice["outcome"] == "confirmed"
    assert alice["mark"] == {"total": 5, "out_of": 6}
    bob = _cell(body, "10B-02", classroom.session)
    assert bob["outcome"] == "suggested"
    assert bob["mark"] is None


async def test_only_open_alerts_are_counted(client, classroom, db):
    for status in (ExceptionStatus.OPEN, ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED):
        db.add(
            Exception_(
                session_id=classroom.session.id,
                student_id=classroom.bob.id,
                kind=ExceptionKind.TEACHER_REQUESTED.value,
                priority=1,
                status=status.value,
                summary="Pressed Ask my teacher.",
            )
        )
    await db.commit()
    body = (await _progress(client, classroom)).json()
    assert _cell(body, "10B-02", classroom.session)["alerts_open"] == 2
    assert _cell(body, "10B-01", classroom.session)["alerts_open"] == 0


async def test_lessons_run_oldest_first_and_a_scheduled_one_is_left_out(client, classroom, db):
    earlier = Session(
        contract_id=classroom.contract.id,
        class_id=classroom.klass.id,
        status=SessionStatus.CLOSED.value,
        opened_at=datetime.now(UTC) - timedelta(days=7),
        closed_at=datetime.now(UTC) - timedelta(days=7, minutes=-40),
    )
    planned = Session(
        contract_id=classroom.contract.id,
        class_id=classroom.klass.id,
        status=SessionStatus.SCHEDULED.value,
        scheduled_for=datetime.now(UTC) + timedelta(days=2),
    )
    db.add_all([earlier, planned])
    await db.flush()
    # Only alice was in the earlier lesson.
    db.add(SessionParticipant(session_id=earlier.id, student_id=classroom.alice.id))
    await db.commit()
    body = (await _progress(client, classroom)).json()
    assert [lesson["session_id"] for lesson in body["lessons"]] == [
        str(earlier.id),
        str(classroom.session.id),
    ]
    assert _cell(body, "10B-02", earlier)["state"] == "not_in_lesson"
    assert _cell(body, "10B-01", earlier)["state"] == "not_started"


async def test_a_student_in_a_lesson_who_is_not_on_the_roster_still_has_a_row(
    client, classroom, db
):
    db.add(SessionParticipant(session_id=classroom.session.id, student_id=classroom.outsider.id))
    await db.commit()
    body = (await _progress(client, classroom)).json()
    assert [s["pseudonym"] for s in body["students"]] == ["10B-01", "10B-02", "10C-01"]


async def test_a_class_with_no_lessons_yet_has_no_columns(client, classroom, db):
    classroom.session.status = SessionStatus.SCHEDULED.value
    await db.commit()
    body = (await _progress(client, classroom)).json()
    assert body["lessons"] == []
    assert all(s["cells"] == [] for s in body["students"])


async def test_another_teacher_cannot_see_the_class(client, classroom):
    r = await _progress(client, classroom, classroom.other_teacher)
    assert r.status_code == 404
