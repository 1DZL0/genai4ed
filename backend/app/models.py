"""ORM models.

Relational with JSON fields, as the concept note permits (S3). The shapes that
carry the design:

* `LessonContract.brief` is what the teacher and the class agent agreed the
  lesson is - objectives, activity, rules - as data the teacher controls.
* `Conversation` and `Message` are every exchange with the agent. Which ones
  the agent may see in a given turn is decided in `app.agent.context`.
* `EvidenceRecord` is an append-only ledger of what the agent judged, noticed
  and was stopped from doing. Nothing here stores a narrative learner profile.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.enums import (
    Audience,
    ContractStatus,
    ConversationKind,
    EvidenceKind,
    ExceptionKind,
    ExceptionStatus,
    LeakageCheck,
    LearningStatus,
    MessageRole,
    RetentionClass,
    Role,
    ScoreStatus,
    SessionStatus,
    TeacherAction,
    ValidationOutcome,
)

# JSONB on Postgres, plain JSON elsewhere so the models stay importable in
# tooling that has no Postgres dialect loaded.
Json = JSON().with_variant(JSONB(), "postgresql")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _check(column: str, enum_cls: type[StrEnum], name: str) -> CheckConstraint:
    allowed = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} in ({allowed})", name=name)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Base, TimestampMixin):
    """A teacher or a student.

    Pseudonymous by construction: there is deliberately no name column. The
    pseudonym -> person mapping is held by the teacher outside this system.

    Teachers sign in with an email and password; the email is the teacher's
    work address, not student data. Students never have either - they sign in
    with a join code their teacher issues, stored only as a keyed digest. The
    check constraints make that split impossible to get wrong by accident.
    """

    __tablename__ = "users"
    __table_args__ = (
        _check("role", Role, "ck_users_role"),
        CheckConstraint(
            "role = 'teacher' or (email is null and password_hash is null)",
            name="ck_users_student_has_no_credentials",
        ),
        CheckConstraint(
            "role = 'student' or join_code_digest is null",
            name="ck_users_teacher_has_no_join_code",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    pseudonym: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    join_code_digest: Mapped[str | None] = mapped_column(String(64), unique=True)


class AuthSession(Base, TimestampMixin):
    """One signed-in browser.

    Held server-side, so signing out or issuing a new join code ends it at
    once. Only a digest of the cookie's token is stored.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user", "user_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Class(Base, TimestampMixin):
    __tablename__ = "classes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)


class Enrolment(Base, TimestampMixin):
    __tablename__ = "enrolments"
    __table_args__ = (UniqueConstraint("class_id", "student_id", name="uq_enrolment"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class LessonContract(Base, TimestampMixin):
    """One version of a lesson: what the teacher approves before the class agent teaches it.

    A lesson is reusable. Every version of the same lesson shares a `plan_id`;
    changing an approved lesson creates the next version rather than changing
    the one classes were taught with, so a session always points at exactly
    what its class was held to. The class is chosen when a lesson is booked.

    Everything the teacher decided lives in `brief` as data they can change by
    talking to the agent, never as constants in code.
    """

    __tablename__ = "lesson_contracts"
    __table_args__ = (
        _check("status", ContractStatus, "ck_contract_status"),
        UniqueConstraint("plan_id", "version", name="uq_plan_version"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4, index=True
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContractStatus.DRAFT.value
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # The lesson brief the teacher and the class agent shape together
    # (`app.agent.brief.LessonBrief`): objectives, activity steps, the rules the
    # agent works under and how learning is judged.
    brief: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    # Storing a student's past work, finding what is relevant, and letting it
    # change how the agent teaches are three separate decisions. This is the
    # third, and it is off unless the teacher turns it on.
    use_past_lessons: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )


class Session(Base, TimestampMixin):
    """A lesson: one class taught with one version of a lesson brief.

    It is `scheduled` until the teacher starts it, then timed. The agent works
    with students only while it is `open`; pausing the class stops it.
    """

    __tablename__ = "sessions"
    __table_args__ = (_check("status", SessionStatus, "ck_session_status"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lesson_contracts.id", ondelete="RESTRICT"), nullable=False
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SessionStatus.OPEN.value
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionParticipant(Base, TimestampMixin):
    """Membership is the isolation boundary: a student reaches only their own."""

    __tablename__ = "session_participants"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_participant"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvidenceRecord(Base, TimestampMixin):
    """Append-only evidence ledger (S4).

    Never updated in place. `retention_class` and `purge_after` are what make
    the shorter retention of raw chat a column rather than a promise.
    """

    __tablename__ = "evidence_records"
    __table_args__ = (
        _check("kind", EvidenceKind, "ck_evidence_kind"),
        _check("retention_class", RetentionClass, "ck_evidence_retention"),
        # A student's record across lessons, newest first: what memory retrieval reads.
        Index("ix_evidence_student", "student_id", "created_at"),
        Index("ix_evidence_session", "session_id", "created_at"),
        Index("ix_evidence_purge", "purge_after"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    provenance: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentTurn(Base, TimestampMixin):
    """Audit trail for one call to the class agent's model, and the source of
    the feasibility metrics in S5: rule compliance, answer leakage, latency and
    failures.

    `context_manifest` holds the ids of exactly the records the agent was shown,
    so what it knew when it answered can always be reconstructed."""

    __tablename__ = "agent_turns"
    __table_args__ = (
        _check("validation_outcome", ValidationOutcome, "ck_turn_validation"),
        _check("leakage_check", LeakageCheck, "ck_turn_leakage"),
        Index("ix_turn_session", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE", name="fk_turn_conversation"),
    )
    mode: Mapped[str | None] = mapped_column(String(16))
    context_manifest: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    leakage_check: Mapped[str] = mapped_column(String(16), nullable=False)
    conflicts: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    request: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    response: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)


class Exception_(Base, TimestampMixin):
    """One item in the teacher's prioritised queue. Every exception cites the
    evidence that produced it."""

    __tablename__ = "exceptions"
    __table_args__ = (
        _check("kind", ExceptionKind, "ck_exception_kind"),
        _check("status", ExceptionStatus, "ck_exception_status"),
        Index("ix_exception_queue", "session_id", "status", "priority", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ExceptionStatus.OPEN.value
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_record_ids: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    payload: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class LessonOutcome(Base, TimestampMixin):
    """A student's outcome for a lesson: suggested by the agent, confirmed by the teacher.

    The suggestion and the confirmed outcome are kept side by side, so the
    record shows both what the model proposed and what the teacher decided.
    """

    __tablename__ = "lesson_outcomes"
    __table_args__ = (
        _check("status", ScoreStatus, "ck_score_status"),
        UniqueConstraint("session_id", "student_id", name="uq_outcome_student"),
        Index("ix_scores_session_status", "session_id", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ScoreStatus.SUGGESTED.value
    )
    # [{"name", "points", "max", "reason"}] and the development areas, as the model proposed.
    suggested: Mapped[dict] = mapped_column(Json, nullable=False)
    suggested_total: Mapped[int] = mapped_column(Integer, nullable=False)
    # What the teacher confirmed, and a comment for the student.
    confirmed: Mapped[dict | None] = mapped_column(Json)
    confirmed_total: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)


class Material(Base, TimestampMixin):
    """Something a teacher gave the class agent to teach from: a PDF, slides, a
    document, an image, notes.

    Kept in the lesson's own database rather than a file store, so the school
    pilot's data stays in one isolated, destroyable place. `plan_id` ties it to
    every version of the lesson.
    """

    __tablename__ = "materials"
    __table_args__ = (Index("ix_materials_plan", "plan_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Text pulled out of documents so the agent can read them. Empty for images,
    # which the agent is shown directly.
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Conversation(Base, TimestampMixin):
    """One thread with the class agent.

    The agent is the same everywhere; the kind decides what it may see. A
    student conversation belongs to exactly one student in one lesson, and is
    the only conversation that student's agent context is built from.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        _check("kind", ConversationKind, "ck_conversation_kind"),
        CheckConstraint(
            "(kind = 'student' and student_id is not null and session_id is not null)"
            " or (kind = 'design' and teacher_id is not null and plan_id is not null)"
            " or (kind = 'classroom' and teacher_id is not null and session_id is not null)",
            name="ck_conversation_owner",
        ),
        UniqueConstraint("kind", "session_id", "student_id", name="uq_conversation_student"),
        Index("ix_conversations_plan", "plan_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    teacher_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Message(Base, TimestampMixin):
    """One thing said in a conversation, by the teacher, a student or the agent.

    `data` holds what the agent decided alongside what it said - its move, its
    judgment, the brief it proposed - so the record shows the reasoning the
    platform acted on, not just the words.
    """

    __tablename__ = "messages"
    __table_args__ = (
        _check("role", MessageRole, "ck_message_role"),
        _check("audience", Audience, "ck_message_audience"),
        _check("retention_class", RetentionClass, "ck_message_retention"),
        Index("ix_messages_conversation", "conversation_id", "created_at"),
        Index("ix_messages_purge", "purge_after"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    audience: Mapped[str] = mapped_column(String(16), nullable=False, default=Audience.ALL.value)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    material_ids: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_turns.id", ondelete="SET NULL")
    )
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningState(Base, TimestampMixin):
    """Where one student is in one lesson's activity.

    The agent proposes moves; this is what the server accepted, so progress
    can't be talked into existence by a reply that skipped the judging.
    """

    __tablename__ = "learning_states"
    __table_args__ = (
        _check("status", LearningStatus, "ck_learning_status"),
        UniqueConstraint("session_id", "student_id", name="uq_learning_state"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=LearningStatus.NOT_STARTED.value
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Answers given on the current step, which is what unlocks more help.
    attempts_on_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Replies in a row on this step where the student wasn't getting there.
    struggle_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # One entry per brief step: {"judgment", "attempts", "evidence"}.
    steps: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClassInsight(Base, TimestampMixin):
    """The agent's summary of a lesson for the teacher, citing the records it drew on."""

    __tablename__ = "class_insights"
    __table_args__ = (Index("ix_insights_session", "session_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    items: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    model: Mapped[str] = mapped_column(String(128), nullable=False)


class TeacherAccessLog(Base, TimestampMixin):
    """S4: transcript access is by deliberate drill-down, disclosed to students
    and auditable afterwards."""

    __tablename__ = "teacher_access_log"
    __table_args__ = (
        _check("action", TeacherAction, "ck_access_action"),
        Index("ix_access_session", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
