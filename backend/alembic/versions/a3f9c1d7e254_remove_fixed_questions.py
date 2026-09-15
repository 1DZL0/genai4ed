"""remove fixed questions: the class agent replaces items, ladders and phases

Revision ID: a3f9c1d7e254
Revises: e7a1c3b5d920
Create Date: 2026-09-16

The platform no longer has fixed questions, a per-item help ladder or lesson
phases. Their tables and columns go, and the audit and outcome tables are
renamed for what they now hold. Records of the removed kinds (attempts, hints,
drafts, the old alert kinds) are deleted; the teacher access log is kept whole.

Downgrading restores the old shape empty, not its data.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f9c1d7e254"
down_revision: Union[str, Sequence[str], None] = "e7a1c3b5d920"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())

EVIDENCE_NEW = ("assessment", "signal", "policy_event", "step_change", "teacher_guidance")
EVIDENCE_OLD = (
    "attempt",
    "grading_result",
    "hint",
    "teacher_feedback",
    "teacher_intervention",
    "exploratory_turn",
    "draft",
    "submission",
    "tutor_request",
    *EVIDENCE_NEW,
)
EXCEPTION_NEW = (
    "teacher_requested",
    "safeguarding",
    "struggling",
    "manipulation",
    "misconception_pattern",
    "unresolved_question",
    "off_task",
    "fast_progress",
)
EXCEPTION_OLD = (
    *EXCEPTION_NEW,
    "repeated_incorrect",
    "assistance_policy_conflict",
    "tutor_uncertainty",
    "stuck",
)
RUNGS = (
    "attempt",
    "diagnostic_question",
    "conceptual_cue",
    "targeted_hint",
    "analogous_example",
    "partial_step",
    "full_solution",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _recheck(table: str, name: str, column: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, f"{column} in ({_in(values)})")


def upgrade() -> None:
    op.execute(f"delete from evidence_records where kind not in ({_in(EVIDENCE_NEW)})")
    _recheck("evidence_records", "ck_evidence_kind", "kind", EVIDENCE_NEW)
    op.execute(f"delete from exceptions where kind not in ({_in(EXCEPTION_NEW)})")
    _recheck("exceptions", "ck_exception_kind", "kind", EXCEPTION_NEW)

    op.drop_index("ix_evidence_student_objective", table_name="evidence_records")
    for column in ("item_id", "objective_id", "correct", "attempt_index"):
        op.drop_column("evidence_records", column)
    op.create_index("ix_evidence_student", "evidence_records", ["student_id", "created_at"])
    op.drop_column("exceptions", "item_id")

    # Audit of model calls: fixed-question turns go, class agent turns stay.
    op.execute("delete from tutor_turns where mode is null")
    for column in (
        "item_id",
        "attempt_record_id",
        "rung_permitted",
        "rung_used",
        "misconception_code",
        "confidence",
    ):
        op.drop_column("tutor_turns", column)
    op.rename_table("tutor_turns", "agent_turns")

    # Outcomes: per-item scores go, per-lesson outcomes stay.
    op.execute("delete from rubric_scores where item_id is not null")
    op.drop_column("rubric_scores", "item_id")
    op.drop_column("rubric_scores", "submission_record_id")
    op.rename_table("rubric_scores", "lesson_outcomes")
    op.create_unique_constraint(
        "uq_outcome_student", "lesson_outcomes", ["session_id", "student_id"]
    )

    for column in ("class_id", "timeline", "assistance_ladder", "exception_thresholds", "material"):
        op.drop_column("lesson_contracts", column)
    op.drop_column("sessions", "phase_index")
    op.drop_column("sessions", "phase_started_at")

    op.drop_table("contract_items")
    op.drop_table("objectives")


def downgrade() -> None:
    op.create_table(
        "objectives",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_objective_code"),
    )
    op.create_table(
        "contract_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("contract_id", sa.UUID(), nullable=False),
        sa.Column("objective_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=True),
        sa.Column("rubric", JSONB, nullable=True),
        sa.Column("hint_templates", JSONB, nullable=False),
        sa.Column("misconception_vocabulary", JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.CheckConstraint(
            "(kind = 'short_answer' and expected_answer is not null)"
            " or (kind = 'written_response' and rubric is not null)",
            name="ck_item_marking",
        ),
        sa.CheckConstraint("kind in ('short_answer', 'written_response')", name="ck_item_kind"),
        sa.ForeignKeyConstraint(["contract_id"], ["lesson_contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["objective_id"], ["objectives.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_id", "ordinal", name="uq_item_ordinal"),
    )

    op.add_column(
        "sessions",
        sa.Column("phase_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "sessions", sa.Column("phase_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "lesson_contracts",
        sa.Column("class_id", sa.UUID(), sa.ForeignKey("classes.id", ondelete="SET NULL")),
    )
    for column, default in (
        ("timeline", "'[]'"),
        ("assistance_ladder", "'{}'"),
        ("exception_thresholds", "'{}'"),
        ("material", "'{}'"),
    ):
        op.add_column(
            "lesson_contracts",
            sa.Column(column, JSONB, nullable=False, server_default=sa.text(default)),
        )

    op.drop_constraint("uq_outcome_student", "lesson_outcomes", type_="unique")
    op.rename_table("lesson_outcomes", "rubric_scores")
    op.add_column(
        "rubric_scores",
        sa.Column("item_id", sa.UUID(), sa.ForeignKey("contract_items.id", ondelete="CASCADE")),
    )
    op.add_column(
        "rubric_scores",
        sa.Column(
            "submission_record_id",
            sa.UUID(),
            sa.ForeignKey("evidence_records.id", ondelete="CASCADE"),
        ),
    )
    op.create_unique_constraint("uq_score_submission", "rubric_scores", ["submission_record_id"])

    op.rename_table("agent_turns", "tutor_turns")
    op.add_column(
        "tutor_turns",
        sa.Column("item_id", sa.UUID(), sa.ForeignKey("contract_items.id", ondelete="CASCADE")),
    )
    op.add_column(
        "tutor_turns",
        sa.Column(
            "attempt_record_id",
            sa.UUID(),
            sa.ForeignKey("evidence_records.id", ondelete="SET NULL"),
        ),
    )
    op.add_column("tutor_turns", sa.Column("rung_permitted", sa.String(length=32)))
    op.add_column("tutor_turns", sa.Column("rung_used", sa.String(length=32)))
    op.add_column("tutor_turns", sa.Column("misconception_code", sa.String(length=64)))
    op.add_column("tutor_turns", sa.Column("confidence", sa.Float()))
    op.create_check_constraint(
        "ck_turn_rung_permitted", "tutor_turns", f"rung_permitted in ({_in(RUNGS)})"
    )

    op.add_column(
        "exceptions",
        sa.Column("item_id", sa.UUID(), sa.ForeignKey("contract_items.id", ondelete="SET NULL")),
    )
    op.drop_index("ix_evidence_student", table_name="evidence_records")
    op.add_column(
        "evidence_records",
        sa.Column("item_id", sa.UUID(), sa.ForeignKey("contract_items.id", ondelete="SET NULL")),
    )
    op.add_column(
        "evidence_records",
        sa.Column("objective_id", sa.UUID(), sa.ForeignKey("objectives.id", ondelete="SET NULL")),
    )
    op.add_column("evidence_records", sa.Column("correct", sa.Boolean()))
    op.add_column("evidence_records", sa.Column("attempt_index", sa.Integer()))
    op.create_index(
        "ix_evidence_student_objective",
        "evidence_records",
        ["student_id", "objective_id", "created_at"],
    )

    _recheck("exceptions", "ck_exception_kind", "kind", EXCEPTION_OLD)
    _recheck("evidence_records", "ck_evidence_kind", "kind", EVIDENCE_OLD)
