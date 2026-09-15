"""The teacher console.

Quiet by default: compact progress, help requests, and a prioritised exception
queue. Everything that touches a named student's work - drilling into a
transcript, messaging them, pausing their session - is written to
`teacher_access_log`, because the note promises students that transcript access
is deliberate and disclosed rather than ambient.
"""

import asyncio
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.auth import CurrentTeacher, DbSession, revoke_sign_ins, teacher_session
from app.enums import (
    EvidenceKind,
    ExceptionStatus,
    Role,
    SessionStatus,
    TeacherAction,
)
from app.events import broker
from app.ledger import append
from app.lifecycle import close_expired
from app.models import (
    Class,
    Enrolment,
    EvidenceRecord,
    Exception_,
    LessonContract,
    Session,
    SessionParticipant,
    TeacherAccessLog,
    User,
)
from app.register import StudentProgress, build_register
from app.security import join_code_digest, new_join_code
from app.timeline import timeline_of

router = APIRouter(prefix="/api/teacher", tags=["teacher"])

HEARTBEAT_SECONDS = 15


class ConsoleItem(BaseModel):
    id: uuid.UUID
    ordinal: int
    prompt: str
    kind: str = "short_answer"


class QueueItem(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    pseudonym: str
    kind: str
    priority: int
    summary: str
    supporting_record_ids: list[str]
    created_at: datetime


class ConsoleOut(BaseModel):
    session_id: uuid.UUID
    status: str
    # Empty until a scheduled lesson is started.
    closes_at: datetime | None
    title: str
    subject: str
    class_label: str
    items: int
    item_list: list[ConsoleItem]
    # The contract's ladder, in order, so the register can draw each gauge to scale.
    rungs: list[str]
    # The lesson's phases and which one the class is in, for the whiteboard.
    timeline: list[dict]
    phase_index: int
    progress: list[StudentProgress]
    queue: list[QueueItem]


class TranscriptLine(BaseModel):
    record_id: uuid.UUID
    kind: str
    correct: bool | None
    detail: dict
    created_at: datetime


class MessageIn(BaseModel):
    text: str


async def _log(
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
    """ "9B English" -> "9B". Pseudonyms stay short enough to read off a card."""
    first = re.sub(r"[^A-Za-z0-9]", "", label.split()[0]) if label.split() else ""
    return (first or "class")[:12]


async def _new_students(db, klass: Class, count: int) -> list[User]:
    """Make `count` pseudonymous students and enrol them.

    Numbers count up from 01 and skip any pseudonym already taken, in this class
    or anywhere else, because pseudonyms are unique platform-wide.
    """
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
    """A class and its students. Students are pseudonyms from the start; the
    teacher keeps the list of who is who outside the platform."""
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
    await db.commit()
    return RosterEntry(student_id=student.id, pseudonym=student.pseudonym, has_join_code=False)


@router.delete("/classes/{class_id}/students/{student_id}", status_code=204)
async def remove_student(
    class_id: uuid.UUID, student_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> None:
    """Take a student off the class list. Their past lessons and work are kept;
    they are simply not admitted to this class's future lessons."""
    await _owned_class(class_id, teacher, db)
    enrolment = await db.scalar(
        select(Enrolment).where(Enrolment.class_id == class_id, Enrolment.student_id == student_id)
    )
    if enrolment is None:
        raise HTTPException(status_code=404, detail="Student not in this class.")
    await db.delete(enrolment)
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


@router.post("/classes/{class_id}/join-codes", response_model=list[JoinCodeOut])
async def issue_join_codes(
    class_id: uuid.UUID,
    teacher: CurrentTeacher,
    db: DbSession,
    student_id: uuid.UUID | None = None,
) -> list[JoinCodeOut]:
    """Issue fresh join codes for the whole class, or for one student.

    Codes are shown here once and stored only as digests, so a lost code is
    replaced rather than looked up. Replacing a code signs that student out, so
    a code that went astray stops working everywhere.
    """
    await _owned_class(class_id, teacher, db)
    students = await _class_students(db, class_id)
    if student_id is not None:
        students = [s for s in students if s.id == student_id]
        if not students:
            raise HTTPException(status_code=404, detail="Student not in this class.")

    issued: list[JoinCodeOut] = []
    for student in students:
        code = new_join_code()
        student.join_code_digest = join_code_digest(code)
        issued.append(JoinCodeOut(student_id=student.id, pseudonym=student.pseudonym, code=code))

    await revoke_sign_ins(db, [s.id for s in students])
    # The codes themselves never reach the log - only who was issued one.
    await _log(
        db,
        teacher,
        TeacherAction.ISSUE_JOIN_CODES,
        student_id=student_id,
        detail={"class_id": str(class_id), "students": [s.pseudonym for s in students]},
    )
    await db.commit()
    return issued


class TeacherSessionSummary(BaseModel):
    session_id: uuid.UUID
    title: str
    subject: str
    status: str
    class_label: str
    closes_at: datetime
    open_exceptions: int


@router.get("/sessions", response_model=list[TeacherSessionSummary])
async def my_sessions(teacher: CurrentTeacher, db: DbSession) -> list[TeacherSessionSummary]:
    """Sessions for the classes this teacher owns that have started. Booked
    lessons that haven't started yet are listed under today's lessons."""
    await close_expired(db)
    rows = (
        await db.execute(
            select(Session, LessonContract, Class)
            .join(LessonContract, LessonContract.id == Session.contract_id)
            .join(Class, Class.id == Session.class_id)
            .where(
                Class.teacher_id == teacher.id,
                Session.status != SessionStatus.SCHEDULED.value,
            )
            .order_by(Session.opened_at.desc())
        )
    ).all()

    out: list[TeacherSessionSummary] = []
    for session, contract, klass in rows:
        open_count = len(
            (
                await db.scalars(
                    select(Exception_.id).where(
                        Exception_.session_id == session.id,
                        Exception_.status == ExceptionStatus.OPEN.value,
                    )
                )
            ).all()
        )
        out.append(
            TeacherSessionSummary(
                session_id=session.id,
                title=contract.title,
                subject=contract.subject,
                status=session.status,
                class_label=klass.label,
                closes_at=session.closes_at,
                open_exceptions=open_count,
            )
        )
    return out


@router.get("/sessions/{session_id}/console", response_model=ConsoleOut)
async def console(session_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> ConsoleOut:
    """Aggregate only. Reading this does not open anyone's transcript, so it is
    not an access event."""
    session = await teacher_session(session_id, teacher, db)
    reg = await build_register(db, session)
    by_id = {s.id: s for s in reg.students}

    return ConsoleOut(
        session_id=session.id,
        status=session.status,
        closes_at=session.closes_at,
        title=reg.contract.title,
        subject=reg.contract.subject,
        class_label=reg.klass.label if reg.klass else "",
        items=len(reg.items),
        item_list=[
            ConsoleItem(id=i.id, ordinal=i.ordinal, prompt=i.prompt, kind=i.kind) for i in reg.items
        ],
        rungs=list((reg.contract.assistance_ladder or {}).get("rungs", [])),
        timeline=timeline_of(reg.contract.timeline),
        phase_index=session.phase_index,
        progress=reg.progress,
        queue=[
            QueueItem(
                id=e.id,
                student_id=e.student_id,
                pseudonym=by_id[e.student_id].pseudonym if e.student_id in by_id else "unknown",
                kind=e.kind,
                priority=e.priority,
                summary=e.summary,
                supporting_record_ids=[str(r) for r in e.supporting_record_ids],
                created_at=e.created_at,
            )
            for e in reg.open_exceptions
        ],
    )


@router.get("/sessions/{session_id}/stream")
async def stream(session_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession):
    """Live exceptions.

    Note: this holds its database session for the life of the connection. With
    one teacher per session that is fine; it is the first thing to change if
    the console is ever opened on many devices at once.
    """
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

    exc.status = ExceptionStatus.ACKNOWLEDGED.value
    exc.acknowledged_at = datetime.now(UTC)
    exc.acknowledged_by = teacher.id
    await _log(
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


@router.get(
    "/sessions/{session_id}/students/{student_id}/transcript",
    response_model=list[TranscriptLine],
)
async def transcript(
    session_id: uuid.UUID, student_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> list[TranscriptLine]:
    """Deliberate drill-down into one student's work. Always logged."""
    await teacher_session(session_id, teacher, db)
    participant = await db.scalar(
        select(SessionParticipant).where(
            SessionParticipant.session_id == session_id,
            SessionParticipant.student_id == student_id,
        )
    )
    if participant is None:
        raise HTTPException(status_code=404, detail="Student not in this session.")

    records = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session_id,
                EvidenceRecord.student_id == student_id,
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()

    await _log(
        db,
        teacher,
        TeacherAction.TRANSCRIPT_DRILLDOWN,
        session_id,
        student_id,
        {"records": len(records)},
    )
    await db.commit()

    return [
        TranscriptLine(
            record_id=r.id,
            kind=r.kind,
            correct=r.correct,
            detail=r.payload,
            created_at=r.created_at,
        )
        for r in records
    ]


@router.post("/sessions/{session_id}/students/{student_id}/message", status_code=202)
async def message_student(
    session_id: uuid.UUID,
    student_id: uuid.UUID,
    body: MessageIn,
    teacher: CurrentTeacher,
    db: DbSession,
) -> dict[str, str]:
    await teacher_session(session_id, teacher, db)
    await append(
        db,
        session_id=session_id,
        student_id=student_id,
        kind=EvidenceKind.TEACHER_FEEDBACK,
        payload={"text": body.text},
        provenance={"source": "teacher", "teacher_id": str(teacher.id)},
    )
    await _log(db, teacher, TeacherAction.MESSAGE_STUDENT, session_id, student_id)
    await db.commit()
    return {"status": "sent"}


@router.post("/sessions/{session_id}/state", response_model=ConsoleOut)
async def set_state(
    session_id: uuid.UUID, to: SessionStatus, teacher: CurrentTeacher, db: DbSession
) -> ConsoleOut:
    """Pause, resume or close the activity for the whole class.

    Closing is final, whether the teacher did it or the time ran out: a closed
    session cannot be resumed, so its deadline stays a limit.
    """
    session = await teacher_session(session_id, teacher, db)
    if session.status == SessionStatus.CLOSED.value:
        raise HTTPException(
            status_code=409, detail="This session has ended. Open a new session to continue."
        )
    action = {
        SessionStatus.PAUSED: TeacherAction.PAUSE_SESSION,
        SessionStatus.OPEN: TeacherAction.RESUME_SESSION,
        SessionStatus.CLOSED: TeacherAction.CLOSE_SESSION,
    }[to]

    session.status = to.value
    if to is SessionStatus.CLOSED:
        session.closed_at = datetime.now(UTC)
    await _log(db, teacher, action, session_id)
    await db.commit()

    await broker.publish(
        session_id, {"type": "session_state", "status": to.value, "summary": f"Session {to.value}."}
    )
    return await console(session_id, teacher, db)
