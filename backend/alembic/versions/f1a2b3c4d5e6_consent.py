"""consent on the enrolment, and two more things a teacher does to a student's record

Revision ID: f1a2b3c4d5e6
Revises: e5f7a9b1c3d5
Create Date: 2026-11-05

Research consent is recorded per student per class, by the teacher: unknown, given, withheld
or withdrawn. A student is taught the same whatever it says; only the study needs it given.
The access log gains the two actions that go with it: recording consent, and erasing a
student's records.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e5f7a9b1c3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_ACTIONS = ", ".join(
    f"'{a}'"
    for a in (
        "transcript_drilldown",
        "message_student",
        "pause_session",
        "resume_session",
        "close_session",
        "acknowledge_exception",
        "issue_join_codes",
        "schedule_lesson",
        "start_lesson",
        "change_phase",
        "review_student",
        "confirm_score",
        "guide_student",
        "ask_agent",
    )
)
NEW_ACTIONS = OLD_ACTIONS + ", 'record_consent', 'erase_student'"


def upgrade() -> None:
    op.add_column(
        "enrolments",
        sa.Column("consent", sa.String(length=16), nullable=False, server_default="unknown"),
    )
    op.add_column("enrolments", sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_enrolment_consent",
        "enrolments",
        "consent in ('unknown', 'given', 'withheld', 'withdrawn')",
    )
    op.drop_constraint("ck_access_action", "teacher_access_log", type_="check")
    op.create_check_constraint(
        "ck_access_action", "teacher_access_log", f"action in ({NEW_ACTIONS})"
    )


def downgrade() -> None:
    op.execute(
        "delete from teacher_access_log where action in ('record_consent', 'erase_student')"
    )
    op.drop_constraint("ck_access_action", "teacher_access_log", type_="check")
    op.create_check_constraint(
        "ck_access_action", "teacher_access_log", f"action in ({OLD_ACTIONS})"
    )
    op.drop_constraint("ck_enrolment_consent", "enrolments", type_="check")
    op.drop_column("enrolments", "consent_at")
    op.drop_column("enrolments", "consent")
