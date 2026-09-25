"""Vocabularies shared by the ORM, the agent and the API. Stored as strings with check
constraints rather than native Postgres enums, so adding a value is a cheap migration."""

from enum import StrEnum


class Role(StrEnum):
    TEACHER = "teacher"
    STUDENT = "student"


class ContractStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class SessionStatus(StrEnum):
    SCHEDULED = "scheduled"
    OPEN = "open"
    PAUSED = "paused"
    CLOSED = "closed"


class EvidenceKind(StrEnum):
    """What the agent judged, noticed or was stopped from doing; the chat itself is in messages."""

    ASSESSMENT = "assessment"
    SIGNAL = "signal"
    POLICY_EVENT = "policy_event"
    STEP_CHANGE = "step_change"
    TEACHER_GUIDANCE = "teacher_guidance"


class ScoreStatus(StrEnum):
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"


class RetentionClass(StrEnum):
    """Raw chat is kept for less time than submitted work."""

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
    """Breaches of the teacher's rules seen in the agent's own replies; never about the student."""

    # Stated the answer before the rules allow it.
    ANSWER_LEAKAGE = "answer_leakage"
    # Gave away more of the answer than the rules allow at this point.
    OVER_DISCLOSURE = "over_disclosure"
    # A reply long enough to be the student's work, not help with it.
    WROTE_THE_WORK = "wrote_the_work"
    # Moved a student on without judging what they said.
    SKIPPED_ASSESSMENT = "skipped_assessment"
    # Told the teacher it had done something only they can do.
    FALSE_CLAIM = "false_claim"
    # Gave a form of help other than the one the ladder allows next.
    OFF_LADDER = "off_ladder"
    MALFORMED_OUTPUT = "malformed_output"


class ExceptionKind(StrEnum):
    """What can reach the teacher's queue."""

    TEACHER_REQUESTED = "teacher_requested"
    SAFEGUARDING = "safeguarding"
    STRUGGLING = "struggling"
    MANIPULATION = "manipulation"
    MISCONCEPTION_PATTERN = "misconception_pattern"
    UNRESOLVED_QUESTION = "unresolved_question"
    OFF_TASK = "off_task"
    FAST_PROGRESS = "fast_progress"
    # The platform held back one of the agent's own replies. Says nothing of the student.
    POLICY_CONFLICT = "policy_conflict"


class ExceptionStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


# Lower sorts first in the teacher's queue.
EXCEPTION_PRIORITY: dict[ExceptionKind, int] = {
    ExceptionKind.SAFEGUARDING: 0,
    ExceptionKind.TEACHER_REQUESTED: 1,
    ExceptionKind.STRUGGLING: 2,
    ExceptionKind.MANIPULATION: 3,
    ExceptionKind.MISCONCEPTION_PATTERN: 3,
    ExceptionKind.UNRESOLVED_QUESTION: 4,
    ExceptionKind.OFF_TASK: 4,
    ExceptionKind.FAST_PROGRESS: 5,
    ExceptionKind.POLICY_CONFLICT: 3,
}


class TeacherAction(StrEnum):
    """Everything a teacher does that touches a student's record."""

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


class ConversationKind(StrEnum):
    """Where the agent is talking; each kind sees different things."""

    TEACHER = "teacher"  # one thread per teacher, for everything they do
    STUDENT = "student"  # one per student per lesson


class MessageRole(StrEnum):
    TEACHER = "teacher"
    STUDENT = "student"
    AGENT = "agent"
    # Something that happened rather than something said: a reply was held back, the class paused.
    EVENT = "event"


class Audience(StrEnum):
    """Who may read a message. Teacher guidance in a student's conversation is hidden from them."""

    ALL = "all"
    TEACHER = "teacher"


class StepKind(StrEnum):
    EXPLAIN = "explain"
    QUESTION = "question"
    PRACTICE = "practice"
    CHECK = "check"


class Disclosure(StrEnum):
    """How much of the answer to the current step a reply gives away."""

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
    """What becomes of a signal: logged, gathered into the teacher's summary, or raised now."""

    LOG = "log"
    SUMMARISE = "summarise"
    ALERT = "alert"


class LearningStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
