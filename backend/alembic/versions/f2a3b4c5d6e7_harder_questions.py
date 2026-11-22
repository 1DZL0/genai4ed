"""harder questions

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-16

A teacher's switch for the tutor's harder follow-up questions, off for everyone until they turn
it on, and a kind of evidence for a pupil's one try at such a question, kept apart from the
judgments of the lesson's own steps.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = "'assessment', 'signal', 'policy_event', 'step_change', 'teacher_guidance'"


def _recheck(values: str) -> None:
    op.drop_constraint("ck_evidence_kind", "evidence_records", type_="check")
    op.create_check_constraint("ck_evidence_kind", "evidence_records", f"kind in ({values})")


def upgrade() -> None:
    op.add_column(
        "memory_settings",
        sa.Column("harder_questions", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _recheck(f"{_BEFORE}, 'harder_question'")


def downgrade() -> None:
    op.execute("delete from evidence_records where kind = 'harder_question'")
    _recheck(_BEFORE)
    op.drop_column("memory_settings", "harder_questions")
