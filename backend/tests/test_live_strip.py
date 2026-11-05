"""The strip across the top of the teacher's screen names who is struggling and who has
finished, not only how many, so the screen can tell the teacher when either changes."""

from datetime import UTC, datetime, timedelta

from app.enums import EvidenceKind, LearningStatus, RetentionClass, SignalKind, TriageAction
from app.models import EvidenceRecord, LearningState


def _state(session, student, status=LearningStatus.IN_PROGRESS, step_index=1):
    return LearningState(
        session_id=session.id,
        student_id=student.id,
        status=status.value,
        step_index=step_index,
        turns=3,
        steps=[],
    )


def _struggling_signal(session, student, step_index):
    return EvidenceRecord(
        session_id=session.id,
        student_id=student.id,
        kind=EvidenceKind.SIGNAL.value,
        payload={
            "signal": SignalKind.STRUGGLING.value,
            "step_index": step_index,
            "note": "Two wrong tries.",
            "action": TriageAction.LOG.value,
        },
        provenance={},
        retention_class=RetentionClass.SUBMITTED_WORK.value,
        purge_after=datetime.now(UTC) + timedelta(days=30),
    )


async def _strip(client, classroom):
    r = await client.get("/api/teacher/thread", headers=classroom.headers(classroom.teacher))
    assert r.status_code == 200
    [row] = r.json()["strip"]
    return row


async def test_the_strip_names_who_is_struggling_and_who_has_finished(client, classroom, db):
    db.add(_state(classroom.session, classroom.alice, step_index=1))
    db.add(_struggling_signal(classroom.session, classroom.alice, step_index=1))
    db.add(_state(classroom.session, classroom.bob, LearningStatus.COMPLETED, step_index=2))
    await db.commit()

    row = await _strip(client, classroom)
    assert row["counts"] == {"struggling": 1, "finished": 1}
    assert row["struggling"] == [
        {
            "student_id": str(classroom.alice.id),
            "pseudonym": classroom.alice.pseudonym,
            "step_name": "Both sides",
        }
    ]
    assert row["finished"] == [
        {"student_id": str(classroom.bob.id), "pseudonym": classroom.bob.pseudonym}
    ]


async def test_the_strips_lists_are_empty_when_nobody_is_in_that_state(client, classroom):
    row = await _strip(client, classroom)
    assert row["struggling"] == []
    assert row["finished"] == []
