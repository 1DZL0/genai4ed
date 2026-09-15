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
    SCHEDULED = "scheduled"
    OPEN = "open"
    PAUSED = "paused"
    CLOSED = "closed"


class ItemKind(StrEnum):
    """What a task asks the student to produce, which decides how it is marked.

    A short answer is compared with the teacher's expected answer. A written
    response has no single right answer: it is marked against the teacher's
    rubric, by an AI suggestion the teacher confirms.
    """

    SHORT_ANSWER = "short_answer"
    WRITTEN_RESPONSE = "written_response"


class EvidenceKind(StrEnum):
    ATTEMPT = "attempt"
    GRADING_RESULT = "grading_result"
    HINT = "hint"
    TEACHER_FEEDBACK = "teacher_feedback"
    TEACHER_INTERVENTION = "teacher_intervention"
    EXPLORATORY_TURN = "exploratory_turn"
    # Written responses: the text as the student left it, what they handed in,
    # and what they asked the tutor.
    DRAFT = "draft"
    SUBMISSION = "submission"
    TUTOR_REQUEST = "tutor_request"
    # The class agent. What it judged, what it noticed, what the rules stopped,
    # where the student moved in the activity, and what the teacher told it.
    # The conversation itself lives in `messages`; these are the evidence
    # drawn from it.
    ASSESSMENT = "assessment"
    SIGNAL = "signal"
    POLICY_EVENT = "policy_event"
    STEP_CHANGE = "step_change"
    TEACHER_GUIDANCE = "teacher_guidance"


class TutorAsk(StrEnum):
    """The ways a student can ask their tutor for help with a written response."""

    STUCK = "stuck"
    LANGUAGE = "language"
    FEEDBACK = "feedback"
    QUESTION = "question"


class ScoreStatus(StrEnum):
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"


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
    # Written responses: a reply long enough to be the student's work, not help with it.
    WROTE_THE_WORK = "wrote_the_work"
    # A sentence rewritten before the student had tried and asked again.
    EARLY_REWRITE = "early_rewrite"
    # The class agent: gave away more of the answer than the rules allow at
    # this point, or moved a student on without judging what they said.
    OVER_DISCLOSURE = "over_disclosure"
    SKIPPED_ASSESSMENT = "skipped_assessment"


class ExceptionKind(StrEnum):
    TEACHER_REQUESTED = "teacher_requested"
    REPEATED_INCORRECT = "repeated_incorrect"
    ASSISTANCE_POLICY_CONFLICT = "assistance_policy_conflict"
    TUTOR_UNCERTAINTY = "tutor_uncertainty"
    SAFEGUARDING = "safeguarding"
    # Written responses: asking for help again and again with no new writing.
    STUCK = "stuck"
    # Raised by triage from what the class agent noticed.
    STRUGGLING = "struggling"
    MANIPULATION = "manipulation"
    MISCONCEPTION_PATTERN = "misconception_pattern"
    UNRESOLVED_QUESTION = "unresolved_question"
    OFF_TASK = "off_task"
    FAST_PROGRESS = "fast_progress"


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
    ExceptionKind.STUCK: 2,
    ExceptionKind.ASSISTANCE_POLICY_CONFLICT: 3,
    ExceptionKind.TUTOR_UNCERTAINTY: 4,
    ExceptionKind.STRUGGLING: 2,
    ExceptionKind.MANIPULATION: 3,
    ExceptionKind.MISCONCEPTION_PATTERN: 3,
    ExceptionKind.UNRESOLVED_QUESTION: 4,
    ExceptionKind.OFF_TASK: 4,
    ExceptionKind.FAST_PROGRESS: 5,
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
    SCHEDULE_LESSON = "schedule_lesson"
    START_LESSON = "start_lesson"
    CHANGE_PHASE = "change_phase"
    REVIEW_STUDENT = "review_student"
    CONFIRM_SCORE = "confirm_score"
    GUIDE_STUDENT = "guide_student"
    ASK_AGENT = "ask_agent"


# ---------- the class agent ----------


class ConversationKind(StrEnum):
    """Where the one class agent is talking. Each kind sees different things."""

    DESIGN = "design"  # with the teacher, shaping a lesson
    CLASSROOM = "classroom"  # with the teacher, about a running or finished lesson
    STUDENT = "student"  # with one student, in one lesson


class MessageRole(StrEnum):
    TEACHER = "teacher"
    STUDENT = "student"
    AGENT = "agent"
    # Something that happened rather than something said: a rule stopped a
    # reply, the teacher paused the class.
    EVENT = "event"


class Audience(StrEnum):
    """Who may read a message. Teacher guidance in a student's conversation is
    for the agent and the teacher, never shown to the student."""

    ALL = "all"
    TEACHER = "teacher"


class StepKind(StrEnum):
    EXPLAIN = "explain"
    QUESTION = "question"
    PRACTICE = "practice"
    CHECK = "check"


class Disclosure(StrEnum):
    """How much of the answer to the current step a reply gives away.

    Explaining the idea itself is always allowed; this is about the answer.
    """

    NONE = "none"
    HINT = "hint"
    PARTIAL = "partial"
    FULL = "full"


DISCLOSURE_ORDER: tuple[Disclosure, ...] = (
    Disclosure.NONE,
    Disclosure.HINT,
    Disclosure.PARTIAL,
    Disclosure.FULL,
)


class AgentMove(StrEnum):
    """What the agent chose to do next with a student."""

    ASK = "ask"
    FOLLOW_UP = "follow_up"
    CLARIFY = "clarify"
    CHALLENGE = "challenge"
    HINT = "hint"
    EXPLAIN = "explain"
    EXAMPLE = "example"
    SIMPLIFY = "simplify"
    HARDER = "harder"
    JUSTIFY = "justify"
    REVISIT = "revisit"
    ADVANCE = "advance"
    COMPLETE = "complete"
    DECLINE = "decline"


class Judgment(StrEnum):
    MET = "met"
    PARTIAL = "partial"
    NOT_MET = "not_met"
    UNCLEAR = "unclear"


class SignalKind(StrEnum):
    """What the agent may notice about a student. Observations, not verdicts."""

    STRUGGLING = "struggling"
    MISCONCEPTION = "misconception"
    MANIPULATION_ATTEMPT = "manipulation_attempt"
    OFF_TASK = "off_task"
    FAST_PROGRESS = "fast_progress"
    UNRESOLVED_QUESTION = "unresolved_question"
    WELLBEING = "wellbeing"
    ASKED_FOR_TEACHER = "asked_for_teacher"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TriageAction(StrEnum):
    """What becomes of a signal: kept in the record, gathered into the teacher's
    summary, or put in front of the teacher now."""

    LOG = "log"
    SUMMARISE = "summarise"
    ALERT = "alert"


class LearningStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
