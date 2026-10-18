"""Demo sign-in: any username, any password, switched on by `DEMO_SIGN_IN`.

A new teacher gets an empty class, which their own students join, the sample lesson approved
and nothing running; a new student joins one teacher's class and running lessons, or
every class when no teacher is named.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import Role, SessionStatus
from app.models import Class, Enrolment, Session, SessionParticipant, User
from app.samples import add_sample_lessons


class NameTaken(Exception):
    """The name belongs to someone with the other role."""


async def demo_user(
    db: AsyncSession, username: str, role: Role, teacher: str | None = None
) -> User:
    """The user with this name, created on first use. The password is never checked."""
    user = await db.scalar(select(User).where(User.pseudonym == username))
    if user is not None:
        if user.role != role.value:
            raise NameTaken(user.role)
        return user

    user = User(pseudonym=username, role=role.value)
    db.add(user)
    await db.flush()

    if role is Role.TEACHER:
        # Empty: other teachers' students stay theirs. "New student of Teacher N" fills it.
        db.add(Class(teacher_id=user.id, label=f"{username}'s class"))
        await db.flush()
        await add_sample_lessons(db, user)
    else:
        classes = select(Class.id)
        if teacher:
            # A student of one teacher only, so two teachers trying the demo don't
            # see each other's students. The teacher is made if they don't exist yet.
            owner = await demo_user(db, teacher, Role.TEACHER)
            classes = classes.where(Class.teacher_id == owner.id)
        class_ids = (await db.scalars(classes)).all()
        db.add_all([Enrolment(class_id=c, student_id=user.id) for c in class_ids])
        # Booked lessons admit their class when they start, so only running ones here.
        session_ids = (
            await db.scalars(
                select(Session.id).where(
                    Session.class_id.in_(class_ids),
                    Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
                )
            )
        ).all()
        db.add_all([SessionParticipant(session_id=s, student_id=user.id) for s in session_ids])

    await db.commit()
    return user
