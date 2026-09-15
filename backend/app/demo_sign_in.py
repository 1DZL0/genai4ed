"""Demo sign-in: any username, any password.

For trying the platform out, while real accounts are not needed yet. Switched
on by `DEMO_SIGN_IN`; with it off, none of this is reachable.

Everyone in demo mode shares one open world, so two browsers can play teacher
and student without any setup:

* A new teacher gets their own class and a copy of the sample lesson with a
  session already running. Every existing student is put in that class.
* A new student is put in every class and every session still running.
* A name that already exists signs in as that person. The password is not
  checked - that is what "demo" means here.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import Role, SessionStatus
from app.models import Class, Enrolment, Session, SessionParticipant, User
from app.seed import add_sample_lesson


class NameTaken(Exception):
    """The name belongs to someone with the other role."""


async def demo_user(db: AsyncSession, username: str, role: Role) -> User:
    user = await db.scalar(select(User).where(User.pseudonym == username))
    if user is not None:
        if user.role != role.value:
            raise NameTaken(user.role)
        return user

    user = User(pseudonym=username, role=role.value)
    db.add(user)
    await db.flush()

    if role is Role.TEACHER:
        students = list(
            (await db.scalars(select(User).where(User.role == Role.STUDENT.value))).all()
        )
        klass = Class(teacher_id=user.id, label=f"{username}'s class")
        db.add(klass)
        await db.flush()
        db.add_all([Enrolment(class_id=klass.id, student_id=s.id) for s in students])
        await add_sample_lesson(db, user, klass, students)
    else:
        class_ids = (await db.scalars(select(Class.id))).all()
        db.add_all([Enrolment(class_id=c, student_id=user.id) for c in class_ids])
        session_ids = (
            await db.scalars(
                select(Session.id).where(Session.status != SessionStatus.CLOSED.value)
            )
        ).all()
        db.add_all([SessionParticipant(session_id=s, student_id=user.id) for s in session_ids])

    await db.commit()
    return user
