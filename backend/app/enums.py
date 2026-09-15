"""Vocabularies shared by the ORM, the policy and the API.

Stored as strings with database check constraints rather than native Postgres
enums: new exception kinds and rungs are expected, and a string column keeps
those migrations cheap while the Python enum keeps the code honest.
"""

from enum import StrEnum


class Role(StrEnum):
    TEACHER = "teacher"
    STUDENT = "student"


class Rung(StrEnum):
    """The teacher-defined assistance ladder (concept note S2).

    Order matters: `LADDER` below is the canonical escalation sequence, and the
    policy may advance at most one rung per turn.
    """

    ATTEMPT = "attempt"
    DIAGNOSTIC_QUESTION = "diagnostic_question"
    CONCEPTUAL_CUE = "conceptual_cue"
    TARGETED_HINT = "targeted_hint"
    ANALOGOUS_EXAMPLE = "analogous_example"
    PARTIAL_STEP = "partial_step"
    FULL_SOLUTION = "full_solution"


LADDER: tuple[Rung, ...] = (
    Rung.ATTEMPT,
    Rung.DIAGNOSTIC_QUESTION,
    Rung.CONCEPTUAL_CUE,
    Rung.TARGETED_HINT,
    Rung.ANALOGOUS_EXAMPLE,
    Rung.PARTIAL_STEP,
    Rung.FULL_SOLUTION,
)


def rung_index(rung: Rung) -> int:
    return LADDER.index(rung)


class ContractStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class SessionStatus(StrEnum):
    OPEN = "open"
    PAUSED = "paused"
    CLOSED = "closed"


class EvidenceKind(StrEnum):
    ATTEMPT = "attempt"
    GRADING_RESULT = "grading_result"
    HINT = "hint"
    TEACHER_FEEDBACK = "teacher_feedback"
    TEACHER_INTERVENTION = "teacher_intervention"
    EXPLORATORY_TURN = "exploratory_turn"


class RetentionClass(StrEnum):
    """S4: raw exploratory chat is kept for less time than submitted work."""

    SUBMITTED_WORK = "submitted_work"
    EXPLORATORY_CHAT = "exploratory_chat"


class ValidationOutcome(StrEnum):
    OK = "ok"
    REGENERATED = "regenerated"
    WITHHELD = "withheld"


class LeakageCheck(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ConflictCode(StrEnum):
    """Observable assistance-policy conflicts.

    These describe what the platform saw in its own output. They are never a
    claim about the student's intent (concept note S2).
    """

    RUNG_EXCEEDED = "rung_exceeded"
    ANSWER_LEAKAGE = "answer_leakage"
    INVALID_DIAGNOSIS = "invalid_diagnosis"
    MALFORMED_OUTPUT = "malformed_output"


class ExceptionKind(StrEnum):
    TEACHER_REQUESTED = "teacher_requested"
    REPEATED_INCORRECT = "repeated_incorrect"
    ASSISTANCE_POLICY_CONFLICT = "assistance_policy_conflict"
    TUTOR_UNCERTAINTY = "tutor_uncertainty"
    SAFEGUARDING = "safeguarding"


class ExceptionStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


# Lower number sorts first in the teacher's queue. Safeguarding and an explicit
# request from a student outrank anything the platform inferred about itself.
EXCEPTION_PRIORITY: dict[ExceptionKind, int] = {
    ExceptionKind.SAFEGUARDING: 0,
    ExceptionKind.TEACHER_REQUESTED: 1,
    ExceptionKind.REPEATED_INCORRECT: 2,
    ExceptionKind.ASSISTANCE_POLICY_CONFLICT: 3,
    ExceptionKind.TUTOR_UNCERTAINTY: 4,
}


class TeacherAction(StrEnum):
    """Everything a teacher does that touches a student's record is logged."""

    TRANSCRIPT_DRILLDOWN = "transcript_drilldown"
    MESSAGE_STUDENT = "message_student"
    PAUSE_SESSION = "pause_session"
    RESUME_SESSION = "resume_session"
    CLOSE_SESSION = "close_session"
    ACKNOWLEDGE_EXCEPTION = "acknowledge_exception"
    ISSUE_JOIN_CODES = "issue_join_codes"
