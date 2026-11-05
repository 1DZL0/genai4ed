"""What the agent noticed and whether it reaches the teacher: the triage rule (the agent
decides, the teacher's rule for the kind overrides once it has happened often enough, a
wellbeing concern is never held back); the alerts that time answers (struggling clears when
the student moves on, off task when they answer right); and who else in the class slipped
on a step. The server records everything either way."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import EvidenceKind, ExceptionKind, ExceptionStatus, SignalKind, TriageAction
from app.models import EvidenceRecord, Exception_, User

# ---------- does it reach the teacher ----------

# The same misconception in this many students is a class problem worth a line on the board.
CLASS_PATTERN_STUDENTS = 3

ALERT_KIND: dict[SignalKind, ExceptionKind] = {
    SignalKind.ASKED_FOR_TEACHER: ExceptionKind.TEACHER_REQUESTED,
    SignalKind.WELLBEING: ExceptionKind.SAFEGUARDING,
    SignalKind.MANIPULATION_ATTEMPT: ExceptionKind.MANIPULATION,
    SignalKind.STRUGGLING: ExceptionKind.STRUGGLING,
    SignalKind.OFF_TASK: ExceptionKind.OFF_TASK,
    SignalKind.MISCONCEPTION: ExceptionKind.MISCONCEPTION_PATTERN,
    SignalKind.FAST_PROGRESS: ExceptionKind.FAST_PROGRESS,
    SignalKind.UNRESOLVED_QUESTION: ExceptionKind.UNRESOLVED_QUESTION,
}


def triage(signal: SignalKind, *, tell_teacher: bool) -> TriageAction:
    """An alert when the agent says the teacher should know now; otherwise a record."""
    return TriageAction.ALERT if tell_teacher else TriageAction.LOG


# Never held back: a student asking for the teacher, or upset, reaches them as soon as it is
# seen. Defined with the rules, so the card and the read-back list the same two.
from app.agent.policy import ALWAYS_TOLD  # noqa: E402


def decide(signal: SignalKind, *, tell_teacher: bool, rule, seen: int) -> TriageAction:
    """What happens to a signal. The teacher's rule for its kind decides once it has happened
    often enough (alert, kept for the summary, or kept in the record), whatever the agent
    thought; before that it is kept. With no rule, the agent's call stands. A wellbeing
    concern or a call for the teacher the agent flags is never held back."""
    model = triage(signal, tell_teacher=tell_teacher)
    if signal in ALWAYS_TOLD and model is TriageAction.ALERT:
        return model
    if rule is None:
        return model
    return rule.action if seen >= rule.after else TriageAction.LOG


def is_class_pattern(students_with_misconception: int) -> bool:
    return students_with_misconception >= CLASS_PATTERN_STUDENTS


# ---------- alerts that answer themselves ----------


async def students_with_misconception(
    db: AsyncSession, session_id: uuid.UUID, step_index: int
) -> list[str]:
    """Pseudonyms of the students who have shown a misconception on this step."""
    rows = await db.execute(
        select(func.distinct(User.pseudonym))
        .select_from(EvidenceRecord)
        .join(User, User.id == EvidenceRecord.student_id)
        .where(
            EvidenceRecord.session_id == session_id,
            EvidenceRecord.kind == EvidenceKind.SIGNAL.value,
            EvidenceRecord.payload["signal"].as_string() == SignalKind.MISCONCEPTION.value,
            EvidenceRecord.payload["step_index"].as_integer() == step_index,
        )
        .order_by(User.pseudonym)
    )
    return [r[0] for r in rows]


async def let_go(
    db, session, student, kind: ExceptionKind, *, because: str, before_step: int | None = None
) -> None:
    """Close an open alert of this kind for this student: what they did next answered it. The
    record keeps the alert, marked as cleared without the teacher, so the board can let it go
    and the research view can still count it. With `before_step`, only alerts about an
    earlier step (or about no step) go."""
    for alert in (
        await db.scalars(
            select(Exception_).where(
                Exception_.session_id == session.id,
                Exception_.student_id == student.id,
                Exception_.kind == kind.value,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
    ).all():
        about = alert.payload.get("step_index")
        if before_step is not None and isinstance(about, int) and about >= before_step:
            continue
        alert.status = ExceptionStatus.RESOLVED.value
        alert.payload = {
            **alert.payload,
            "cleared_because": because,
            "cleared_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
