"""Trying the platform without real accounts: the sample lesson, the development seed
(`python -m app.demo [--reset]`) and demo sign-in (any username, any password, switched on
by `DEMO_SIGN_IN`). Pseudonyms only.

Under demo sign-in a new teacher gets an empty class, which their own students join, the
sample lesson approved and nothing running. A new student names a teacher and joins that
teacher's class and the lessons running for it; a returning student keeps their classes.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.brief import LessonBrief
from app.db import Base, get_engine, get_sessionmaker
from app.enums import ContractStatus, Role, SessionStatus
from app.models import Class, Enrolment, LessonContract, Session, SessionParticipant, User
from app.security import hash_password, join_code_digest, new_join_code, new_password

# ---------- the sample lesson ----------

MATHS = LessonBrief.model_validate(
    {
        "title": "Linear equations: unknown on both sides",
        "subject": "mathematics",
        "year_group": "Year 10",
        "duration_minutes": 20,
        "prior_knowledge": "One-step and two-step equations.",
        "objectives": ["Solve equations with the unknown on both sides, showing working"],
        "strategy": "Ask for their first step before anything else. Keep the equation balanced.",
        "steps": [
            {
                "name": "Warm up",
                "kind": "question",
                "goal": "Solve 3x + 4 = 19",
                "prompt_ideas": ["Solve 3x + 4 = 19. What's your first step?"],
                "success_criteria": ["x = 5 with a correct method"],
                "reference_answer": "5",
            },
            {
                "name": "Both sides",
                "kind": "practice",
                "goal": "Solve 5x - 7 = 2x + 8",
                "prompt_ideas": ["Solve 5x - 7 = 2x + 8."],
                "success_criteria": ["Collects x terms on one side; x = 5"],
                "reference_answer": "5",
            },
            {
                "name": "Brackets",
                "kind": "check",
                "goal": "Solve 2(x + 3) = 4x - 2",
                "prompt_ideas": ["Solve 2(x + 3) = 4x - 2."],
                "success_criteria": ["Expands fully; x = 4"],
                "reference_answer": "4",
            },
        ],
        "assessment": [{"name": "Method", "max": 3}, {"name": "Accuracy", "max": 3}],
        "rules_text": "Show worked steps after one try, never just give the final value.",
        "rules": {
            "hints_allowed": True,
            "partial_after_attempts": 1,
            "full_answer_after_attempts": None,
            "may_write_for_student": False,
            "escalations": [],
            "notes": [],
        },
        "topics": ["linear equations", "algebra"],
    }
)

SAMPLES = (MATHS,)


async def add_sample_lessons(db: AsyncSession, teacher: User) -> list[LessonContract]:
    """The sample lesson, approved. The caller commits."""
    now = datetime.now(UTC)
    contracts = [
        LessonContract(
            teacher_id=teacher.id,
            title=brief.title,
            subject=brief.subject,
            status=ContractStatus.ACTIVE.value,
            version=1,
            brief=brief.model_dump(mode="json"),
            activated_at=now,
            activated_by=teacher.id,
        )
        for brief in SAMPLES
    ]
    db.add_all(contracts)
    await db.flush()
    return contracts


async def start_lesson(
    db: AsyncSession, contract: LessonContract, klass: Class, students: list[User]
) -> Session:
    """A lesson already running for a class, so students have somewhere to go."""
    now = datetime.now(UTC)
    brief = LessonBrief.model_validate(contract.brief or {})
    session = Session(
        contract_id=contract.id,
        class_id=klass.id,
        status=SessionStatus.OPEN.value,
        opened_at=now,
        closes_at=now + timedelta(minutes=brief.duration_minutes),
    )
    db.add(session)
    await db.flush()
    db.add_all([SessionParticipant(session_id=session.id, student_id=s.id) for s in students])
    await db.flush()
    return session


# ---------- demo sign-in ----------


class NameTaken(Exception):
    """The name belongs to someone with the other role."""


class NotATeacher(Exception):
    """The teacher a student named is a student."""


class NoSuchTeacher(Exception):
    """Nobody teaches under the name a student typed."""


class NeedsTeacher(Exception):
    """A new student named no teacher, so there is no class for them to join."""


# The demo's shared teachers, made the first time a student names one (the "New student of
# Teacher N" buttons). Any other teacher signs in first; a mistyped name is refused rather
# than made into an empty teacher.
STANDING_TEACHERS = ("teacher-1", "teacher-2", "teacher-3")


async def demo_user(
    db: AsyncSession, username: str, role: Role, teacher: str | None = None
) -> User:
    """The user with this name, created on first use. The password is never checked."""
    teacher = (teacher or "").strip() or None
    if role is Role.STUDENT and username.lower() in STANDING_TEACHERS:
        # Kept for the teachers: a student called teacher-1 would block "New student of
        # Teacher 1" for everyone.
        raise NameTaken(Role.TEACHER.value)
    user = await db.scalar(select(User).where(User.pseudonym == username))
    if user is not None:
        if user.role != role.value:
            raise NameTaken(user.role)
        if role is Role.STUDENT and teacher:
            # Signing in again under another teacher puts them in that class too; with no
            # teacher named they keep the classes they have.
            await _join(db, user, await _teacher(db, teacher))
            await db.commit()
        return user

    # A student of one teacher only, so two teachers trying the demo don't see each other's
    # students: a new one must say whose class they are joining.
    owner = None
    if role is Role.STUDENT:
        if not teacher:
            raise NeedsTeacher()
        owner = await _teacher(db, teacher)

    user = User(pseudonym=username, role=role.value)
    db.add(user)
    await db.flush()

    if role is Role.TEACHER:
        # Empty: other teachers' students stay theirs. "New student of Teacher N" fills it.
        # The label column holds 64 characters, and "'s class" takes 8 of them.
        db.add(Class(teacher_id=user.id, label=f"{username[:56]}'s class"))
        await db.flush()
        await add_sample_lessons(db, user)
    else:
        await _join(db, user, owner)

    await db.commit()
    return user


async def _teacher(db: AsyncSession, name: str) -> User:
    """The teacher a student named, whatever the case of the letters: the exact name first,
    then any teacher spelt the same. One of the standing demo teachers is made if they don't
    exist yet; a name that is only a student's is refused as not a teacher."""
    teachers = select(User).where(User.role == Role.TEACHER.value)
    owner = await db.scalar(teachers.where(User.pseudonym == name))
    if owner is None:
        owner = await db.scalar(
            teachers.where(func.lower(User.pseudonym) == name.lower()).order_by(User.created_at)
        )
    if owner is None:
        if await db.scalar(select(User.id).where(func.lower(User.pseudonym) == name.lower())):
            raise NotATeacher(name)
        if name.lower() not in STANDING_TEACHERS:
            raise NoSuchTeacher(name)
        owner = await demo_user(db, name.lower(), Role.TEACHER)
    return owner


async def _join(db: AsyncSession, student: User, owner: User) -> None:
    """Into the teacher's classes, and the lessons running for them now."""
    class_ids = (await db.scalars(select(Class.id).where(Class.teacher_id == owner.id))).all()
    have = set(
        (
            await db.scalars(select(Enrolment.class_id).where(Enrolment.student_id == student.id))
        ).all()
    )
    db.add_all([Enrolment(class_id=c, student_id=student.id) for c in class_ids if c not in have])
    # Booked lessons admit their class when they start, so only running ones here.
    running = (
        await db.scalars(
            select(Session.id).where(
                Session.class_id.in_(class_ids),
                Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            )
        )
    ).all()
    joined = set(
        (
            await db.scalars(
                select(SessionParticipant.session_id).where(
                    SessionParticipant.student_id == student.id
                )
            )
        ).all()
    )
    db.add_all(
        [
            SessionParticipant(session_id=s, student_id=student.id)
            for s in running
            if s not in joined
        ]
    )
    await db.flush()


# ---------- the development seed ----------


# A reserved .test domain, so the demo account can never be a real inbox.
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
