"""class agent: conversations, materials, learning state, briefs

Revision ID: e7a1c3b5d920
Revises: c4e8a2d6f913
Create Date: 2026-09-15

Additive. The fixed-question tables stay until the old code is removed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7a1c3b5d920"
down_revision: Union[str, Sequence[str], None] = "c4e8a2d6f913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())

EVIDENCE_OLD = (
    "'attempt', 'grading_result', 'hint', 'teacher_feedback', 'teacher_intervention', "
    "'exploratory_turn', 'draft', 'submission', 'tutor_request'"
)
EVIDENCE_ADDED = ("assessment", "signal", "policy_event", "step_change", "teacher_guidance")
EXCEPTION_OLD = (
    "'teacher_requested', 'repeated_incorrect', 'assistance_policy_conflict', "
    "'tutor_uncertainty', 'safeguarding', 'stuck'"
)
EXCEPTION_ADDED = (
    "struggling",
    "manipulation",
    "misconception_pattern",
    "unresolved_question",
    "off_task",
    "fast_progress",
)
ACTIONS_OLD = (
    "'transcript_drilldown', 'message_student', 'pause_session', 'resume_session', "
    "'close_session', 'acknowledge_exception', 'issue_join_codes', 'schedule_lesson', "
    "'start_lesson', 'change_phase', 'review_student', 'confirm_score'"
)
ACTIONS_ADDED = ("guide_student", "ask_agent")


def _with(old: str, added: tuple[str, ...]) -> str:
    return old + ", " + ", ".join(f"'{a}'" for a in added)


def _recheck(table: str, name: str, column: str, values: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, f"{column} in ({values})")


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "materials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("teacher_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_materials_plan", "materials", ["plan_id", "created_at"])

    op.create_table(
        "class_insights",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("items", JSONB, nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_insights_session", "class_insights", ["session_id", "created_at"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("teacher_id", sa.UUID(), nullable=True),
        sa.Column("student_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("plan_id", sa.UUID(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "(kind = 'student' and student_id is not null and session_id is not null)"
            " or (kind = 'design' and teacher_id is not null and plan_id is not null)"
            " or (kind = 'classroom' and teacher_id is not null and session_id is not null)",
            name="ck_conversation_owner",
        ),
        sa.CheckConstraint(
            "kind in ('design', 'classroom', 'student')", name="ck_conversation_kind"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "session_id", "student_id", name="uq_conversation_student"),
    )
    op.create_index("ix_conversations_plan", "conversations", ["plan_id"])

    op.create_table(
        "learning_states",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("attempts_on_step", sa.Integer(), nullable=False),
        sa.Column("struggle_turns", sa.Integer(), nullable=False),
        sa.Column("turns", sa.Integer(), nullable=False),
        sa.Column("steps", JSONB, nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "status in ('not_started', 'in_progress', 'completed')", name="ck_learning_status"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "student_id", name="uq_learning_state"),
    )

    op.add_column("tutor_turns", sa.Column("conversation_id", sa.UUID(), nullable=True))
    op.add_column("tutor_turns", sa.Column("mode", sa.String(length=16), nullable=True))
    op.add_column(
        "tutor_turns",
        sa.Column("context_manifest", JSONB, nullable=False, server_default=sa.text("'{}'")),
    )
    op.alter_column("tutor_turns", "context_manifest", server_default=None)
    for column in ("session_id", "student_id", "item_id"):
        op.alter_column("tutor_turns", column, existing_type=sa.UUID(), nullable=True)
    op.alter_column(
        "tutor_turns", "rung_permitted", existing_type=sa.String(length=32), nullable=True
    )
    op.create_foreign_key(
        "fk_turn_conversation",
        "tutor_turns",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("audience", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("material_ids", JSONB, nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=True),
        sa.Column("retention_class", sa.String(length=32), nullable=False),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.CheckConstraint("audience in ('all', 'teacher')", name="ck_message_audience"),
        sa.CheckConstraint(
            "retention_class in ('submitted_work', 'exploratory_chat')",
            name="ck_message_retention",
        ),
        sa.CheckConstraint(
            "role in ('teacher', 'student', 'agent', 'event')", name="ck_message_role"
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["turn_id"], ["tutor_turns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation", "messages", ["conversation_id", "created_at"])
    op.create_index("ix_messages_purge", "messages", ["purge_after"])

    op.add_column(
        "lesson_contracts",
        sa.Column("brief", JSONB, nullable=False, server_default=sa.text("'{}'")),
    )
    op.alter_column("lesson_contracts", "brief", server_default=None)
    op.add_column(
        "lesson_contracts",
        sa.Column("use_past_lessons", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("lesson_contracts", "use_past_lessons", server_default=None)

    for column in ("item_id", "submission_record_id"):
        op.alter_column("rubric_scores", column, existing_type=sa.UUID(), nullable=True)

    _recheck("evidence_records", "ck_evidence_kind", "kind", _with(EVIDENCE_OLD, EVIDENCE_ADDED))
    _recheck("exceptions", "ck_exception_kind", "kind", _with(EXCEPTION_OLD, EXCEPTION_ADDED))
    _recheck("teacher_access_log", "ck_access_action", "action", _with(ACTIONS_OLD, ACTIONS_ADDED))


def downgrade() -> None:
    op.execute(
        "delete from teacher_access_log where action in ("
        + ", ".join(f"'{a}'" for a in ACTIONS_ADDED)
        + ")"
    )
    _recheck("teacher_access_log", "ck_access_action", "action", ACTIONS_OLD)
    op.execute(
        "delete from exceptions where kind in ("
        + ", ".join(f"'{a}'" for a in EXCEPTION_ADDED)
        + ")"
    )
    _recheck("exceptions", "ck_exception_kind", "kind", EXCEPTION_OLD)
    op.execute(
        "delete from evidence_records where kind in ("
        + ", ".join(f"'{a}'" for a in EVIDENCE_ADDED)
        + ")"
    )
    _recheck("evidence_records", "ck_evidence_kind", "kind", EVIDENCE_OLD)

    op.execute("delete from rubric_scores where item_id is null or submission_record_id is null")
    for column in ("submission_record_id", "item_id"):
        op.alter_column("rubric_scores", column, existing_type=sa.UUID(), nullable=False)

    op.drop_column("lesson_contracts", "use_past_lessons")
    op.drop_column("lesson_contracts", "brief")

    op.drop_index("ix_messages_purge", table_name="messages")
    op.drop_index("ix_messages_conversation", table_name="messages")
    op.drop_table("messages")

    # Class agent turns have no item or rung, so they can't survive the old shape.
    op.execute("delete from tutor_turns where item_id is null or rung_permitted is null")
    op.drop_constraint("fk_turn_conversation", "tutor_turns", type_="foreignkey")
    op.alter_column(
        "tutor_turns", "rung_permitted", existing_type=sa.String(length=32), nullable=False
    )
    for column in ("item_id", "student_id", "session_id"):
        op.alter_column("tutor_turns", column, existing_type=sa.UUID(), nullable=False)
    op.drop_column("tutor_turns", "context_manifest")
    op.drop_column("tutor_turns", "mode")
    op.drop_column("tutor_turns", "conversation_id")

    op.drop_table("learning_states")
    op.drop_index("ix_conversations_plan", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_insights_session", table_name="class_insights")
    op.drop_table("class_insights")
    op.drop_index("ix_materials_plan", table_name="materials")
    op.drop_table("materials")
