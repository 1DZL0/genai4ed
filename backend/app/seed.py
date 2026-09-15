"""Development seed.

A teacher with a sign-in, a small class with join codes, the sample lessons
approved, and the science lesson already running so a student has somewhere
to go.

    uv run python -m app.seed          # seed an empty database
    uv run python -m app.seed --reset  # wipe seeded data first

Pseudonyms only. No real name belongs in this database.
"""

import argparse
import asyncio

from sqlalchemy import select, text

from app.db import Base, get_engine, get_sessionmaker
from app.enums import Role
from app.models import Class, Enrolment, User
from app.samples import add_sample_lessons, start_lesson
from app.security import hash_password, join_code_digest, new_join_code, new_password

# A reserved .test domain, so the demo account can never be a real inbox.
# The password and the students' join codes are generated and printed once.
DEMO_TEACHER_EMAIL = "teacher-01@genai4ed.test"


async def _reset() -> None:
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with get_sessionmaker()() as db:
        await db.execute(text(f"truncate {tables} cascade"))
        await db.commit()


async def seed() -> None:
    async with get_sessionmaker()() as db:
        if await db.scalar(select(User.id).where(User.email == DEMO_TEACHER_EMAIL)):
            print("Database already seeded. Use --reset to wipe and re-seed.")
            return

        password = new_password()
        teacher = User(
            pseudonym="teacher-01",
            role=Role.TEACHER.value,
            email=DEMO_TEACHER_EMAIL,
            password_hash=hash_password(password),
        )
        codes = {f"10B-{i:02d}": new_join_code() for i in (1, 2, 3)}
        students = [
            User(pseudonym=p, role=Role.STUDENT.value, join_code_digest=join_code_digest(code))
            for p, code in codes.items()
        ]
        db.add_all([teacher, *students])
        await db.flush()

        klass = Class(teacher_id=teacher.id, label="10B")
        db.add(klass)
        await db.flush()
        db.add_all([Enrolment(class_id=klass.id, student_id=s.id) for s in students])

        lessons = await add_sample_lessons(db, teacher)
        running = await start_lesson(db, lessons[0], klass, students)
        await db.commit()

        print("Seeded:")
        print(f"  teacher   {teacher.pseudonym}  sign in as {DEMO_TEACHER_EMAIL} / {password}")
        for pseudonym, code in codes.items():
            print(f"  student   {pseudonym}  join code {code}")
        for lesson in lessons:
            print(f"  lesson    {lesson.title} (approved)")
        print(f"  running   {lessons[0].title} for 10B, closes {running.closes_at:%H:%M UTC}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the development database.")
    parser.add_argument("--reset", action="store_true", help="truncate every table before seeding")
    args = parser.parse_args()
    if args.reset:
        await _reset()
    await seed()
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
