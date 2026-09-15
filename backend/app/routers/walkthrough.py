"""The guided walkthrough: one English lesson, run with a class of pretend students.

For showing the platform to people who won't sit in a classroom to see it. The
pretend students go through the real pipeline - the same drafts, tutor requests,
supervisor, attention queue and score suggestions as a real student - so what the
walkthrough shows is what the platform does, not a picture of it.

Only reachable in demo mode (`DEMO_SIGN_IN`), and only on the teacher's own lessons.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.auth import CurrentTeacher, DbSession, teacher_session
from app.config import get_settings
from app.enums import ContractStatus, ItemKind, SessionStatus, TutorAsk
from app.models import (
    Class,
    ContractItem,
    Enrolment,
    LessonContract,
    Session,
    SessionParticipant,
    User,
)
from app.routers.student import StudentSessionOut, build_student_view, request_teacher
from app.routers.teacher import _new_students, _pseudonym_prefix
from app.seed_english import TITLE as ENGLISH_TITLE
from app.seed_english import add_english_lesson
from app.timeline import timeline_of
from app.tutor.writing import WritingError, get_writing_service

router = APIRouter(prefix="/api/demo", tags=["walkthrough"])

CLASS_LABEL = "9B Walkthrough"
CLASS_SIZE = 6


# ---------- the pretend class ----------


@dataclass(frozen=True)
class Profile:
    key: str
    description: str


# One of each kind of student a teacher meets, in class-list order.
PROFILES = [
    Profile("confident", "Writes a strong paragraph and asks for feedback."),
    Profile("gets_going", "Asks for help before writing, then gets going."),
    Profile("language", "Writes informally and asks for language help."),
    Profile("stuck", "Keeps asking for help without writing anything."),
    Profile("hand_up", "Writes a little, then asks for the teacher."),
    Profile("quiet", "Writes slowly and doesn't hand in."),
]

TEXT = {
    "confident_draft": (
        "Salary is one of the most important criteria when choosing a profession. Firstly, a "
        "good salary gives people financial security, because they can pay for a home and food "
        "without constant worry."
    ),
    "confident_final": (
        "Salary is one of the most important criteria when choosing a profession. Firstly, a "
        "good salary gives people financial security, because they can pay for a home and food "
        "without constant worry. Secondly, it improves their quality of life, since they can "
        "travel and rest properly. For example, engineers often earn enough to support a family "
        "and still save for the future. For this reason, many young people think carefully "
        "about salary before they choose a career."
    ),
    "gets_going_start": "I think personal talents are important when you choose a job.",
    "gets_going_final": (
        "I think personal talents are important when you choose a job. If you are good at "
        "something you enjoy your work more and you do it well, because you feel confident. "
        "For example, my cousin is good at drawing and she became a designer."
    ),
    "language_draft": (
        "Lifestyle is super important cuz if your job is really stressful you wont have time "
        "for your family and stuff."
    ),
    "language_final": (
        "Lifestyle is an important criterion when choosing a profession, because a very "
        "stressful job leaves little time for family and rest. For example, doctors who work "
        "night shifts often miss time with their children. Therefore, people should consider "
        "lifestyle before they decide."
    ),
    "stuck_final": "Career prospects are important because you can get promoted.",
    "hand_up_draft": "Future career prospects matter when choosing a job.",
    "hand_up_final": (
        "Future career prospects matter when choosing a job. A job with good prospects gives "
        "people security, because they know they can keep working and earn more later. For "
        "example, jobs in technology are growing."
    ),
    "quiet_draft": "Salary is important because",
}


class CastMember(BaseModel):
    student_id: uuid.UUID
    pseudonym: str
    profile: str
    description: str


class WalkthroughOut(BaseModel):
    lesson_id: uuid.UUID
    plan_version_id: uuid.UUID
    class_label: str
    writing_phase: int
    cast: list[CastMember]


class SimulateIn(BaseModel):
    action: Literal["start_writing", "get_stuck", "hand_in"]


class SimulateOut(BaseModel):
    happened: list[str]


def _require_demo() -> None:
    if not get_settings().demo_sign_in:
        raise HTTPException(status_code=404, detail="Not found.")


async def _cast(db, session: Session) -> list[tuple[User, Profile]]:
    klass = await db.get(Class, session.class_id)
    prefix = _pseudonym_prefix(klass.label) + "-" if klass else ""
    students = (
        await db.scalars(
            select(User)
            .join(SessionParticipant, SessionParticipant.student_id == User.id)
            .where(SessionParticipant.session_id == session.id)
            .order_by(User.pseudonym)
        )
    ).all()
    mine = [s for s in students if s.pseudonym.startswith(prefix)][: len(PROFILES)]
    return list(zip(mine, PROFILES, strict=False))


def _writing_phase(contract: LessonContract) -> int:
    phases = timeline_of(contract.timeline)
    return next((i for i, p in enumerate(phases) if p["tutors_on"]), 0)


# ---------- endpoints ----------


@router.post("/walkthrough", response_model=WalkthroughOut)
async def begin(teacher: CurrentTeacher, db: DbSession) -> WalkthroughOut:
    """A fresh English lesson, booked for the walkthrough class. Run it again
    for a clean start; earlier runs stay as past lessons."""
    _require_demo()

    klass = await db.scalar(
        select(Class).where(Class.teacher_id == teacher.id, Class.label == CLASS_LABEL)
    )
    if klass is None:
        klass = Class(teacher_id=teacher.id, label=CLASS_LABEL)
        db.add(klass)
        await db.flush()
        await _new_students(db, klass, CLASS_SIZE)

    plan = await db.scalar(
        select(LessonContract).where(
            LessonContract.teacher_id == teacher.id,
            LessonContract.title == ENGLISH_TITLE,
            LessonContract.status == ContractStatus.ACTIVE.value,
            LessonContract.archived_at.is_(None),
        )
    )
    if plan is None:
        plan = await add_english_lesson(db, teacher)

    session = Session(
        contract_id=plan.id,
        class_id=klass.id,
        status=SessionStatus.SCHEDULED.value,
        scheduled_for=datetime.now(UTC),
    )
    db.add(session)
    await db.commit()

    prefix = _pseudonym_prefix(klass.label) + "-"
    students = (
        await db.scalars(
            select(User)
            .join(Enrolment, Enrolment.student_id == User.id)
            .where(Enrolment.class_id == klass.id)
            .order_by(User.pseudonym)
        )
    ).all()
    mine = [s for s in students if s.pseudonym.startswith(prefix)][: len(PROFILES)]
    return WalkthroughOut(
        lesson_id=session.id,
        plan_version_id=plan.id,
        class_label=klass.label,
        writing_phase=_writing_phase(plan),
        cast=[
            CastMember(
                student_id=s.id, pseudonym=s.pseudonym, profile=p.key, description=p.description
            )
            for s, p in zip(mine, PROFILES, strict=False)
        ],
    )


@router.post("/lessons/{lesson_id}/simulate", response_model=SimulateOut)
async def simulate(
    lesson_id: uuid.UUID, body: SimulateIn, teacher: CurrentTeacher, db: DbSession
) -> SimulateOut:
    """Move the pretend class on one stage, through the same services a real
    student's requests use."""
    _require_demo()
    session = await teacher_session(lesson_id, teacher, db)
    if session.status not in (SessionStatus.OPEN.value, SessionStatus.PAUSED.value):
        raise HTTPException(status_code=409, detail="Start the lesson first.")
    contract = await db.get(LessonContract, session.contract_id)
    phases = timeline_of(contract.timeline)
    tutors_on = phases[session.phase_index]["tutors_on"] if phases else True
    if not tutors_on and body.action != "hand_in":
        raise HTTPException(
            status_code=409, detail="Move the class to a phase with tutors on first."
        )
    item = await db.scalar(
        select(ContractItem)
        .where(
            ContractItem.contract_id == contract.id,
            ContractItem.kind == ItemKind.WRITTEN_RESPONSE.value,
        )
        .order_by(ContractItem.ordinal)
    )
    if item is None:
        raise HTTPException(status_code=409, detail="The walkthrough needs a writing task.")

    writing = get_writing_service()
    happened: list[str] = []

    async def draft(student: User, text: str) -> None:
        await writing.save_draft(db, session=session, student=student, item=item, text=text)

    async def ask(student: User, how: TutorAsk, text: str, note: str) -> None:
        reply = await writing.ask(
            db, session=session, contract=contract, student=student, item=item, ask=how, text=text
        )
        happened.append(f"{student.pseudonym} {note}. Tutor: “{reply.message}”")

    async def submit(student: User, text: str) -> None:
        await writing.submit(db, session=session, student=student, item=item, text=text)
        happened.append(f"{student.pseudonym} handed in task {item.ordinal}.")

    try:
        for student, profile in await _cast(db, session):
            key = profile.key
            if body.action == "start_writing":
                if key == "confident":
                    await draft(student, TEXT["confident_draft"])
                    await ask(
                        student, TutorAsk.FEEDBACK, TEXT["confident_draft"], "asked for feedback"
                    )
                elif key == "gets_going":
                    await ask(student, TutorAsk.STUCK, "", "said they were stuck before writing")
                    await ask(
                        student,
                        TutorAsk.STUCK,
                        TEXT["gets_going_start"],
                        "wrote a sentence and asked again",
                    )
                elif key == "language":
                    await ask(
                        student,
                        TutorAsk.LANGUAGE,
                        TEXT["language_draft"],
                        "asked for help with their language",
                    )
                elif key == "stuck":
                    await ask(student, TutorAsk.STUCK, "", "said they were stuck")
                elif key == "hand_up":
                    await draft(student, TEXT["hand_up_draft"])
                    happened.append(f"{student.pseudonym} started writing.")
                elif key == "quiet":
                    await draft(student, TEXT["quiet_draft"])
                    happened.append(f"{student.pseudonym} started writing, slowly.")
            elif body.action == "get_stuck":
                if key == "stuck":
                    await ask(student, TutorAsk.STUCK, "", "asked again, still without writing")
                    await ask(student, TutorAsk.STUCK, "", "asked a third time")
                elif key == "hand_up":
                    await request_teacher(session.id, student, db)
                    happened.append(f"{student.pseudonym} pressed “Ask my teacher for help”.")
            elif body.action == "hand_in":
                final = {
                    "confident": "confident_final",
                    "gets_going": "gets_going_final",
                    "language": "language_final",
                    "stuck": "stuck_final",
                    "hand_up": "hand_up_final",
                }.get(key)
                if final:
                    await submit(student, TEXT[final])
                else:
                    happened.append(f"{student.pseudonym} is still writing.")
    except WritingError as error:
        raise HTTPException(
            status_code=error.status,
            detail=f"{error.detail} Start the walkthrough again for a fresh lesson.",
        ) from error
    return SimulateOut(happened=happened)


@router.get("/lessons/{lesson_id}/cast", response_model=list[CastMember])
async def cast(lesson_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession) -> list[CastMember]:
    _require_demo()
    session = await teacher_session(lesson_id, teacher, db)
    return [
        CastMember(student_id=s.id, pseudonym=s.pseudonym, profile=p.key, description=p.description)
        for s, p in await _cast(db, session)
    ]


@router.get("/lessons/{lesson_id}/students/{student_id}/view", response_model=StudentSessionOut)
async def student_view(
    lesson_id: uuid.UUID, student_id: uuid.UUID, teacher: CurrentTeacher, db: DbSession
) -> StudentSessionOut:
    """What this student's screen shows right now, for the teacher's preview."""
    _require_demo()
    session = await teacher_session(lesson_id, teacher, db)
    admitted = await db.scalar(
        select(SessionParticipant.id).where(
            SessionParticipant.session_id == session.id,
            SessionParticipant.student_id == student_id,
        )
    )
    student = await db.get(User, student_id)
    if admitted is None or student is None:
        raise HTTPException(status_code=404, detail="Student not in this lesson.")
    return await build_student_view(db, session, student)
