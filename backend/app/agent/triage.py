"""Whether something the agent noticed reaches the teacher now. The agent decides; the
server records everything either way."""

from app.enums import ExceptionKind, SignalKind, TriageAction

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


def is_class_pattern(students_with_misconception: int) -> bool:
    return students_with_misconception >= CLASS_PATTERN_STUDENTS
