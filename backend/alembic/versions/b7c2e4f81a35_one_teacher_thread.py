"""one teacher thread: the teacher's whole interface is a single conversation

Revision ID: b7c2e4f81a35
Revises: a3f9c1d7e254
Create Date: 2026-09-16

A teacher had a design conversation per lesson and a classroom conversation per
running lesson. They now have one thread for everything: making a lesson,
running it, asking about a class. Student conversations are unchanged.

The old threads are deleted rather than merged - their messages were a record of
a screen that no longer exists, and merging several of them would invent an
order they never had. Judgments, signals and every other piece of evidence live
in `evidence_records` and are untouched; so are the students' own conversations.

Downgrading restores the old kinds; the old threads do not come back.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b7c2e4f81a35"
down_revision: Union[str, Sequence[str], None] = "a3f9c1d7e254"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OWNER_NEW = (
    "(kind = 'student' and student_id is not null and session_id is not null)"
    " or (kind = 'teacher' and teacher_id is not null)"
)
OWNER_OLD = (
    "(kind = 'student' and student_id is not null and session_id is not null)"
    " or (kind = 'design' and teacher_id is not null and plan_id is not null)"
    " or (kind = 'classroom' and teacher_id is not null and session_id is not null)"
)


def upgrade() -> None:
    # Messages and agent turns cascade from the conversation.
    op.execute("delete from conversations where kind in ('design', 'classroom')")
    op.drop_constraint("ck_conversation_kind", "conversations", type_="check")
    op.drop_constraint("ck_conversation_owner", "conversations", type_="check")
    op.create_check_constraint(
        "ck_conversation_kind", "conversations", "kind in ('teacher', 'student')"
    )
    op.create_check_constraint("ck_conversation_owner", "conversations", OWNER_NEW)
    op.create_unique_constraint(
        "uq_conversation_teacher", "conversations", ["kind", "teacher_id"]
    )
    op.execute("update agent_turns set mode = 'teacher' where mode in ('design', 'classroom')")


def downgrade() -> None:
    op.drop_constraint("uq_conversation_teacher", "conversations", type_="unique")
    op.drop_constraint("ck_conversation_kind", "conversations", type_="check")
    op.drop_constraint("ck_conversation_owner", "conversations", type_="check")
    op.execute("delete from conversations where kind = 'teacher'")
    op.create_check_constraint(
        "ck_conversation_kind", "conversations", "kind in ('design', 'classroom', 'student')"
    )
    op.create_check_constraint("ck_conversation_owner", "conversations", OWNER_OLD)
