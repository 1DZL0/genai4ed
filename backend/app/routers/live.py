"""The teacher's view of a lesson while it runs and after it ends.

Meaningful signals first - who needs the teacher, who is struggling, what the
class keeps getting wrong - with the evidence one click away. Opening a
student's conversation is a deliberate, logged act.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent import classroom, store
from app.agent.brief import LessonBrief
from app.agent.llm import LLMClient, LLMError, get_llm_client
from app.auth import CurrentTeacher, DbSession, teacher_session
from app.enums import (
    Audience,
    EvidenceKind,
    MessageRole,
    ScoreStatus,
    SessionStatus,
    TeacherAction,
)
from app.events import broker
from app.ledger import append
from app.models import (
    Class,
    ClassInsight,
    EvidenceRecord,
    LearningState,
    LessonContract,
    RubricScore,
    SessionParticipant,
    TeacherAccessLog,
    User,
)

router = APIRouter(prefix="/api/teacher/live", tags=["live"])

Agent = Annotated[LLMClient, Depends(get_llm_client)]


class InsightOut(BaseModel):
    summary: str
    items: list[dict]
    created_at: datetime


class ChatLineOut(BaseModel):
    id: uuid.UUID
    role: str
    text: str
    created_at: datetime


class LiveOut(BaseModel):
    lesson_id: uuid.UUID
    design_id: uuid.UUID
    title: str
    subject: str
    class_label: str
    status: str
    opened_at: datetime | None
    closes_at: datetime | None
    steps: list[str]
    students: list[classroom.StudentState]
    alerts: list[classroom.Alert]
    patterns: list[classroom.Pattern]
    notable: list[classroom.Notable]
    insight: InsightOut | None
    conversation: list[ChatLineOut]


def _log(db, teacher, action: TeacherAction, session_id, student_id=None, detail=None):
    db.add(
        TeacherAccessLog(
            teacher_id=teacher.id,
            session_id=session_id,
            student_id=student_id,
            action=action.value,
            detail=detail or {},
        )
    )


async def _latest_insight(db, session_id) -> InsightOut | None:
    row = await db.scalar(
        select(ClassInsight)
        .where(ClassInsight.session_id == session_id)
        .order_by(ClassInsight.created_at.desc())
        .limit(1)
    )
    return (
        InsightOut(summary=row.summary, items=row.items, created_at=row.created_at) if row else None
    )


async def _live(db, session, teacher) -> LiveOut:
    p = await classroom.pulse(db, session)
    contract = await db.get(LessonContract, session.contract_id)
    klass = await db.get(Class, session.class_id)
    conversation = await store.classroom_conversation(
        db, teacher_id=teacher.id, session_id=session.id
    )
    lines = [
        ChatLineOut(id=m.id, role=m.role, text=m.text, created_at=m.created_at)
        for m in await store.messages(db, conversation.id, limit=40)
        if m.role in (MessageRole.TEACHER.value, MessageRole.AGENT.value)
    ]
    out = LiveOut(
        lesson_id=session.id,
        design_id=contract.id,
        title=p.brief.title or contract.title,
        subject=p.brief.subject or contract.subject,
        class_label=klass.label if klass else "",
        status=session.status,
        opened_at=session.opened_at,
        closes_at=session.closes_at,
        steps=[s.name for s in p.brief.steps],
        students=p.students,
        alerts=p.alerts,
        patterns=p.patterns,
        notable=p.notable,
        insight=await _latest_insight(db, session.id),
        conversation=lines,
    )
    await db.commit()
    return out


@router.get("/{lesson_id}", response_model=LiveOut)
async def live(lesson_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> LiveOut:
    return await _live(db, await teacher_session(lesson_id, teacher, db), teacher)


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/{lesson_id}/ask", response_model=LiveOut)
async def ask(
    lesson_id: uuid.UUID, body: AskIn, teacher: CurrentTeacher, db: DbSession, agent: Agent
) -> LiveOut:
    session = await teacher_session(lesson_id, teacher, db)
    _log(db, teacher, TeacherAction.ASK_AGENT, session.id)
    try:
        await classroom.ask_about_class(
            db, agent, session=session, teacher=teacher, text=body.text.strip()
        )
    except LLMError as exc:
        await db.commit()
        raise HTTPException(status_code=503, detail="The agent couldn't answer just now.") from exc
    return await _live(db, session, teacher)


@router.post("/{lesson_id}/insight", response_model=LiveOut)
async def insight(
    lesson_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession, agent: Agent
) -> LiveOut:
    session = await teacher_session(lesson_id, teacher, db)
    try:
        await classroom.refresh_insight(db, agent, session=session)
    except LLMError as exc:
        raise HTTPException(
            status_code=503, detail="The agent couldn't summarise just now."
        ) from exc
    return await _live(db, session, teacher)


# ---------- one student ----------


class StepProgress(BaseModel):
    name: str
    judgment: str | None
    attempts: int
    current: bool


class EvidenceLine(BaseModel):
    kind: str
    text: str
    detail: str
    at: datetime


class StudentLine(BaseModel):
    who: str  # student | agent | note (the student saw it) | teacher_only
    text: str
    at: datetime


class StudentDetail(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    state: str
    summary: list[str]
    steps: list[StepProgress]
    evidence: list[EvidenceLine]
    conversation: list[StudentLine] | None


async def _student(db, session, student_id: uuid.UUID) -> User:
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


@router.get("/{lesson_id}/students/{student_id}", response_model=StudentDetail)
async def student_detail(
    lesson_id: uuid.UUID,
    student_id: uuid.UUID,
    teacher: CurrentTeacher,
    db: DbSession,
    conversation: bool = False,
) -> StudentDetail:
    """A student's progress and the evidence behind it. `conversation=true` also
    returns what they and the agent said, and that is logged."""
    session = await teacher_session(lesson_id, teacher, db)
    student = await _student(db, session, student_id)
    contract = await db.get(LessonContract, session.contract_id)
    brief = LessonBrief.model_validate(contract.brief or {})
    state = await db.scalar(
        select(LearningState).where(
            LearningState.session_id == session.id, LearningState.student_id == student.id
        )
    )
    p = await classroom.pulse(db, session)
    label = next((s.state for s in p.students if s.student_id == student.id), "not_started")

    step_rows = (state.steps if state else []) or []
    steps = [
        StepProgress(
            name=s.name,
            judgment=(step_rows[i] or {}).get("judgment") if i < len(step_rows) else None,
            attempts=(step_rows[i] or {}).get("attempts", 0) if i < len(step_rows) else 0,
            current=bool(state) and i == state.step_index,
        )
        for i, s in enumerate(brief.steps)
    ]

    records = (
        await db.scalars(
            select(EvidenceRecord)
            .where(
                EvidenceRecord.session_id == session.id,
                EvidenceRecord.student_id == student.id,
                EvidenceRecord.kind.in_(
                    [
                        EvidenceKind.ASSESSMENT.value,
                        EvidenceKind.SIGNAL.value,
                        EvidenceKind.POLICY_EVENT.value,
                        EvidenceKind.STEP_CHANGE.value,
                        EvidenceKind.TEACHER_GUIDANCE.value,
                    ]
                ),
            )
            .order_by(EvidenceRecord.created_at)
        )
    ).all()
    evidence = []
    for r in records:
        pl = r.payload
        if r.kind == EvidenceKind.ASSESSMENT.value:
            text = f"{pl.get('step_name', 'Step')}: {str(pl.get('judgment', '')).replace('_', ' ')}"
            detail = pl.get("evidence_quote", "")
            if pl.get("misconception"):
                detail += f" (misconception: {pl['misconception']})"
        elif r.kind == EvidenceKind.SIGNAL.value:
            text = str(pl.get("signal", "")).replace("_", " ").capitalize()
            detail = f"{pl.get('note', '')} [{pl.get('action', '')}]"
        elif r.kind == EvidenceKind.POLICY_EVENT.value:
            text = "A reply was held back by your rules"
            detail = pl.get("reason", "")
        elif r.kind == EvidenceKind.STEP_CHANGE.value:
            text = "Finished the activity" if pl.get("completed") else "Moved to another step"
            detail = ""
        else:
            text = "Your guidance"
            detail = pl.get("text", "")
        evidence.append(EvidenceLine(kind=r.kind, text=text, detail=str(detail), at=r.created_at))

    summary: list[str] = []
    met = sum(1 for s in steps if s.judgment == "met")
    summary.append(f"{met} of {len(steps)} steps met so far.")
    if state and state.status == "completed":
        summary.append("Finished the activity.")
    elif state:
        summary.append(f"Now on “{steps[state.step_index].name}”." if steps else "")
    misconceptions = [
        r.payload["misconception"]
        for r in records
        if r.kind == EvidenceKind.ASSESSMENT.value and r.payload.get("misconception")
    ]
    if misconceptions:
        summary.append(f"Misconception seen: {misconceptions[-1]}.")
    held = sum(1 for r in records if r.kind == EvidenceKind.POLICY_EVENT.value)
    if held:
        summary.append(
            f"{held} agent repl{'y was' if held == 1 else 'ies were'} held back by your rules."
        )

    lines = None
    if conversation:
        _log(db, teacher, TeacherAction.TRANSCRIPT_DRILLDOWN, session.id, student.id)
        convo = await store.student_conversation(db, session_id=session.id, student_id=student.id)
        lines = [
            StudentLine(
                who={"student": "student", "agent": "agent"}.get(
                    m.role, "note" if m.audience == Audience.ALL.value else "teacher_only"
                ),
                text=m.text,
                at=m.created_at,
            )
            for m in await store.messages(db, convo.id)
        ]
    else:
        _log(db, teacher, TeacherAction.REVIEW_STUDENT, session.id, student.id)
    await db.commit()
    return StudentDetail(
        student_id=student.id,
        pseudonym=student.pseudonym,
        state=label,
        summary=[s for s in summary if s],
        steps=steps,
        evidence=evidence,
        conversation=lines,
    )


class GuideIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    show_to_student: bool = False


@router.post("/{lesson_id}/students/{student_id}/guide", response_model=StudentDetail)
async def guide(
    lesson_id: uuid.UUID,
    student_id: uuid.UUID,
    body: GuideIn,
    teacher: CurrentTeacher,
    db: DbSession,
) -> StudentDetail:
    """Tell the agent something about how to teach this student. It takes effect
    on the student's next turn; shown to the student too if the teacher chooses."""
    session = await teacher_session(lesson_id, teacher, db)
    student = await _student(db, session, student_id)
    await append(
        db,
        session_id=session.id,
        student_id=student.id,
        kind=EvidenceKind.TEACHER_GUIDANCE,
        payload={"text": body.text.strip(), "shown_to_student": body.show_to_student},
        provenance={"source": "teacher", "teacher_id": str(teacher.id)},
    )
    convo = await store.student_conversation(db, session_id=session.id, student_id=student.id)
    await store.add_message(
        db,
        convo,
        role=MessageRole.EVENT,
        audience=Audience.ALL if body.show_to_student else Audience.TEACHER,
        text=(
            f"From your teacher: {body.text.strip()}"
            if body.show_to_student
            else f"Teacher guidance for the agent: {body.text.strip()}"
        ),
    )
    _log(
        db,
        teacher,
        TeacherAction.GUIDE_STUDENT,
        session.id,
        student.id,
        {"shown_to_student": body.show_to_student},
    )
    await db.commit()
    await broker.publish(session.id, {"type": "guidance", "student": student.pseudonym})
    return await student_detail(lesson_id, student_id, teacher, db)


# ---------- after the lesson ----------


class OutcomeOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    pseudonym: str
    status: str
    suggested: dict
    suggested_total: int
    confirmed: dict | None
    confirmed_total: int | None
    comment: str | None
    out_of: int


class ReviewPageOut(BaseModel):
    live: LiveOut
    criteria: list[dict]
    outcomes: list[OutcomeOut]
    students_without_outcome: list[str]


async def _review(db, session, teacher) -> ReviewPageOut:
    view = await _live(db, session, teacher)
    contract = await db.get(LessonContract, session.contract_id)
    brief = LessonBrief.model_validate(contract.brief or {})
    out_of = sum(c.max for c in brief.assessment)
    scores = (
        await db.scalars(
            select(RubricScore)
            .where(RubricScore.session_id == session.id, RubricScore.item_id.is_(None))
            .order_by(RubricScore.created_at)
        )
    ).all()
    names = {s.student_id: s.pseudonym for s in view.students}
    outcomes = [
        OutcomeOut(
            id=s.id,
            student_id=s.student_id,
            pseudonym=names.get(s.student_id, "unknown"),
            status=s.status,
            suggested=s.suggested,
            suggested_total=s.suggested_total,
            confirmed=s.confirmed,
            confirmed_total=s.confirmed_total,
            comment=s.comment,
            out_of=out_of,
        )
        for s in scores
    ]
    have = {o.student_id for o in outcomes}
    return ReviewPageOut(
        live=view,
        criteria=[c.model_dump() for c in brief.assessment],
        outcomes=sorted(outcomes, key=lambda o: o.pseudonym),
        students_without_outcome=[
            s.pseudonym
            for s in view.students
            if s.student_id not in have and s.state != "not_started"
        ],
    )


@router.get("/{lesson_id}/review", response_model=ReviewPageOut)
async def review(lesson_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> ReviewPageOut:
    return await _review(db, await teacher_session(lesson_id, teacher, db), teacher)


@router.post("/{lesson_id}/outcomes", response_model=ReviewPageOut)
async def suggest(
    lesson_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession, agent: Agent
) -> ReviewPageOut:
    """The agent's summary of the lesson and a suggested outcome per student."""
    session = await teacher_session(lesson_id, teacher, db)
    if session.status != SessionStatus.CLOSED.value:
        raise HTTPException(status_code=409, detail="End the lesson before reviewing outcomes.")
    try:
        await classroom.suggest_outcomes(db, agent, session=session)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail="The agent couldn't review just now.") from exc
    return await _review(db, session, teacher)


class ConfirmIn(BaseModel):
    points: dict[str, int] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=1000)


@router.post("/{lesson_id}/outcomes/{outcome_id}/confirm", response_model=ReviewPageOut)
async def confirm(
    lesson_id: uuid.UUID,
    outcome_id: uuid.UUID,
    body: ConfirmIn,
    teacher: CurrentTeacher,
    db: DbSession,
) -> ReviewPageOut:
    """The teacher's decision. Their points replace the suggestion where given."""
    session = await teacher_session(lesson_id, teacher, db)
    score = await db.get(RubricScore, outcome_id)
    if score is None or score.session_id != session.id:
        raise HTTPException(status_code=404, detail="Outcome not found.")
    chosen = []
    for c in score.suggested.get("criteria", []):
        value = body.points.get(c["name"], c["points"])
        if not 0 <= value <= int(c["max"]):
            raise HTTPException(
                status_code=422, detail=f"{c['name']} must be between 0 and {c['max']}."
            )
        chosen.append({**c, "points": value})
    score.confirmed = {
        "criteria": chosen,
        "keep": score.suggested.get("keep", ""),
        "develop": score.suggested.get("develop", []),
    }
    score.confirmed_total = sum(c["points"] for c in chosen)
    score.comment = body.comment
    score.status = ScoreStatus.CONFIRMED.value
    score.confirmed_by = teacher.id
    score.confirmed_at = datetime.now(UTC)
    _log(
        db,
        teacher,
        TeacherAction.CONFIRM_SCORE,
        session.id,
        score.student_id,
        {"suggested": score.suggested_total, "confirmed": score.confirmed_total},
    )
    await db.commit()
    return await _review(db, session, teacher)
