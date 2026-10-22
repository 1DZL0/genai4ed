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


# Never held back: a student asking for the teacher, or upset, reaches them as soon as it is seen.
ALWAYS_TOLD = (SignalKind.WELLBEING, SignalKind.ASKED_FOR_TEACHER)


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
