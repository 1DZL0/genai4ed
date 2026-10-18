"""units: a name on each lesson

Revision ID: d4e6f8a0b2c4
Revises: c81d2f6a9b47
Create Date: 2026-10-18

A unit is a run of lessons a teacher keeps under one name. For now it is only
the name, held on every version of the lesson, so the teacher's list can show
lessons by unit. Nothing else hangs off it yet.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e6f8a0b2c4"
down_revision: Union[str, Sequence[str], None] = "c81d2f6a9b47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson_contracts", sa.Column("unit", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("lesson_contracts", "unit")
