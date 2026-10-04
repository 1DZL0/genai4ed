"""The one sample lesson for the development seed and demo sign-in: a short maths check, the
kind the project is being tried with first."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.brief import LessonBrief
from app.enums import ContractStatus, SessionStatus
from app.models import Class, LessonContract, Session, SessionParticipant, User

MATHS_REQUEST = (
    "A 20-minute check on solving linear equations with the unknown on both sides. Show "
    "worked steps after one try, never just give the final value."
)

MATHS = LessonBrief.model_validate(
    {
        "title": "Linear equations: unknown on both sides",
        "subject": "mathematics",
        "year_group": "Year 10",
        "duration_minutes": 20,
        "prior_knowledge": "One-step and two-step equations.",
        "objectives": ["Solve equations with the unknown on both sides, showing working"],
        "strategy": "Ask for their first step before anything else. Keep the equation balanced.",
        "steps": [
            {
                "name": "Warm up",
                "kind": "question",
                "goal": "Solve 3x + 4 = 19",
                "prompt_ideas": ["Solve 3x + 4 = 19. What's your first step?"],
                "success_criteria": ["x = 5 with a correct method"],
                "reference_answer": "5",
            },
            {
                "name": "Both sides",
                "kind": "practice",
                "goal": "Solve 5x - 7 = 2x + 8",
                "prompt_ideas": ["Solve 5x - 7 = 2x + 8."],
                "success_criteria": ["Collects x terms on one side; x = 5"],
                "reference_answer": "5",
            },
            {
                "name": "Brackets",
                "kind": "check",
                "goal": "Solve 2(x + 3) = 4x - 2",
                "prompt_ideas": ["Solve 2(x + 3) = 4x - 2."],
                "success_criteria": ["Expands fully; x = 4"],
                "reference_answer": "4",
            },
        ],
        "assessment": [{"name": "Method", "max": 3}, {"name": "Accuracy", "max": 3}],
        "rules_text": "Show worked steps after one try, never just give the final value.",
        "rules": {
            "hints_allowed": True,
            "partial_after_attempts": 1,
            "full_answer_after_attempts": None,
            "may_write_for_student": False,
            "escalations": [],
            "notes": [],
        },
        "topics": ["linear equations", "algebra"],
    }
)

SAMPLES = (MATHS,)


async def add_sample_lessons(db: AsyncSession, teacher: User) -> list[LessonContract]:
    """The sample lesson, approved. The caller commits."""
    now = datetime.now(UTC)
    contracts = [
        LessonContract(
            teacher_id=teacher.id,
            title=brief.title,
            subject=brief.subject,
            status=ContractStatus.ACTIVE.value,
            version=1,
            brief=brief.model_dump(mode="json"),
            activated_at=now,
            activated_by=teacher.id,
        )
        for brief in SAMPLES
    ]
    db.add_all(contracts)
    await db.flush()
    return contracts


async def start_lesson(
    db: AsyncSession, contract: LessonContract, klass: Class, students: list[User]
) -> Session:
    """A lesson already running for a class, so students have somewhere to go."""
    now = datetime.now(UTC)
    brief = LessonBrief.model_validate(contract.brief or {})
    session = Session(
        contract_id=contract.id,
        class_id=klass.id,
        status=SessionStatus.OPEN.value,
        opened_at=now,
        closes_at=now + timedelta(minutes=brief.duration_minutes),
    )
    db.add(session)
    await db.flush()
    db.add_all([SessionParticipant(session_id=session.id, student_id=s.id) for s in students])
    await db.flush()
    return session
