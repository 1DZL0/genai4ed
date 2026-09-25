"""ORM models: relational tables with JSON fields. Every enum-valued column is a string
with a check constraint, and every table is append-mostly."""

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

# JSONB on Postgres, plain JSON elsewhere.
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
    """A teacher or a student. Pseudonymous: there is no name column."""

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
    """One signed-in browser; only a digest of the cookie's token is stored."""

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
    """One version of a lesson. Versions share a plan_id; editing an approved one adds the next."""

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
    # The lesson brief (`app.agent.brief.LessonBrief`) as the teacher and the agent agreed it.
    brief: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    # Let a student's past work shape how the agent teaches. Off unless the teacher turns it on.
    use_past_lessons: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )


class Session(Base, TimestampMixin):
    """A lesson: one class taught with one version of a brief. Scheduled, then timed."""

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
    # What the study assigned this student for this lesson. Empty outside a study.
    condition: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)


class EvidenceRecord(Base, TimestampMixin):
    """Append-only evidence ledger; never updated in place."""

    __tablename__ = "evidence_records"
    __table_args__ = (
        _check("kind", EvidenceKind, "ck_evidence_kind"),
        _check("retention_class", RetentionClass, "ck_evidence_retention"),
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
    """Audit trail for one model call: what it was shown, what it said, how it was checked."""

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
    # The ids of exactly the records the agent was shown.
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
    """One item in the teacher's queue, citing the evidence that raised it."""

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
    """A student's outcome for a lesson: suggested by the agent, confirmed by the teacher."""

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
    # [{"name", "points", "max", "reason"}] and development areas, as the model proposed.
    suggested: Mapped[dict] = mapped_column(Json, nullable=False)
    suggested_total: Mapped[int] = mapped_column(Integer, nullable=False)
    # What the teacher confirmed, in the same shape.
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
    """Something a teacher gave the agent to teach from, stored in the database itself."""

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
    # Text pulled out of documents; empty for images, which the agent is shown directly.
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Conversation(Base, TimestampMixin):
    """One thread with the agent: one per teacher, or one per student per lesson."""

    __tablename__ = "conversations"
    __table_args__ = (
        _check("kind", ConversationKind, "ck_conversation_kind"),
        CheckConstraint(
            "(kind = 'student' and student_id is not null and session_id is not null)"
            " or (kind = 'teacher' and teacher_id is not null)",
            name="ck_conversation_owner",
        ),
        UniqueConstraint("kind", "session_id", "student_id", name="uq_conversation_student"),
        UniqueConstraint("kind", "teacher_id", name="uq_conversation_teacher"),
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
    # Ids of what the teacher has on screen beside the conversation, so a reload restores it.
    showing: Mapped[dict | None] = mapped_column(Json)


class Message(Base, TimestampMixin):
    """One thing said in a conversation, by the teacher, a student or the agent."""

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
    # What the agent decided alongside what it said: its move, its judgment, the brief it proposed.
    data: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    material_ids: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_turns.id", ondelete="SET NULL")
    )
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningState(Base, TimestampMixin):
    """Where one student is in a lesson's activity, as the server accepted it."""

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
    """Every teacher action that touches a student's record, so access is auditable."""

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
