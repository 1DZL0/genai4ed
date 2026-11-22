"""adapt to student

Revision ID: a4b5c6d7e8f9
Revises: f2a3b4c5d6e7
Create Date: 2026-11-21

A teacher's switch for letting the tutor pitch each step for the student in front of it, off for
everyone until they turn it on.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_settings",
        sa.Column("adapt_to_student", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("memory_settings", "adapt_to_student")
