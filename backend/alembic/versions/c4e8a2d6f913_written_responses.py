"""written responses: task kinds, rubric-marked work, AI-suggested scores

Revision ID: c4e8a2d6f913
Revises: 9b3d5f7a1c22
Create Date: 2026-09-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e8a2d6f913"
down_revision: Union[str, Sequence[str], None] = "9b3d5f7a1c22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVIDENCE_OLD = (
    "'attempt', 'grading_result', 'hint', 'teacher_feedback', 'teacher_intervention', "
    "'exploratory_turn'"
)
EVIDENCE_NEW = EVIDENCE_OLD + ", 'draft', 'submission', 'tutor_request'"
EXCEPTION_OLD = (
    "'teacher_requested', 'repeated_incorrect', 'assistance_policy_conflict', "
    "'tutor_uncertainty', 'safeguarding'"
)
EXCEPTION_NEW = EXCEPTION_OLD + ", 'stuck'"
ACTIONS_OLD = (
    "'transcript_drilldown', 'message_student', 'pause_session', 'resume_session', "
    "'close_session', 'acknowledge_exception', 'issue_join_codes', 'schedule_lesson', "
    "'start_lesson', 'change_phase', 'review_student'"
)
ACTIONS_NEW = ACTIONS_OLD + ", 'confirm_score'"


def _recheck(table: str, name: str, column: str, values: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, f"{column} in ({values})")


def upgrade() -> None:
    op.add_column(
        "contract_items",
        sa.Column("kind", sa.String(length=24), nullable=False, server_default="short_answer"),
    )
    op.alter_column("contract_items", "kind", server_default=None)
    op.alter_column("contract_items", "expected_answer", nullable=True)
    op.create_check_constraint(
        "ck_item_kind", "contract_items", "kind in ('short_answer', 'written_response')"
    )
    op.create_check_constraint(
        "ck_item_marking",
        "contract_items",
        "(kind = 'short_answer' and expected_answer is not null)"
        " or (kind = 'written_response' and rubric is not null)",
    )

    _recheck("evidence_records", "ck_evidence_kind", "kind", EVIDENCE_NEW)
    _recheck("exceptions", "ck_exception_kind", "kind", EXCEPTION_NEW)
    _recheck("teacher_access_log", "ck_access_action", "action", ACTIONS_NEW)

    op.create_table(
        "rubric_scores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("submission_record_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("suggested", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("suggested_total", sa.Integer(), nullable=False),
        sa.Column("confirmed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confirmed_total", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.UUID(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("status in ('suggested', 'confirmed')", name="ck_score_status"),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["contract_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["submission_record_id"], ["evidence_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_record_id", name="uq_score_submission"),
    )
    op.create_index("ix_scores_session_status", "rubric_scores", ["session_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_scores_session_status", table_name="rubric_scores")
    op.drop_table("rubric_scores")

    op.execute("delete from teacher_access_log where action = 'confirm_score'")
    _recheck("teacher_access_log", "ck_access_action", "action", ACTIONS_OLD)
    op.execute("delete from exceptions where kind = 'stuck'")
    _recheck("exceptions", "ck_exception_kind", "kind", EXCEPTION_OLD)
    op.execute("delete from evidence_records where kind in ('draft', 'submission', 'tutor_request')")
    _recheck("evidence_records", "ck_evidence_kind", "kind", EVIDENCE_OLD)

    op.drop_constraint("ck_item_marking", "contract_items", type_="check")
    op.drop_constraint("ck_item_kind", "contract_items", type_="check")
    # Written responses have no expected answer; they cannot exist before this revision.
    op.execute("delete from contract_items where kind = 'written_response'")
    op.alter_column("contract_items", "expected_answer", nullable=False)
    op.drop_column("contract_items", "kind")
