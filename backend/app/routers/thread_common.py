"""What every handler on the teacher's thread needs: the lesson in focus, a lesson the
teacher owns, the access log, and a few small checks."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.agent import store, thread
from app.enums import (
    TeacherAction,
)
from app.models import (
    LessonContract,
    Session,
    SessionParticipant,
    TeacherAccessLog,
    User,
)


def log_access(
    db, teacher: User, action: TeacherAction, session_id=None, student_id=None, detail=None
):
    db.add(
        TeacherAccessLog(
            teacher_id=teacher.id,
            session_id=session_id,
            student_id=student_id,
            action=action.value,
            detail=detail or {},
        )
    )


async def current_focus(db, teacher: User) -> thread.Focus:
    conversation = await store.teacher_thread(db, teacher_id=teacher.id)
    return await thread.focus_of(db, conversation, teacher)


async def owned_lesson(db, teacher: User, lesson_id: uuid.UUID) -> LessonContract:
    lesson = await db.get(LessonContract, lesson_id)
    if lesson is None or lesson.teacher_id != teacher.id or lesson.archived_at is not None:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    return lesson


async def versions_of(db, plan_id: uuid.UUID) -> list[LessonContract]:
    return list(
        (
            await db.scalars(
                select(LessonContract)
                .where(LessonContract.plan_id == plan_id)
                .order_by(LessonContract.version)
            )
        ).all()
    )


def need(value, what: str):
    if value is None:
        raise HTTPException(status_code=422, detail=f"{what} is needed for that.")
    return value


async def mark_focus(db, teacher, *, lesson_id=None, session_id=None):
    """A blank event saying what the teacher turned to, only when it changes."""
    focus = await current_focus(db, teacher)
    same_lesson = lesson_id and focus.lesson is not None and str(focus.lesson.id) == lesson_id
    same_session = session_id and focus.session is not None and str(focus.session.id) == session_id
    if same_lesson or same_session:
        return
    await thread.event(db, teacher, text="", lesson_id=lesson_id, session_id=session_id)


async def student_in(db, session: Session, student_id: uuid.UUID) -> User:
    admitted = await db.scalar(
        select(SessionParticipant.id).where(
            SessionParticipant.session_id == session.id,
            SessionParticipant.student_id == student_id,
        )
    )
    student = await db.get(User, student_id)
    if admitted is None or student is None:
        raise HTTPException(status_code=404, detail="Student not in this lesson.")
    return student
