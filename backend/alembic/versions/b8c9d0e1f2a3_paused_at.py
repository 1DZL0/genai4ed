"""when a lesson was paused, so a pause stops its clock

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-08

Until now pausing a lesson closed the pupils' boxes but the clock ran on, so a class paused
for ten minutes came back with ten fewer. The moment of the pause is kept; carrying on moves
the deadline later by however long the pause lasted.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "paused_at")
