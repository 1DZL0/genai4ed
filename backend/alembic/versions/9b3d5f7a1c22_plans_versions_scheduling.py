"""plans become reusable and versioned; lessons are scheduled and have phases

Revision ID: 9b3d5f7a1c22
Revises: 7c1e2b9a4d10
Create Date: 2026-09-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9b3d5f7a1c22"
down_revision: Union[str, Sequence[str], None] = "7c1e2b9a4d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_SESSION = "'open', 'paused', 'closed'"
NEW_SESSION = "'scheduled', 'open', 'paused', 'closed'"
OLD_ACTIONS = (
    "'transcript_drilldown', 'message_student', 'pause_session', 'resume_session', "
    "'close_session', 'acknowledge_exception', 'issue_join_codes'"
)
NEW_ACTIONS = OLD_ACTIONS + ", 'schedule_lesson', 'start_lesson', 'change_phase', 'review_student'"


def upgrade() -> None:
    # Plans: a lineage id shared by every version, no fixed class, a timeline, archiving.
    op.add_column("lesson_contracts", sa.Column("plan_id", sa.UUID(), nullable=True))
    op.execute("update lesson_contracts set plan_id = id")
    op.alter_column("lesson_contracts", "plan_id", nullable=False)
    op.create_index("ix_lesson_contracts_plan_id", "lesson_contracts", ["plan_id"])
    op.create_unique_constraint("uq_plan_version", "lesson_contracts", ["plan_id", "version"])
    op.add_column(
        "lesson_contracts",
        sa.Column(
            "timeline",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("lesson_contracts", "timeline", server_default=None)
    op.add_column(
        "lesson_contracts", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column("lesson_contracts", "class_id", nullable=True)
    op.drop_constraint("lesson_contracts_class_id_fkey", "lesson_contracts", type_="foreignkey")
    op.create_foreign_key(
        "lesson_contracts_class_id_fkey",
        "lesson_contracts",
        "classes",
        ["class_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Lessons: scheduled before they start, timed from the start, moving through phases.
    op.drop_constraint("ck_session_status", "sessions", type_="check")
    op.create_check_constraint("ck_session_status", "sessions", f"status in ({NEW_SESSION})")
    op.add_column("sessions", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("phase_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("sessions", "phase_index", server_default=None)
    op.add_column(
        "sessions", sa.Column("phase_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column("sessions", "opened_at", nullable=True, server_default=None)
    op.alter_column("sessions", "closes_at", nullable=True)

    op.drop_constraint("ck_access_action", "teacher_access_log", type_="check")
    op.create_check_constraint(
        "ck_access_action", "teacher_access_log", f"action in ({NEW_ACTIONS})"
    )


def downgrade() -> None:
    op.execute(
        "delete from teacher_access_log where action in "
        "('schedule_lesson', 'start_lesson', 'change_phase', 'review_student')"
    )
    op.drop_constraint("ck_access_action", "teacher_access_log", type_="check")
    op.create_check_constraint(
        "ck_access_action", "teacher_access_log", f"action in ({OLD_ACTIONS})"
    )

    # Scheduled lessons that never ran have no earlier representation.
    op.execute("delete from sessions where status = 'scheduled'")
    op.execute("update sessions set opened_at = coalesce(opened_at, created_at)")
    op.execute("update sessions set closes_at = coalesce(closes_at, opened_at)")
    op.alter_column("sessions", "closes_at", nullable=False)
    op.alter_column("sessions", "opened_at", nullable=False, server_default=sa.text("now()"))
    op.drop_column("sessions", "phase_started_at")
    op.drop_column("sessions", "phase_index")
    op.drop_column("sessions", "scheduled_for")
    op.drop_constraint("ck_session_status", "sessions", type_="check")
    op.create_check_constraint("ck_session_status", "sessions", f"status in ({OLD_SESSION})")

    op.drop_constraint("lesson_contracts_class_id_fkey", "lesson_contracts", type_="foreignkey")
    # A plan needs a class again: give class-less plans the class of their first lesson.
    op.execute(
        "update lesson_contracts c set class_id = s.class_id from sessions s "
        "where c.class_id is null and s.contract_id = c.id"
    )
    op.execute("delete from lesson_contracts where class_id is null")
    op.create_foreign_key(
        "lesson_contracts_class_id_fkey",
        "lesson_contracts",
        "classes",
        ["class_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("lesson_contracts", "class_id", nullable=False)
    op.drop_column("lesson_contracts", "archived_at")
    op.drop_column("lesson_contracts", "timeline")
    op.drop_constraint("uq_plan_version", "lesson_contracts", type_="unique")
    op.drop_index("ix_lesson_contracts_plan_id", table_name="lesson_contracts")
    op.drop_column("lesson_contracts", "plan_id")
