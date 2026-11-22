"""memory settings a teacher can change, and when a student's memory was last deleted

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-16

Memory between lessons was always on, and all of it. A teacher can now set, for their own
lessons, whether the tutor is told anything from before, how many days back, whether the lines
a model wrote are among them, and whether the end of the last lesson is repeated word for word.
A teacher who has set nothing has no row and memory is as it was.

Deleting what is remembered of a student keeps the moment in memory_starts, so nothing from
before it is counted or recalled again. The lessons themselves stay in the record.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_settings",
        sa.Column("teacher_id", sa.UUID(), nullable=False),
        sa.Column("remember", sa.Boolean(), nullable=False),
        sa.Column("forget_after_days", sa.Integer(), nullable=True),
        sa.Column("written_lines", sa.Boolean(), nullable=False),
        sa.Column("recent_lines", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "forget_after_days is null or forget_after_days between 1 and 365",
            name="ck_memory_settings_forget_after_days",
        ),
        sa.CheckConstraint("recent_lines between 0 and 20", name="ck_memory_settings_recent_lines"),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("teacher_id"),
    )
    op.create_table(
        "memory_starts",
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("student_id"),
    )


def downgrade() -> None:
    op.drop_table("memory_starts")
    op.drop_table("memory_settings")
