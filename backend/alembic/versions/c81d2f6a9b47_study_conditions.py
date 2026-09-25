"""study conditions: what each student was assigned, and a queue kind for held-back replies

Revision ID: c81d2f6a9b47
Revises: 5e00da793122
Create Date: 2026-09-20

A study needs to know, for every student in every lesson, which condition they
were in. It is kept on the participant row - the unit a condition is assigned
to - and copied onto each turn's manifest, so an export never has to guess.

`policy_conflict` lets a reply the platform held back reach the teacher's queue
(concept note S2: "assistance-policy conflicts" are one of the routed events).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c81d2f6a9b47"
down_revision: Union[str, Sequence[str], None] = "5e00da793122"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KINDS = (
    "teacher_requested",
    "safeguarding",
    "struggling",
    "manipulation",
    "misconception_pattern",
    "unresolved_question",
    "off_task",
    "fast_progress",
)


def _kinds(values) -> str:
    return "kind in (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column(
        "session_participants",
        sa.Column(
            "condition",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )
    op.alter_column("session_participants", "condition", server_default=None)
    op.drop_constraint("ck_exception_kind", "exceptions", type_="check")
    op.create_check_constraint(
        "ck_exception_kind", "exceptions", _kinds((*KINDS, "policy_conflict"))
    )


def downgrade() -> None:
    op.execute("delete from exceptions where kind = 'policy_conflict'")
    op.drop_constraint("ck_exception_kind", "exceptions", type_="check")
    op.create_check_constraint("ck_exception_kind", "exceptions", _kinds(KINDS))
    op.drop_column("session_participants", "condition")
