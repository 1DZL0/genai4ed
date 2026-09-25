"""Create and manage teacher accounts from the command line (`python -m app.accounts --help`).
There is no sign-up page on purpose. A new password is printed once and signs the teacher out."""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.auth import revoke_sign_ins
from app.db import get_engine, get_sessionmaker
from app.enums import Role
from app.models import User
from app.security import MIN_PASSWORD_LENGTH, hash_password, new_password, normalise_email


async def upsert_teacher(
    email: str, pseudonym: str | None, password: str | None, reset_password: bool
) -> int:
    email = normalise_email(email)
    if password is not None and len(password) < MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        return 1

    async with get_sessionmaker()() as db:
        by_email = await db.scalar(select(User).where(User.email == email))
        by_pseudonym = (
            await db.scalar(select(User).where(User.pseudonym == pseudonym)) if pseudonym else None
        )

        if by_email and by_pseudonym and by_email.id != by_pseudonym.id:
            print(f"{email} already belongs to {by_email.pseudonym}.", file=sys.stderr)
            return 1
        if by_pseudonym is not None and by_pseudonym.role != Role.TEACHER.value:
            print(f"{pseudonym} is a student, not a teacher.", file=sys.stderr)
            return 1

        user = by_email or by_pseudonym
        created = user is None
        if created:
            user = User(
                pseudonym=pseudonym or await _next_teacher_pseudonym(db),
                role=Role.TEACHER.value,
            )
            db.add(user)
        user.email = email

        issued = None
        if created or reset_password or password is not None or user.password_hash is None:
            issued = password or new_password()
            user.password_hash = hash_password(issued)
            await db.flush()
            await revoke_sign_ins(db, [user.id])

        await db.commit()

        print(f"{'Created' if created else 'Updated'} teacher {user.pseudonym} <{email}>")
        if issued and password is None:
            print(f"  password: {issued}")
            print("  Shown once. Pass it on privately.")
        elif issued is None:
            print("  password unchanged (use --reset-password for a new one)")
    return 0


async def _next_teacher_pseudonym(db) -> str:
    taken = set((await db.scalars(select(User.pseudonym))).all())
    n = 1
    while f"teacher-{n:02d}" in taken:
        n += 1
    return f"teacher-{n:02d}"


async def list_teachers() -> int:
    async with get_sessionmaker()() as db:
        teachers = (
            await db.scalars(
                select(User).where(User.role == Role.TEACHER.value).order_by(User.pseudonym)
            )
        ).all()
    for t in teachers:
        state = "can sign in" if t.password_hash else "no password yet"
        print(f"{t.pseudonym:<14} {t.email or '(no email)':<36} {state}")
    if not teachers:
        print("No teachers.")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="Manage teacher accounts.")
    commands = parser.add_subparsers(dest="command", required=True)

    teacher = commands.add_parser("teacher", help="create a teacher, or update one")
    teacher.add_argument("--email", required=True)
    teacher.add_argument(
        "--pseudonym", help="attach the email to this existing teacher, or name a new one"
    )
    teacher.add_argument("--password", help="set this password instead of generating one")
    teacher.add_argument("--reset-password", action="store_true", help="generate a new password")

    commands.add_parser("list", help="list teachers")

    args = parser.parse_args()
    try:
        if args.command == "teacher":
            return await upsert_teacher(
                args.email, args.pseudonym, args.password, args.reset_password
            )
        return await list_teachers()
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
