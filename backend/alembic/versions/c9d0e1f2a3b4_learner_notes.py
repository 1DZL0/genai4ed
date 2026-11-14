"""the learner note: what a student's next lessons are told about them

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-14

Until now nothing about a student was kept between lessons except the record itself, read
again each time. The note is one short text per student in two parts: how they learn, and
what they know a subject at a time. Every change is a new row, so the highest version is the
note and the earlier ones show how it got there. It goes when the student does.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "learner_notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("worked_out", _json(), nullable=False),
        sa.Column("written", _json(), nullable=False),
        sa.Column("knows", _json(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "version", name="uq_learner_note_version"),
    )


def downgrade() -> None:
    op.drop_table("learner_notes")
