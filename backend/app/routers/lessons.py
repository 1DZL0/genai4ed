"""Lessons: a class taught with one approved version of a lesson brief.

A lesson is booked (`scheduled`), started, and ends when its time is up or the
teacher ends it. While it runs the class agent works with each student; the
teacher's view of that is in `routers/live.py`.

Students are admitted when the lesson starts, not when it is booked, so a
student who joined the class in between is let in. Admission is the isolation
boundary: only participants can reach the lesson at all.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.agent.brief import LessonBrief
from app.auth import CurrentTeacher, DbSession, teacher_session
from app.enums import (
    ContractStatus,
    ExceptionStatus,
    Role,
    ScoreStatus,
    SessionStatus,
    TeacherAction,
)
from app.events import broker
from app.lifecycle import close_expired
from app.models import (
    Class,
    Enrolment,
    Exception_,
    LessonContract,
    LessonOutcome,
    Session,
    SessionParticipant,
    TeacherAccessLog,
    User,
)

router = APIRouter(prefix="/api/teacher", tags=["lessons"])

FINISHED_DAYS = 7


class LessonIn(BaseModel):
    plan_version_id: uuid.UUID
    class_id: uuid.UUID
    scheduled_for: datetime | None = None


class LessonSummary(BaseModel):
    lesson_id: uuid.UUID
    plan_version_id: uuid.UUID
    title: str
    subject: str
    class_label: str
    status: str
    plan_version: int
    scheduled_for: datetime | None
    opened_at: datetime | None
    closes_at: datetime | None
    closed_at: datetime | None
    students: int
    steps: int
    open_exceptions: int
    # Outcomes the agent suggested, waiting on the teacher.
    outcomes_to_confirm: int = 0


class TodayOut(BaseModel):
    coming_up: list[LessonSummary]
    finished: list[LessonSummary]


def _log(db, teacher: User, action: TeacherAction, session_id=None, student_id=None, detail=None):
    db.add(
        TeacherAccessLog(
            teacher_id=teacher.id,
            session_id=session_id,
            student_id=student_id,
            action=action.value,
            detail=detail or {},
        )
    )


async def _summary(db, session: Session) -> LessonSummary:
    contract = await db.get(LessonContract, session.contract_id)
    klass = await db.get(Class, session.class_id)
    brief = LessonBrief.model_validate(contract.brief or {})
    if session.status == SessionStatus.SCHEDULED.value:
        students = await db.scalar(
            select(func.count(Enrolment.id)).where(Enrolment.class_id == session.class_id)
        )
    else:
        students = await db.scalar(
            select(func.count(SessionParticipant.id)).where(
                SessionParticipant.session_id == session.id
            )
        )
    return LessonSummary(
        lesson_id=session.id,
        plan_version_id=contract.id,
        title=brief.title or contract.title,
        subject=brief.subject or contract.subject,
        class_label=klass.label if klass else "",
        status=session.status,
        plan_version=contract.version,
        scheduled_for=session.scheduled_for,
        opened_at=session.opened_at,
        closes_at=session.closes_at,
        closed_at=session.closed_at,
        students=students or 0,
        steps=len(brief.steps),
        open_exceptions=await db.scalar(
            select(func.count(Exception_.id)).where(
                Exception_.session_id == session.id,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
        )
        or 0,
        outcomes_to_confirm=await db.scalar(
            select(func.count(LessonOutcome.id)).where(
                LessonOutcome.session_id == session.id,
                LessonOutcome.status == ScoreStatus.SUGGESTED.value,
            )
        )
        or 0,
    )


async def _teacher_lessons(db, teacher: User, *statuses: str) -> list[Session]:
    return list(
        (
            await db.scalars(
                select(Session)
                .join(Class, Class.id == Session.class_id)
                .where(Class.teacher_id == teacher.id, Session.status.in_(statuses))
            )
        ).all()
    )


@router.post("/lessons", response_model=LessonSummary, status_code=status.HTTP_201_CREATED)
async def book_lesson(body: LessonIn, teacher: CurrentTeacher, db: DbSession) -> LessonSummary:
    contract = await db.get(LessonContract, body.plan_version_id)
    if contract is None or contract.teacher_id != teacher.id or contract.archived_at is not None:
        raise HTTPException(status_code=404, detail="Lesson not found.")
    if contract.status != ContractStatus.ACTIVE.value:
        raise HTTPException(
            status_code=409, detail="Approve the lesson before using it with a class."
        )
    klass = await db.get(Class, body.class_id)
    if klass is None or klass.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="Class not found.")

    session = Session(
        contract_id=contract.id,
        class_id=klass.id,
        status=SessionStatus.SCHEDULED.value,
        scheduled_for=body.scheduled_for,
    )
    db.add(session)
    await db.flush()
    _log(db, teacher, TeacherAction.SCHEDULE_LESSON, session.id, detail={"class": klass.label})
    await db.commit()
    return await _summary(db, session)


@router.post("/lessons/{lesson_id}/start", response_model=LessonSummary)
async def start_lesson(
    lesson_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> LessonSummary:
    session = await teacher_session(lesson_id, teacher, db)
    if session.status != SessionStatus.SCHEDULED.value:
        raise HTTPException(status_code=409, detail="This lesson has already started.")
    contract = await db.get(LessonContract, session.contract_id)

    students = (
        await db.scalars(
            select(User)
            .join(Enrolment, Enrolment.student_id == User.id)
            .where(Enrolment.class_id == session.class_id, User.role == Role.STUDENT.value)
        )
    ).all()
    db.add_all([SessionParticipant(session_id=session.id, student_id=s.id) for s in students])

    now = datetime.now(UTC)
    minutes = LessonBrief.model_validate(contract.brief or {}).duration_minutes
    session.status = SessionStatus.OPEN.value
    session.opened_at = now
    session.closes_at = now + timedelta(minutes=minutes)
    _log(db, teacher, TeacherAction.START_LESSON, session.id, detail={"students": len(students)})
    await db.commit()
    await broker.publish(session.id, {"type": "session_state", "status": session.status})
    return await _summary(db, session)


@router.get("/today", response_model=TodayOut)
async def today(teacher: CurrentTeacher, db: DbSession) -> TodayOut:
    await close_expired(db)
    now = datetime.now(UTC)
    coming = await _teacher_lessons(
        db,
        teacher,
        SessionStatus.SCHEDULED.value,
        SessionStatus.OPEN.value,
        SessionStatus.PAUSED.value,
    )
    # Running lessons first, then booked ones by time; lessons booked for another day wait.
    coming = [
        s
        for s in coming
        if s.status != SessionStatus.SCHEDULED.value
        or s.scheduled_for is None
        or s.scheduled_for.date() <= now.date()
    ]
    coming.sort(key=lambda s: (s.status == SessionStatus.SCHEDULED.value, s.scheduled_for or now))

    finished = [
        s
        for s in await _teacher_lessons(db, teacher, SessionStatus.CLOSED.value)
        if s.closed_at and s.closed_at >= now - timedelta(days=FINISHED_DAYS)
    ]
    finished.sort(key=lambda s: s.closed_at, reverse=True)
    return TodayOut(
        coming_up=[await _summary(db, s) for s in coming],
        finished=[await _summary(db, s) for s in finished],
    )


@router.get("/lessons/past", response_model=list[LessonSummary])
async def past_lessons(
    teacher: CurrentTeacher, db: DbSession, class_id: uuid.UUID | None = None
) -> list[LessonSummary]:
    await close_expired(db)
    lessons = await _teacher_lessons(db, teacher, SessionStatus.CLOSED.value)
    if class_id is not None:
        lessons = [s for s in lessons if s.class_id == class_id]
    lessons.sort(key=lambda s: s.closed_at or s.created_at, reverse=True)
    return [await _summary(db, s) for s in lessons]
