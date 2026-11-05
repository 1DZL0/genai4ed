"""what each model call cost, on the turn

Revision ID: a7b8c9d0e1f2
Revises: e5f7a9b1c3d5
Create Date: 2026-11-05

The provider reports prompt, completion and total tokens with every reply; until now they
were thrown away, so nobody could say what a lesson costs. Kept as JSON on the turn.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "e5f7a9b1c3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_turns",
        sa.Column("usage", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("agent_turns", "usage")
