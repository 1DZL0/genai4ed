"""Development seed.

Stands in for what a teacher would author: one lesson contract with a six-rung
ladder (full solution withheld), four linear-equation items, per-item hint
templates and a closed misconception vocabulary.

    uv run python -m app.seed          # seed an empty database
    uv run python -m app.seed --reset  # wipe seeded data first

Pseudonyms only. No real name belongs in this database.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.db import get_engine, get_sessionmaker
from app.enums import ContractStatus, Role, Rung, SessionStatus
from app.models import (
    Class,
    ContractItem,
    Enrolment,
    LessonContract,
    Objective,
    Session,
    SessionParticipant,
    User,
)
from app.security import hash_password, join_code_digest, new_join_code, new_password

OBJECTIVE_CODE = "ALG-L4"

# A reserved .test domain, so the demo account can never be a real inbox.
# The password and the students' join codes are generated and printed once.
DEMO_TEACHER_EMAIL = "teacher-01@genai4ed.test"

# The teacher's diagnosis vocabulary for this objective. The tutor may name a
# misconception only from this list, which is what keeps a diagnosis checkable.
MISCONCEPTIONS = [
    {
        "code": "sign_error_on_transfer",
        "label": "Moves a term across the equals sign without changing its sign",
    },
    {
        "code": "divides_one_term_only",
        "label": "Divides a single term by the coefficient instead of the whole side",
    },
    {
        "code": "combines_unlike_terms",
        "label": "Adds an x term to a constant as though they were like terms",
    },
    {
        "code": "expands_bracket_partially",
        "label": "Multiplies only the first term inside a bracket",
    },
    {"code": "arithmetic_slip", "label": "Correct method, arithmetic error"},
]

ITEMS = [
    {
        "prompt": "Solve for x:  3x + 4 = 19",
        "expected_answer": "5",
        "hint_templates": {
            Rung.DIAGNOSTIC_QUESTION: "What is being done to x, and in what order?",
            Rung.CONCEPTUAL_CUE: "Whatever you do to one side, do to the other.",
            Rung.TARGETED_HINT: "Deal with the +4 before the ×3.",
            Rung.ANALOGOUS_EXAMPLE: "For 2x + 1 = 9: subtract 1 to get 2x = 8, then divide by 2.",
            Rung.PARTIAL_STEP: "Subtracting 4 from both sides gives 3x = 15. Finish from there.",
        },
    },
    {
        "prompt": "Solve for x:  5x - 7 = 2x + 8",
        "expected_answer": "5",
        "hint_templates": {
            Rung.DIAGNOSTIC_QUESTION: "Which side would you rather collect the x terms on?",
            Rung.CONCEPTUAL_CUE: "Subtracting 2x from both sides keeps the equation balanced.",
            Rung.TARGETED_HINT: "When 2x moves across the equals sign it changes sign.",
            Rung.ANALOGOUS_EXAMPLE: "For 4x - 1 = x + 8: subtract x to get 3x - 1 = 8.",
            Rung.PARTIAL_STEP: "Collecting terms gives 3x = 15. Finish from there.",
        },
    },
    {
        "prompt": "Solve for x:  2(x + 3) = 4x - 2",
        "expected_answer": "4",
        "hint_templates": {
            Rung.DIAGNOSTIC_QUESTION: "What does the 2 outside the bracket multiply?",
            Rung.CONCEPTUAL_CUE: "The multiplier applies to every term inside the bracket.",
            Rung.TARGETED_HINT: "Expand fully before collecting terms.",
            Rung.ANALOGOUS_EXAMPLE: "3(x + 2) = 3x + 6, not 3x + 2.",
            Rung.PARTIAL_STEP: "Expanding gives 2x + 6 = 4x - 2. Finish from there.",
        },
    },
    {
        "prompt": "Solve for x:  7 - 2x = 3x - 8",
        "expected_answer": "3",
        "hint_templates": {
            Rung.DIAGNOSTIC_QUESTION: "What happens to -2x when it moves to the other side?",
            Rung.CONCEPTUAL_CUE: "Adding 2x to both sides removes it from the left.",
            Rung.TARGETED_HINT: "Watch the signs on both the x term and the constant.",
            Rung.ANALOGOUS_EXAMPLE: "For 5 - x = 2x - 1: add x to get 5 = 3x - 1.",
            Rung.PARTIAL_STEP: "Collecting terms gives 15 = 5x. Finish from there.",
        },
    },
]

# Six rungs, full solution deliberately withheld. This is the teacher's call,
# and it is data she can change without a deploy.
ASSISTANCE_LADDER = {
    "rungs": [
        Rung.ATTEMPT.value,
        Rung.DIAGNOSTIC_QUESTION.value,
        Rung.CONCEPTUAL_CUE.value,
        Rung.TARGETED_HINT.value,
        Rung.ANALOGOUS_EXAMPLE.value,
        Rung.PARTIAL_STEP.value,
    ],
    "max_rung": Rung.PARTIAL_STEP.value,
    "allow_full_solution": False,
}

EXCEPTION_THRESHOLDS = {
    "repeated_incorrect": 3,
    "repeated_misconception": 2,
    "confidence_floor": 0.45,
}

SEEDED_TABLES = (
    "auth_sessions",
    "teacher_access_log",
    "exceptions",
    "tutor_turns",
    "evidence_records",
    "session_participants",
    "sessions",
    "contract_items",
    "lesson_contracts",
    "enrolments",
    "classes",
    "objectives",
    "users",
)


async def _reset() -> None:
    async with get_sessionmaker()() as db:
        await db.execute(text(f"truncate {', '.join(SEEDED_TABLES)} cascade"))
        await db.commit()


async def add_sample_lesson(
    db, teacher: User, klass: Class, students: list[User]
) -> tuple[LessonContract, Session]:
    """The linear-equations lesson, activated, with a 50-minute session open.

    Used by the seed and by demo sign-in, which gives every new teacher their
    own copy. The caller commits.
    """
    objective = await db.scalar(select(Objective).where(Objective.code == OBJECTIVE_CODE))
    if objective is None:
        objective = Objective(
            code=OBJECTIVE_CODE,
            title="Solve linear equations with the unknown on both sides",
            description="Collect like terms across the equals sign and solve for x.",
        )
        db.add(objective)
        await db.flush()

    contract = LessonContract(
        teacher_id=teacher.id,
        class_id=klass.id,
        title="Linear equations - unknown on both sides",
        subject="mathematics",
        status=ContractStatus.ACTIVE.value,
        version=1,
        assistance_ladder=ASSISTANCE_LADDER,
        exception_thresholds=EXCEPTION_THRESHOLDS,
        material={
            "notes": "Teacher-supplied worked examples were shown on the board beforehand.",
            "images": [],
        },
        activated_at=datetime.now(UTC),
        activated_by=teacher.id,
    )
    db.add(contract)
    await db.flush()

    for ordinal, spec in enumerate(ITEMS, start=1):
        db.add(
            ContractItem(
                contract_id=contract.id,
                objective_id=objective.id,
                ordinal=ordinal,
                prompt=spec["prompt"],
                expected_answer=spec["expected_answer"],
                rubric=None,
                hint_templates={k.value: v for k, v in spec["hint_templates"].items()},
                misconception_vocabulary=MISCONCEPTIONS,
            )
        )

    now = datetime.now(UTC)
    session = Session(
        contract_id=contract.id,
        class_id=klass.id,
        status=SessionStatus.OPEN.value,
        opened_at=now,
        closes_at=now + timedelta(minutes=50),
    )
    db.add(session)
    await db.flush()
    db.add_all([SessionParticipant(session_id=session.id, student_id=s.id) for s in students])
    return contract, session


async def seed() -> None:
    async with get_sessionmaker()() as db:
        existing = await db.scalar(select(Objective).where(Objective.code == OBJECTIVE_CODE))
        if existing is not None:
            print("Database already seeded. Use --reset to wipe and re-seed.")
            return

        password = new_password()
        teacher = User(
            pseudonym="teacher-01",
            role=Role.TEACHER.value,
            email=DEMO_TEACHER_EMAIL,
            password_hash=hash_password(password),
        )
        codes = {f"10B-{i:02d}": new_join_code() for i in (1, 2, 3)}
        students = [
            User(
                pseudonym=pseudonym,
                role=Role.STUDENT.value,
                join_code_digest=join_code_digest(code),
            )
            for pseudonym, code in codes.items()
        ]
        db.add_all([teacher, *students])
        await db.flush()

        klass = Class(teacher_id=teacher.id, label="10B")
        db.add(klass)
        await db.flush()
        db.add_all([Enrolment(class_id=klass.id, student_id=s.id) for s in students])

        contract, session = await add_sample_lesson(db, teacher, klass, students)
        await db.commit()

        print("Seeded:")
        print(f"  teacher   {teacher.pseudonym}  sign in as {DEMO_TEACHER_EMAIL} / {password}")
        for pseudonym, code in codes.items():
            print(f"  student   {pseudonym}  join code {code}")
        print(f"  contract  {contract.title} ({len(ITEMS)} items, full solution withheld)")
        print(f"  session   {session.id}  closes {session.closes_at:%H:%M UTC}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the development database.")
    parser.add_argument(
        "--reset", action="store_true", help="truncate seeded tables before seeding"
    )
    args = parser.parse_args()
    if args.reset:
        await _reset()
    await seed()
    await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
