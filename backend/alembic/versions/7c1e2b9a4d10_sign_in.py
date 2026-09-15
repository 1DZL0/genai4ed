"""sign in: teacher credentials, student join codes, server-side sessions

Revision ID: 7c1e2b9a4d10
Revises: 25d697f3e4ab
Create Date: 2026-09-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c1e2b9a4d10"
down_revision: Union[str, Sequence[str], None] = "25d697f3e4ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_ACTIONS = (
    "'transcript_drilldown', 'message_student', 'pause_session', 'resume_session', "
    "'close_session', 'acknowledge_exception'"
)
NEW_ACTIONS = OLD_ACTIONS + ", 'issue_join_codes'"


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("join_code_digest", sa.String(length=64), nullable=True))
    op.create_unique_constraint("users_email_key", "users", ["email"])
    op.create_unique_constraint("users_join_code_digest_key", "users", ["join_code_digest"])
    op.create_check_constraint(
        "ck_users_student_has_no_credentials",
        "users",
        "role = 'teacher' or (email is null and password_hash is null)",
    )
    op.create_check_constraint(
        "ck_users_teacher_has_no_join_code",
        "users",
        "role = 'student' or join_code_digest is null",
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index("ix_auth_sessions_user", "auth_sessions", ["user_id"], unique=False)

    op.drop_constraint("ck_access_action", "teacher_access_log", type_="check")
    op.create_check_constraint(
        "ck_access_action", "teacher_access_log", f"action in ({NEW_ACTIONS})"
    )


def downgrade() -> None:
    op.execute("delete from teacher_access_log where action = 'issue_join_codes'")
    op.drop_constraint("ck_access_action", "teacher_access_log", type_="check")
    op.create_check_constraint(
        "ck_access_action", "teacher_access_log", f"action in ({OLD_ACTIONS})"
    )

    op.drop_index("ix_auth_sessions_user", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_constraint("ck_users_teacher_has_no_join_code", "users", type_="check")
    op.drop_constraint("ck_users_student_has_no_credentials", "users", type_="check")
    op.drop_constraint("users_join_code_digest_key", "users", type_="unique")
    op.drop_constraint("users_email_key", "users", type_="unique")
    op.drop_column("users", "join_code_digest")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
