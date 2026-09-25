"""Sorts each signal the agent noticed into log, summarise or alert.

The teacher's escalation rules apply where set; the defaults below otherwise. Pure, no I/O.
"""

from app.agent.policy import PolicyRules
from app.enums import ExceptionKind, Severity, SignalKind, TriageAction

# (after how many times in the lesson, action) when the teacher hasn't said.
DEFAULTS: dict[SignalKind, tuple[int, TriageAction]] = {
    SignalKind.ASKED_FOR_TEACHER: (1, TriageAction.ALERT),
    SignalKind.WELLBEING: (1, TriageAction.ALERT),
    SignalKind.MANIPULATION_ATTEMPT: (2, TriageAction.ALERT),
    SignalKind.STRUGGLING: (3, TriageAction.ALERT),
    SignalKind.OFF_TASK: (3, TriageAction.SUMMARISE),
    SignalKind.MISCONCEPTION: (1, TriageAction.SUMMARISE),
    SignalKind.FAST_PROGRESS: (1, TriageAction.SUMMARISE),
    SignalKind.UNRESOLVED_QUESTION: (1, TriageAction.SUMMARISE),
}

# The same misconception in this many students is a class problem.
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


def triage(
    signal: SignalKind, *, severity: Severity, seen: int, rules: PolicyRules
) -> TriageAction:
    """`seen` counts this signal for this student in this lesson, including this one."""
    # A wellbeing concern is never left to a count or a setting.
    if signal is SignalKind.WELLBEING:
        return TriageAction.ALERT

    rule = rules.escalation_for(signal)
    after, action = (rule.after, rule.action) if rule else DEFAULTS[signal]

    if severity is Severity.HIGH and signal is not SignalKind.FAST_PROGRESS:
        return TriageAction.ALERT
    if seen >= after:
        return action
    # Below the threshold it still reaches the summary if the eventual action would.
    if action is not TriageAction.LOG and seen > 1:
        return TriageAction.SUMMARISE
    return TriageAction.LOG


def is_class_pattern(students_with_misconception: int) -> bool:
    return students_with_misconception >= CLASS_PATTERN_STUDENTS
