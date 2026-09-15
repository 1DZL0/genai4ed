"""ORM models.

Relational with JSON fields, as the concept note permits (S3). Two shapes carry
the design:

* `EvidenceRecord` is an append-only ledger. Nothing in this schema stores a
  narrative learner profile; a recurring misconception is recomputed per turn
  from these rows and cites them (S4).
* `LessonContract` holds the assistance ladder, thresholds and material as
  teacher-authored data, so teacher authority is not constants in code.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import (
    ContractStatus,
    EvidenceKind,
    ExceptionKind,
    ExceptionStatus,
    ItemKind,
    LeakageCheck,
    RetentionClass,
    Role,
    Rung,
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


class Objective(Base, TimestampMixin):
    """A learning objective. Evidence is retrieved by this tag (S4)."""

    __tablename__ = "objectives"
    __table_args__ = (UniqueConstraint("code", name="uq_objective_code"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class LessonContract(Base, TimestampMixin):
    """One version of a lesson plan: what the teacher approves before a lesson runs.

    A plan is reusable. Every version of the same plan shares a `plan_id`;
    editing an approved plan creates the next version rather than changing the
    one lessons were taught with, so a session always points at exactly what
    its class was held to. `class_id` is optional for the same reason - the
    class is chosen when a lesson is scheduled, not when the plan is written.

    `assistance_ladder` is the ordered list of permitted rungs plus
    `allow_full_solution`; `exception_thresholds` is what routes her attention;
    `timeline` is the lesson's phases, marking which ones switch tutors on.
    All of it is data she can change without a deploy.
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
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    timeline: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContractStatus.DRAFT.value
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assistance_ladder: Mapped[dict] = mapped_column(Json, nullable=False)
    exception_thresholds: Mapped[dict] = mapped_column(Json, nullable=False)
    material: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )

    items: Mapped[list["ContractItem"]] = relationship(
        back_populates="contract", order_by="ContractItem.ordinal", cascade="all, delete-orphan"
    )


class ContractItem(Base, TimestampMixin):
    """One teacher-authored exercise.

    `misconception_vocabulary` is a closed list for this item. The tutor may
    only diagnose from it, which is what makes a diagnosis validatable and
    legible to the teacher instead of free text.
    """

    __tablename__ = "contract_items"
    __table_args__ = (
        UniqueConstraint("contract_id", "ordinal", name="uq_item_ordinal"),
        _check("kind", ItemKind, "ck_item_kind"),
        # A short answer is marked against its expected answer; a written
        # response against its rubric. Each must have what it is marked with.
        CheckConstraint(
            "(kind = 'short_answer' and expected_answer is not null)"
            " or (kind = 'written_response' and rubric is not null)",
            name="ck_item_marking",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lesson_contracts.id", ondelete="CASCADE"), nullable=False
    )
    objective_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("objectives.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ItemKind.SHORT_ANSWER.value
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    # Written responses: {"criteria": [{"name", "max", "description"}]}.
    rubric: Mapped[dict | None] = mapped_column(Json)
    hint_templates: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    misconception_vocabulary: Mapped[list] = mapped_column(Json, nullable=False, default=list)

    contract: Mapped[LessonContract] = relationship(back_populates="items")


class Session(Base, TimestampMixin):
    """A lesson: one class taught with one version of a plan.

    It is `scheduled` until the teacher starts it, then timed. `phase_index`
    points into the plan version's `timeline`; students can use their tutor
    only while the current phase has tutors on.
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
    phase_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    phase_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
        Index("ix_evidence_student_objective", "student_id", "objective_id", "created_at"),
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
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_items.id", ondelete="SET NULL")
    )
    objective_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("objectives.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    correct: Mapped[bool | None] = mapped_column(Boolean)
    attempt_index: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    provenance: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TutorTurn(Base, TimestampMixin):
    """Audit trail for one model call, and the source of every feasibility
    metric in S5: policy compliance, answer leakage, latency and failures."""

    __tablename__ = "tutor_turns"
    __table_args__ = (
        _check("rung_permitted", Rung, "ck_turn_rung_permitted"),
        _check("validation_outcome", ValidationOutcome, "ck_turn_validation"),
        _check("leakage_check", LeakageCheck, "ck_turn_leakage"),
        Index("ix_turn_session", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_items.id", ondelete="CASCADE"), nullable=False
    )
    attempt_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_records.id", ondelete="SET NULL")
    )
    rung_permitted: Mapped[str] = mapped_column(String(32), nullable=False)
    rung_used: Mapped[str | None] = mapped_column(String(32))
    misconception_code: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
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
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_items.id", ondelete="SET NULL")
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


class RubricScore(Base, TimestampMixin):
    """A written response's mark: suggested by the AI, confirmed by the teacher.

    The suggestion and the confirmed mark are kept side by side, so the record
    shows both what the model proposed and what the teacher decided. Students
    see a score only once it is confirmed.
    """

    __tablename__ = "rubric_scores"
    __table_args__ = (
        _check("status", ScoreStatus, "ck_score_status"),
        UniqueConstraint("submission_record_id", name="uq_score_submission"),
        Index("ix_scores_session_status", "session_id", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_items.id", ondelete="CASCADE"), nullable=False
    )
    submission_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_records.id", ondelete="CASCADE"), nullable=False
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
