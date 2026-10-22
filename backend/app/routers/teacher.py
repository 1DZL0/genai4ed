"""Classes, join codes, the live event stream, and pausing or closing a lesson for the class.

Anything that touches a named student is written to `teacher_access_log`.
"""

import asyncio
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from app.agent import classroom
from app.agent.brief import LessonBrief
from app.auth import CurrentTeacher, DbSession, revoke_sign_ins, teacher_session
from app.enums import (
    ExceptionStatus,
    LearningStatus,
    Role,
    ScoreStatus,
    SessionStatus,
    TeacherAction,
)
from app.events import broker
from app.models import (
    AgentTurn,
    Class,
    Enrolment,
    Exception_,
    LearningState,
    LessonContract,
    LessonOutcome,
    Session,
    SessionParticipant,
    TeacherAccessLog,
    User,
)
from app.security import join_code_digest, new_join_code

router = APIRouter(prefix="/api/teacher", tags=["teacher"])

HEARTBEAT_SECONDS = 15


class QueueItem(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    pseudonym: str
    kind: str
    priority: int
    summary: str
    supporting_record_ids: list[str]
    created_at: datetime


def _log(
    db,
    teacher: User,
    action: TeacherAction,
    session_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        TeacherAccessLog(
            teacher_id=teacher.id,
            session_id=session_id,
            student_id=student_id,
            action=action.value,
            detail=detail or {},
        )
    )


class ClassOut(BaseModel):
    id: uuid.UUID
    label: str
    students: int


@router.get("/classes", response_model=list[ClassOut])
async def my_classes(teacher: CurrentTeacher, db: DbSession) -> list[ClassOut]:
    classes = (
        await db.scalars(select(Class).where(Class.teacher_id == teacher.id).order_by(Class.label))
    ).all()
    out = []
    for klass in classes:
        students = len(
            (await db.scalars(select(Enrolment.id).where(Enrolment.class_id == klass.id))).all()
        )
        out.append(ClassOut(id=klass.id, label=klass.label, students=students))
    return out


class RosterEntry(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    has_join_code: bool


class JoinCodeOut(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    code: str


async def _owned_class(class_id: uuid.UUID, teacher: User, db) -> Class:
    klass = await db.get(Class, class_id)
    if klass is None or klass.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="Class not found.")
    return klass


async def _class_students(db, class_id: uuid.UUID) -> list[User]:
    return list(
        (
            await db.scalars(
                select(User)
                .join(Enrolment, Enrolment.student_id == User.id)
                .where(Enrolment.class_id == class_id)
                .order_by(User.pseudonym)
            )
        ).all()
    )


class ClassIn(BaseModel):
    label: str = Field(min_length=1, max_length=32)
    students: int = Field(default=0, ge=0, le=40)


def _pseudonym_prefix(label: str) -> str:
    """ "9B English" -> "9B"."""
    first = re.sub(r"[^A-Za-z0-9]", "", label.split()[0]) if label.split() else ""
    return (first or "class")[:12]


async def _new_students(db, klass: Class, count: int) -> list[User]:
    """Make `count` pseudonymous students and enrol them, skipping any pseudonym already taken."""
    prefix = _pseudonym_prefix(klass.label)
    taken = set(
        (await db.scalars(select(User.pseudonym).where(User.pseudonym.like(f"{prefix}-%")))).all()
    )
    made: list[User] = []
    n = 1
    while len(made) < count:
        name = f"{prefix}-{n:02d}"
        n += 1
        if name in taken:
            continue
        student = User(pseudonym=name, role=Role.STUDENT.value)
        db.add(student)
        await db.flush()
        db.add(Enrolment(class_id=klass.id, student_id=student.id))
        made.append(student)
    await db.flush()
    return made


@router.post("/classes", response_model=ClassOut, status_code=201)
async def create_class(body: ClassIn, teacher: CurrentTeacher, db: DbSession) -> ClassOut:
    """A class and its students; the teacher keeps who is who outside the platform."""
    klass = Class(teacher_id=teacher.id, label=body.label.strip())
    db.add(klass)
    await db.flush()
    await _new_students(db, klass, body.students)
    await db.commit()
    return ClassOut(id=klass.id, label=klass.label, students=body.students)


@router.post("/classes/{class_id}/students", response_model=RosterEntry, status_code=201)
async def add_student(class_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> RosterEntry:
    klass = await _owned_class(class_id, teacher, db)
    [student] = await _new_students(db, klass, 1)
    # A student added while the class is in a lesson joins that lesson too.
    running = (
        await db.scalars(
            select(Session.id).where(
                Session.class_id == klass.id,
                Session.status.in_([SessionStatus.OPEN.value, SessionStatus.PAUSED.value]),
            )
        )
    ).all()
    db.add_all([SessionParticipant(session_id=s, student_id=student.id) for s in running])
    await db.commit()
    return RosterEntry(student_id=student.id, pseudonym=student.pseudonym, has_join_code=False)


@router.delete("/classes/{class_id}/students/{student_id}", status_code=204)
async def remove_student(
    class_id: uuid.UUID, student_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> None:
    """Their past work is kept; they are just not admitted to this class's future lessons."""
    await _owned_class(class_id, teacher, db)
    enrolment = await db.scalar(
        select(Enrolment).where(Enrolment.class_id == class_id, Enrolment.student_id == student_id)
    )
    if enrolment is None:
        raise HTTPException(status_code=404, detail="Student not in this class.")
    await db.delete(enrolment)
    elsewhere = await db.scalar(
        select(Enrolment.id).where(
            Enrolment.student_id == student_id, Enrolment.class_id != class_id
        )
    )
    if elsewhere is None:
        # In no class any more: their code stops working and they are signed out.
        student = await db.get(User, student_id)
        if student is not None:
            student.join_code_digest = None
        await revoke_sign_ins(db, [student_id])
    await db.commit()


@router.get("/classes/{class_id}/students", response_model=list[RosterEntry])
async def roster(class_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> list[RosterEntry]:
    await _owned_class(class_id, teacher, db)
    return [
        RosterEntry(
            student_id=s.id, pseudonym=s.pseudonym, has_join_code=s.join_code_digest is not None
        )
        for s in await _class_students(db, class_id)
    ]


class ProgressLesson(BaseModel):
    session_id: uuid.UUID
    title: str
    subject: str
    date: str | None
    status: str
    steps: int


class ProgressMark(BaseModel):
    total: int
    out_of: int


class ProgressCell(BaseModel):
    session_id: uuid.UUID
    # finished | part | opened | not_started | not_in_lesson
    state: str
    steps_done: int
    steps_total: int
    # Only a mark the teacher confirmed; a suggestion is not a mark yet.
    mark: ProgressMark | None = None
    # confirmed | suggested, or nothing when no outcome was suggested.
    outcome: str | None = None
    alerts_open: int = 0


class ProgressRow(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    cells: list[ProgressCell]


class ClassProgress(BaseModel):
    class_id: uuid.UUID
    label: str
    lessons: list[ProgressLesson]
    students: list[ProgressRow]


@router.get("/classes/{class_id}/progress", response_model=ClassProgress)
async def class_progress(
    class_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> ClassProgress:
    """How every student did in every lesson the class has had, oldest first, so the teacher
    can see who to go over something with, or check before marking work on paper."""
    klass = await _owned_class(class_id, teacher, db)
    runs = list(
        (
            await db.execute(
                select(Session, LessonContract)
                .join(LessonContract, LessonContract.id == Session.contract_id)
                .where(
                    Session.class_id == klass.id,
                    Session.status != SessionStatus.SCHEDULED.value,
                )
            )
        )
        .tuples()
        .all()
    )
    runs.sort(key=lambda r: (r[0].opened_at or r[0].created_at, r[0].created_at))
    session_ids = [s.id for s, _ in runs]
    briefs = {s.id: LessonBrief.model_validate(c.brief or {}) for s, c in runs}
    steps = {session_id: len(brief.steps) for session_id, brief in briefs.items()}
    lessons = [
        ProgressLesson(
            session_id=s.id,
            title=briefs[s.id].title or c.title,
            subject=c.subject,
            date=classroom.when(s.opened_at or s.created_at),
            status=s.status,
            steps=steps[s.id],
        )
        for s, c in runs
    ]

    # Everything for the class's lessons in one read per table, keyed (session, student).
    members: set[tuple[uuid.UUID, uuid.UUID]] = set()
    turned: set[tuple[uuid.UUID, uuid.UUID]] = set()
    states: dict[tuple[uuid.UUID, uuid.UUID], LearningState] = {}
    outcomes: dict[tuple[uuid.UUID, uuid.UUID], LessonOutcome] = {}
    alerts: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    wrote: dict[uuid.UUID, set[uuid.UUID]] = {}
    if session_ids:
        members = set(
            (
                await db.execute(
                    select(SessionParticipant.session_id, SessionParticipant.student_id).where(
                        SessionParticipant.session_id.in_(session_ids)
                    )
                )
            )
            .tuples()
            .all()
        )
        turned = set(
            (
                await db.execute(
                    select(AgentTurn.session_id, AgentTurn.student_id)
                    .where(AgentTurn.session_id.in_(session_ids), AgentTurn.student_id.is_not(None))
                    .distinct()
                )
            )
            .tuples()
            .all()
        )
        states = {
            (x.session_id, x.student_id): x
            for x in (
                await db.scalars(
                    select(LearningState).where(LearningState.session_id.in_(session_ids))
                )
            ).all()
        }
        outcomes = {
            (x.session_id, x.student_id): x
            for x in (
                await db.scalars(
                    select(LessonOutcome).where(LessonOutcome.session_id.in_(session_ids))
                )
            ).all()
        }
        alerts = {
            (session_id, student_id): count
            for session_id, student_id, count in (
                await db.execute(
                    select(Exception_.session_id, Exception_.student_id, func.count(Exception_.id))
                    .where(
                        Exception_.session_id.in_(session_ids),
                        Exception_.status == ExceptionStatus.OPEN.value,
                    )
                    .group_by(Exception_.session_id, Exception_.student_id)
                )
            ).all()
        }
        # Taking part is read from the turns, as everywhere else: one read per lesson.
        for session_id in session_ids:
            wrote[session_id] = await classroom.students_who_wrote(db, session_id)

    # The roster, and anyone who was in one of these lessons and has since left the class.
    students = await _class_students(db, klass.id)
    gone = {student_id for _, student_id in members} - {s.id for s in students}
    if gone:
        students += list((await db.scalars(select(User).where(User.id.in_(gone)))).all())
    students.sort(key=lambda u: (u.pseudonym.casefold(), u.pseudonym))

    def cell(session_id: uuid.UUID, student_id: uuid.UUID) -> ProgressCell:
        key = (session_id, student_id)
        total = steps[session_id]
        state = states.get(key)
        completed = bool(state and state.status == LearningStatus.COMPLETED.value)
        if key not in members:
            label = "not_in_lesson"
        elif student_id in wrote[session_id]:
            label = "finished" if completed else "part"
        elif key in turned:
            label = "opened"
        else:
            label = "not_started"
        outcome = outcomes.get(key)
        mark = None
        if outcome is not None and outcome.status == ScoreStatus.CONFIRMED.value:
            # Out of what the confirmed criteria were worth, as the student is shown it.
            criteria = (outcome.confirmed or {}).get("criteria", [])
            out_of = sum(int(c.get("max", 0)) for c in criteria)
            if out_of > 0:
                mark = ProgressMark(total=outcome.confirmed_total or 0, out_of=out_of)
        return ProgressCell(
            session_id=session_id,
            state=label,
            steps_done=total if completed else min(state.step_index, total) if state else 0,
            steps_total=total,
            mark=mark,
            outcome=outcome.status if outcome is not None else None,
            alerts_open=alerts.get(key, 0),
        )

    return ClassProgress(
        class_id=klass.id,
        label=klass.label,
        lessons=lessons,
        students=[
            ProgressRow(
                student_id=s.id,
                pseudonym=s.pseudonym,
                cells=[cell(session_id, s.id) for session_id in session_ids],
            )
            for s in students
        ],
    )


@router.post("/classes/{class_id}/join-codes", response_model=list[JoinCodeOut])
async def issue_join_codes(
    class_id: uuid.UUID,
    teacher: CurrentTeacher,
    db: DbSession,
    student_id: uuid.UUID | None = None,
) -> list[JoinCodeOut]:
    """Fresh codes for the class or one student: shown once, stored as digests, and the
    replaced code's sign-ins are ended. A student's first code leaves them signed in."""
    await _owned_class(class_id, teacher, db)
    students = await _class_students(db, class_id)
    if student_id is not None:
        students = [s for s in students if s.id == student_id]
        if not students:
            raise HTTPException(status_code=404, detail="Student not in this class.")

    # Only an old code is being replaced; a student without one (signed in some other way,
    # as in the demo) is not thrown out of the lesson they are in.
    replaced = [s.id for s in students if s.join_code_digest]
    issued: list[JoinCodeOut] = []
    for student in students:
        code = new_join_code()
        student.join_code_digest = join_code_digest(code)
        issued.append(JoinCodeOut(student_id=student.id, pseudonym=student.pseudonym, code=code))

    await revoke_sign_ins(db, replaced)
    # The codes themselves never reach the log, only who was issued one.
    _log(
        db,
        teacher,
        TeacherAction.ISSUE_JOIN_CODES,
        student_id=student_id,
        detail={"class_id": str(class_id), "students": [s.pseudonym for s in students]},
    )
    await db.commit()
    return issued


class StateOut(BaseModel):
    session_id: uuid.UUID
    status: str
    closed_at: datetime | None


@router.get("/sessions/{session_id}/stream")
async def stream(session_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession):
    """Live exceptions. Holds its database session for the life of the connection."""
    await teacher_session(session_id, teacher, db)

    async def events():
        async with broker.subscribe(session_id) as queue:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
                    continue
                yield {"event": "exception", "data": event}

    return EventSourceResponse(events())


@router.post("/exceptions/{exception_id}/acknowledge", response_model=QueueItem)
async def acknowledge(exception_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> QueueItem:
    exc = await db.get(Exception_, exception_id)
    if exc is None:
        raise HTTPException(status_code=404, detail="Exception not found.")
    await teacher_session(exc.session_id, teacher, db)

    # Only an open alert is dealt with: pressing again, or on one the student's own progress
    # already closed, changes nothing and records nothing.
    if exc.status == ExceptionStatus.OPEN.value:
        exc.status = ExceptionStatus.ACKNOWLEDGED.value
        exc.acknowledged_at = datetime.now(UTC)
        exc.acknowledged_by = teacher.id
        _log(
            db,
            teacher,
            TeacherAction.ACKNOWLEDGE_EXCEPTION,
            exc.session_id,
            exc.student_id,
            {"exception_id": str(exc.id), "kind": exc.kind},
        )
        await db.commit()

    student = await db.get(User, exc.student_id)
    return QueueItem(
        id=exc.id,
        student_id=exc.student_id,
        pseudonym=student.pseudonym if student else "unknown",
        kind=exc.kind,
        priority=exc.priority,
        summary=exc.summary,
        supporting_record_ids=[str(r) for r in exc.supporting_record_ids],
        created_at=exc.created_at,
    )


@router.post("/sessions/{session_id}/state", response_model=StateOut)
async def set_state(
    session_id: uuid.UUID, to: SessionStatus, teacher: CurrentTeacher, db: DbSession
) -> StateOut:
    """Pause, resume or close for the whole class. Closing is final."""
    session = await teacher_session(session_id, teacher, db)
    if session.status == SessionStatus.CLOSED.value:
        raise HTTPException(
            status_code=409,
            detail="This lesson has ended. To teach it again, start it from the lesson card.",
        )
    action = {
        SessionStatus.PAUSED: TeacherAction.PAUSE_SESSION,
        SessionStatus.OPEN: TeacherAction.RESUME_SESSION,
        SessionStatus.CLOSED: TeacherAction.CLOSE_SESSION,
    }[to]

    session.status = to.value
    if to is SessionStatus.CLOSED:
        session.closed_at = datetime.now(UTC)
    _log(db, teacher, action, session_id)
    await db.commit()

    await broker.publish(
        session_id, {"type": "session_state", "status": to.value, "summary": f"Session {to.value}."}
    )
    return StateOut(session_id=session.id, status=session.status, closed_at=session.closed_at)
