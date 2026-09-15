"""Lessons: a class taught with one approved version of a plan.

A lesson is booked (`scheduled`), started, moved through the plan's phases,
and ends when its time is up or the teacher ends it. Finished lessons stay
available for review, student by student.

Students are admitted when the lesson starts, not when it is booked, so a
student who joined the class in between is let in. Admission is the isolation
boundary: only participants can reach the lesson at all.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth import CurrentTeacher, DbSession, teacher_session
from app.enums import (
    ContractStatus,
    EvidenceKind,
    ItemKind,
    Role,
    ScoreStatus,
    SessionStatus,
    TeacherAction,
)
from app.events import broker
from app.lifecycle import close_expired
from app.models import (
    Class,
    ContractItem,
    Enrolment,
    EvidenceRecord,
    Exception_,
    LessonContract,
    RubricScore,
    Session,
    SessionParticipant,
    TeacherAccessLog,
    User,
)
from app.register import StudentProgress, build_register
from app.timeline import timeline_of, total_minutes
from app.tutor.writing import WritingError, confirm_score, get_writing_service

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
    phase_name: str | None
    tutors_on: bool
    students: int
    items: int
    open_exceptions: int
    # Written work the AI has suggested a score for, waiting on the teacher.
    scores_to_confirm: int = 0


class TodayOut(BaseModel):
    coming_up: list[LessonSummary]
    finished: list[LessonSummary]


class PhaseIn(BaseModel):
    index: int


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
    phases = timeline_of(contract.timeline)
    live = session.status in (SessionStatus.OPEN.value, SessionStatus.PAUSED.value)
    phase = phases[session.phase_index] if live and session.phase_index < len(phases) else None
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
        title=contract.title,
        subject=contract.subject,
        class_label=klass.label if klass else "",
        status=session.status,
        plan_version=contract.version,
        scheduled_for=session.scheduled_for,
        opened_at=session.opened_at,
        closes_at=session.closes_at,
        closed_at=session.closed_at,
        phase_name=phase["name"] if phase else None,
        tutors_on=bool(phase and phase["tutors_on"]),
        students=students or 0,
        items=await db.scalar(
            select(func.count(ContractItem.id)).where(ContractItem.contract_id == contract.id)
        )
        or 0,
        open_exceptions=await db.scalar(
            select(func.count(Exception_.id)).where(
                Exception_.session_id == session.id, Exception_.status == "open"
            )
        )
        or 0,
        scores_to_confirm=await db.scalar(
            select(func.count(RubricScore.id)).where(
                RubricScore.session_id == session.id,
                RubricScore.status == ScoreStatus.SUGGESTED.value,
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


# ---------- booking and running ----------


@router.post("/lessons", response_model=LessonSummary, status_code=status.HTTP_201_CREATED)
async def book_lesson(body: LessonIn, teacher: CurrentTeacher, db: DbSession) -> LessonSummary:
    contract = await db.get(LessonContract, body.plan_version_id)
    if contract is None or contract.teacher_id != teacher.id or contract.archived_at is not None:
        raise HTTPException(status_code=404, detail="Lesson plan not found.")
    if contract.status != ContractStatus.ACTIVE.value:
        raise HTTPException(
            status_code=409, detail="Approve the lesson plan before using it with a class."
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
    session.status = SessionStatus.OPEN.value
    session.opened_at = now
    session.phase_index = 0
    session.phase_started_at = now
    # A class agent lesson runs for the length in its brief; older plans use their phases.
    minutes = (contract.brief or {}).get("duration_minutes") or total_minutes(contract.timeline)
    session.closes_at = now + timedelta(minutes=int(minutes))
    _log(db, teacher, TeacherAction.START_LESSON, session.id, detail={"students": len(students)})
    await db.commit()
    await broker.publish(session.id, {"type": "session_state", "status": session.status})
    return await _summary(db, session)


@router.post("/lessons/{lesson_id}/phase", response_model=LessonSummary)
async def change_phase(
    lesson_id: uuid.UUID, body: PhaseIn, teacher: CurrentTeacher, db: DbSession
) -> LessonSummary:
    """Move the class on. Tutors follow the phase, on the server."""
    session = await teacher_session(lesson_id, teacher, db)
    if session.status not in (SessionStatus.OPEN.value, SessionStatus.PAUSED.value):
        raise HTTPException(
            status_code=409, detail="Only a running lesson has phases to move through."
        )
    contract = await db.get(LessonContract, session.contract_id)
    phases = timeline_of(contract.timeline)
    if not 0 <= body.index < len(phases):
        raise HTTPException(status_code=422, detail="That phase isn't in this lesson's plan.")

    session.phase_index = body.index
    session.phase_started_at = datetime.now(UTC)
    _log(
        db,
        teacher,
        TeacherAction.CHANGE_PHASE,
        session.id,
        detail={"phase": phases[body.index]["name"], "tutors_on": phases[body.index]["tutors_on"]},
    )
    await db.commit()
    await broker.publish(session.id, {"type": "phase", "index": body.index})
    return await _summary(db, session)


# ---------- today and history ----------


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


# ---------- review ----------


class ReviewOut(BaseModel):
    lesson: LessonSummary
    item_list: list[dict]
    rungs: list[str]
    students: int
    started: int
    finished_all: int
    correct_answers: int
    times_needed_you: int
    progress: list[StudentProgress]


@router.get("/lessons/{lesson_id}/review", response_model=ReviewOut)
async def review(lesson_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> ReviewOut:
    """The whole class at a glance. Aggregate only, like the console."""
    session = await teacher_session(lesson_id, teacher, db)
    reg = await build_register(db, session)
    return ReviewOut(
        lesson=await _summary(db, session),
        item_list=[
            {"id": str(i.id), "ordinal": i.ordinal, "prompt": i.prompt, "kind": i.kind}
            for i in reg.items
        ],
        rungs=list((reg.contract.assistance_ladder or {}).get("rungs", [])),
        students=len(reg.progress),
        started=sum(
            1 for p in reg.progress if any(c.attempts or c.words or c.submitted for c in p.cells)
        ),
        finished_all=sum(1 for p in reg.progress if reg.items and p.correct == len(reg.items)),
        correct_answers=sum(p.correct for p in reg.progress),
        times_needed_you=sum(p.times_needed_you for p in reg.progress),
        progress=reg.progress,
    )


class TimelineEvent(BaseModel):
    at: datetime
    kind: str  # attempt | hint | ask | submitted | teacher_note | needed_you
    item_ordinal: int | None
    text: str
    correct: bool | None = None
    rung: str | None = None


class ScoreOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    pseudonym: str
    item_id: uuid.UUID
    item_ordinal: int
    prompt: str
    text: str
    status: str
    out_of: int
    suggested: dict
    suggested_total: int
    confirmed: dict | None
    confirmed_total: int | None
    comment: str | None


class WrittenWork(BaseModel):
    item_id: uuid.UUID
    ordinal: int
    prompt: str
    text: str
    submitted: bool
    score: ScoreOut | None


class StudentWorkOut(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    progress: StudentProgress
    written: list[WrittenWork]
    events: list[TimelineEvent]


async def _score_out(db, score: RubricScore) -> ScoreOut:
    student = await db.get(User, score.student_id)
    item = await db.get(ContractItem, score.item_id)
    submission = await db.get(EvidenceRecord, score.submission_record_id)
    return ScoreOut(
        id=score.id,
        student_id=score.student_id,
        pseudonym=student.pseudonym if student else "unknown",
        item_id=score.item_id,
        item_ordinal=item.ordinal if item else 0,
        prompt=item.prompt if item else "",
        text=str(submission.payload.get("text", "")) if submission else "",
        status=score.status,
        out_of=sum(int(c["max"]) for c in (item.rubric or {}).get("criteria", [])) if item else 0,
        suggested=score.suggested,
        suggested_total=score.suggested_total,
        confirmed=score.confirmed,
        confirmed_total=score.confirmed_total,
        comment=score.comment,
    )


@router.get("/lessons/{lesson_id}/students/{student_id}", response_model=StudentWorkOut)
async def student_work(
    lesson_id: uuid.UUID, student_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> StudentWorkOut:
    """One student's work in one lesson. Opening it is recorded, like a drill-down."""
    session = await teacher_session(lesson_id, teacher, db)
    reg = await build_register(db, session)
    progress = next((p for p in reg.progress if p.student_id == student_id), None)
    if progress is None:
        raise HTTPException(status_code=404, detail="Student not in this lesson.")
    ordinals = {i.id: i.ordinal for i in reg.items}

    records = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.student_id == student_id,
                EvidenceRecord.kind.in_(
                    [
                        EvidenceKind.ATTEMPT.value,
                        EvidenceKind.HINT.value,
                        EvidenceKind.TEACHER_FEEDBACK.value,
                        EvidenceKind.TUTOR_REQUEST.value,
                        EvidenceKind.SUBMISSION.value,
                    ]
                ),
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()
    events = []
    for r in records:
        if r.kind == EvidenceKind.ATTEMPT.value:
            events.append(
                TimelineEvent(
                    at=r.created_at,
                    kind="attempt",
                    item_ordinal=ordinals.get(r.item_id),
                    text=str(r.payload.get("answer", "")),
                    correct=r.correct,
                )
            )
        elif r.kind == EvidenceKind.HINT.value:
            events.append(
                TimelineEvent(
                    at=r.created_at,
                    kind="hint",
                    item_ordinal=ordinals.get(r.item_id),
                    text=str(r.payload.get("message", "")),
                    rung=r.payload.get("rung"),
                )
            )
        elif r.kind == EvidenceKind.TUTOR_REQUEST.value:
            ask = str(r.payload.get("ask", ""))
            events.append(
                TimelineEvent(
                    at=r.created_at,
                    kind="ask",
                    item_ordinal=ordinals.get(r.item_id),
                    text=str(r.payload.get("question") or ask),
                )
            )
        elif r.kind == EvidenceKind.SUBMISSION.value:
            events.append(
                TimelineEvent(
                    at=r.created_at,
                    kind="submitted",
                    item_ordinal=ordinals.get(r.item_id),
                    text=f"{r.payload.get('words', 0)} words",
                )
            )
        else:
            events.append(
                TimelineEvent(
                    at=r.created_at,
                    kind="teacher_note",
                    item_ordinal=None,
                    text=str(r.payload.get("text", "")),
                )
            )
    for e in (
        await db.scalars(
            select(Exception_).where(
                Exception_.session_id == session.id, Exception_.student_id == student_id
            )
        )
    ).all():
        events.append(
            TimelineEvent(
                at=e.created_at,
                kind="needed_you",
                item_ordinal=ordinals.get(e.item_id),
                text=e.summary,
            )
        )
    events.sort(key=lambda ev: ev.at)

    writing = get_writing_service()
    written: list[WrittenWork] = []
    for item in reg.items:
        if item.kind != ItemKind.WRITTEN_RESPONSE.value:
            continue
        score = await db.scalar(
            select(RubricScore).where(
                RubricScore.session_id == session.id,
                RubricScore.student_id == student_id,
                RubricScore.item_id == item.id,
            )
        )
        written.append(
            WrittenWork(
                item_id=item.id,
                ordinal=item.ordinal,
                prompt=item.prompt,
                text=await writing.latest_text(db, session.id, student_id, item.id),
                submitted=await writing.submission(db, session.id, student_id, item.id) is not None,
                score=await _score_out(db, score) if score else None,
            )
        )

    _log(db, teacher, TeacherAction.REVIEW_STUDENT, session.id, student_id)
    await db.commit()
    return StudentWorkOut(
        student_id=student_id,
        pseudonym=progress.pseudonym,
        progress=progress,
        written=written,
        events=events,
    )


# ---------- scores ----------


class ConfirmIn(BaseModel):
    # Criterion name -> points. Leave a criterion out to keep the suggestion.
    points: dict[str, int] | None = None
    comment: str | None = Field(default=None, max_length=1000)


@router.get("/lessons/{lesson_id}/scores", response_model=list[ScoreOut])
async def lesson_scores(
    lesson_id: uuid.UUID,
    teacher: CurrentTeacher,
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[ScoreOut]:
    session = await teacher_session(lesson_id, teacher, db)
    query = select(RubricScore).where(RubricScore.session_id == session.id)
    if status_filter:
        query = query.where(RubricScore.status == status_filter)
    scores = (await db.scalars(query.order_by(RubricScore.created_at))).all()
    return [await _score_out(db, s) for s in scores]


@router.post("/scores/{score_id}/confirm", response_model=ScoreOut)
async def confirm(
    score_id: uuid.UUID, body: ConfirmIn, teacher: CurrentTeacher, db: DbSession
) -> ScoreOut:
    """The teacher's mark. Only now does the student see a score."""
    score = await db.get(RubricScore, score_id)
    if score is None:
        raise HTTPException(status_code=404, detail="Score not found.")
    await teacher_session(score.session_id, teacher, db)
    item = await db.get(ContractItem, score.item_id)
    try:
        await confirm_score(
            db,
            score,
            teacher=teacher,
            rubric=list((item.rubric or {}).get("criteria", [])),
            points=body.points,
            comment=body.comment,
        )
    except WritingError as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from error
    _log(
        db,
        teacher,
        TeacherAction.CONFIRM_SCORE,
        score.session_id,
        score.student_id,
        {"suggested": score.suggested_total, "confirmed": score.confirmed_total},
    )
    await db.commit()
    return await _score_out(db, score)
