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

from app.auth import CurrentTeacher, DbSession, revoke_sign_ins, teacher_session
from app.enums import (
    EvidenceKind,
    ExceptionStatus,
    Rung,
    SessionStatus,
    TeacherAction,
    rung_index,
)
from app.events import broker
from app.ledger import append
from app.lifecycle import close_expired
from app.models import (
    Class,
    ContractItem,
    Enrolment,
    EvidenceRecord,
    Exception_,
    LessonContract,
    Session,
    SessionParticipant,
    TeacherAccessLog,
    User,
)
from app.security import join_code_digest, new_join_code

router = APIRouter(prefix="/api/teacher", tags=["teacher"])

HEARTBEAT_SECONDS = 15

KNOWN_RUNGS = frozenset(r.value for r in Rung)


class RegisterCell(BaseModel):
    """One student on one question, as the register shows it."""

    item_id: uuid.UUID
    attempts: int
    solved: bool
    # The highest rung of help the tutor has actually given on this question.
    rung: str | None


class StudentProgress(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    attempted: int
    correct: int
    attempts: int
    needs_you: bool
    cells: list[RegisterCell]


class ConsoleItem(BaseModel):
    id: uuid.UUID
    ordinal: int
    prompt: str


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
    closes_at: datetime
    title: str
    subject: str
    class_label: str
    items: int
    item_list: list[ConsoleItem]
    # The contract's ladder, in order, so the register can draw each gauge to scale.
    rungs: list[str]
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
        await db.scalars(
            select(Class).where(Class.teacher_id == teacher.id).order_by(Class.label)
        )
    ).all()
    out = []
    for klass in classes:
        students = len(
            (
                await db.scalars(
                    select(Enrolment.id).where(Enrolment.class_id == klass.id)
                )
            ).all()
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
    """Sessions for the classes this teacher owns."""
    await close_expired(db)
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
    contract = await db.get(LessonContract, session.contract_id)
    klass = await db.get(Class, session.class_id)
    items = (
        await db.scalars(
            select(ContractItem)
            .where(ContractItem.contract_id == contract.id)
            .order_by(ContractItem.ordinal)
        )
    ).all()

    students = (
        await db.scalars(
            select(User)
            .join(SessionParticipant, SessionParticipant.student_id == User.id)
            .where(SessionParticipant.session_id == session_id)
            .order_by(User.pseudonym)
        )
    ).all()

    # One read of the session's attempts and hints, grouped in memory, rather
    # than a query per student per question on every poll.
    records = (
        await db.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.session_id == session_id,
                EvidenceRecord.kind.in_([EvidenceKind.ATTEMPT.value, EvidenceKind.HINT.value]),
            )
        )
    ).all()
    by_cell: dict[tuple[uuid.UUID, uuid.UUID | None], list[EvidenceRecord]] = {}
    for r in records:
        by_cell.setdefault((r.student_id, r.item_id), []).append(r)

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
    waiting = {e.student_id for e in open_exceptions}

    progress: list[StudentProgress] = []
    for student in students:
        cells: list[RegisterCell] = []
        for item in items:
            rows = by_cell.get((student.id, item.id), [])
            attempts = [r for r in rows if r.kind == EvidenceKind.ATTEMPT.value]
            hint_rungs = [
                Rung(r.payload["rung"])
                for r in rows
                if r.kind == EvidenceKind.HINT.value and r.payload.get("rung") in KNOWN_RUNGS
            ]
            cells.append(
                RegisterCell(
                    item_id=item.id,
                    attempts=len(attempts),
                    solved=any(a.correct for a in attempts),
                    rung=max(hint_rungs, key=rung_index).value if hint_rungs else None,
                )
            )
        progress.append(
            StudentProgress(
                student_id=student.id,
                pseudonym=student.pseudonym,
                attempted=sum(1 for c in cells if c.attempts),
                correct=sum(1 for c in cells if c.solved),
                attempts=sum(c.attempts for c in cells),
                needs_you=student.id in waiting,
                cells=cells,
            )
        )

    by_id = {s.id: s for s in students}

    return ConsoleOut(
        session_id=session.id,
        status=session.status,
        closes_at=session.closes_at,
        title=contract.title,
        subject=contract.subject,
        class_label=klass.label if klass else "",
        items=len(items),
        item_list=[ConsoleItem(id=i.id, ordinal=i.ordinal, prompt=i.prompt) for i in items],
        rungs=list((contract.assistance_ladder or {}).get("rungs", [])),
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
