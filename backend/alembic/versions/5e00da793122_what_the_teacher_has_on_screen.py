"""what the teacher has on screen

Revision ID: 5e00da793122
Revises: b7c2e4f81a35
Create Date: 2026-09-16

The teacher's thread is the conversation; the card they are looking at sits
beside it rather than in it. This remembers which record that card is built
from, so closing the tab and coming back puts them where they were. The card
itself is never stored - it is rebuilt from records every time.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5e00da793122"
down_revision: Union[str, Sequence[str], None] = "b7c2e4f81a35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "showing",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "showing")
