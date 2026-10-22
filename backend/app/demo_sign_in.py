"""Demo sign-in: any username, any password, switched on by `DEMO_SIGN_IN`.

A new teacher gets an empty class, which their own students join, the sample lesson approved
and nothing running. A new student names a teacher and joins that teacher's class and the
lessons running for it; a returning student keeps their classes.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import Role, SessionStatus
from app.models import Class, Enrolment, Session, SessionParticipant, User
from app.samples import add_sample_lessons


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
