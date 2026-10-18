"""teaching approach: a tag on each lesson

Revision ID: e5f7a9b1c3d5
Revises: d4e6f8a0b2c4
Create Date: 2026-10-18

For a side-by-side comparison of two ways of teaching (direct instruction against guided
inquiry), a lesson can carry the approach it is taught by. Only a tag; the approach itself is
in the lesson's own rules and strategy, put there through the conversation.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f7a9b1c3d5"
down_revision: Union[str, Sequence[str], None] = "d4e6f8a0b2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lesson_contracts", sa.Column("approach", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("lesson_contracts", "approach")
