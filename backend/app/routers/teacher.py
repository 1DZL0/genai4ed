"""The teacher console.

Quiet by default: compact progress, help requests, and a prioritised exception
queue. Everything that touches a named student's work - drilling into a
transcript, messaging them, pausing their session - is written to
`teacher_access_log`, because the note promises students that transcript access
is deliberate and disclosed rather than ambient.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.auth import CurrentTeacher, DbSession, teacher_session
from app.enums import EvidenceKind, ExceptionStatus, SessionStatus, TeacherAction
from app.events import broker
from app.ledger import append
from app.models import (
    Class,
    ContractItem,
    EvidenceRecord,
    Exception_,
    LessonContract,
    Session,
    SessionParticipant,
    TeacherAccessLog,
    User,
)

router = APIRouter(prefix="/api/teacher", tags=["teacher"])

HEARTBEAT_SECONDS = 15


class StudentProgress(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    attempted: int
    correct: int
    attempts: int


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
    title: str
    items: int
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


class TeacherSessionSummary(BaseModel):
    session_id: uuid.UUID
    title: str
    status: str
    class_label: str
    closes_at: datetime
    open_exceptions: int


@router.get("/sessions", response_model=list[TeacherSessionSummary])
async def my_sessions(teacher: CurrentTeacher, db: DbSession) -> list[TeacherSessionSummary]:
    """Sessions for the classes this teacher owns."""
    rows = (
        await db.execute(
            select(Session, LessonContract, Class)
            .join(LessonContract, LessonContract.id == Session.contract_id)
            .join(Class, Class.id == Session.class_id)
            .where(Class.teacher_id == teacher.id)
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
    contract = await db.get(LessonContract, session.contract_id)
    item_count = len(
        (
            await db.scalars(
                select(ContractItem.id).where(ContractItem.contract_id == contract.id)
            )
        ).all()
    )

    students = (
        await db.scalars(
            select(User)
            .join(SessionParticipant, SessionParticipant.student_id == User.id)
            .where(SessionParticipant.session_id == session_id)
            .order_by(User.pseudonym)
        )
    ).all()

    progress: list[StudentProgress] = []
    for student in students:
        attempts = (
            await db.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.session_id == session_id,
                    EvidenceRecord.student_id == student.id,
                    EvidenceRecord.kind == EvidenceKind.ATTEMPT.value,
                )
            )
        ).all()
        progress.append(
            StudentProgress(
                student_id=student.id,
                pseudonym=student.pseudonym,
                attempted=len({a.item_id for a in attempts}),
                correct=len({a.item_id for a in attempts if a.correct}),
                attempts=len(attempts),
            )
        )

    open_exceptions = (
        await db.scalars(
            select(Exception_)
            .where(
                Exception_.session_id == session_id,
                Exception_.status == ExceptionStatus.OPEN.value,
            )
            .order_by(Exception_.priority, Exception_.created_at)
        )
    ).all()
    by_id = {s.id: s for s in students}

    return ConsoleOut(
        session_id=session.id,
        status=session.status,
        title=contract.title,
        items=item_count,
        progress=progress,
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
            for e in open_exceptions
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
async def acknowledge(
    exception_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> QueueItem:
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
    """Pause, resume or close the activity for the whole class."""
    session = await teacher_session(session_id, teacher, db)
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
