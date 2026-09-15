"""Scenario 1: argumentative paragraphs, as an approved lesson plan.

Entered from `lessons/scenario-1-argumentative-paragraphs.md`. Parts that plan
marks "to confirm" (timings, rubric points, alert numbers) use its drafts; the
teacher checks them in the editor. Time reminders are not in the platform yet.
"""

from datetime import UTC, datetime

from sqlalchemy import select

from app.enums import ContractStatus, ItemKind, Rung, SessionStatus
from app.models import Class, ContractItem, LessonContract, Objective, Session, User

OBJECTIVE_CODE = "ENG-ARG-P"

TITLE = "Argumentative paragraphs: choosing a career"

TIMELINE = [
    {"name": "Explanation", "minutes": 15, "tutors_on": False},
    {"name": "Worked example", "minutes": 15, "tutors_on": False},
    {"name": "Writing with tutors", "minutes": 40, "tutors_on": True},
    {"name": "Class discussion", "minutes": 10, "tutors_on": False},
]

# Up to model sentences; the whole paragraph is never written for a student.
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

RUBRIC = {
    "criteria": [
        {
            "name": "Content",
            "max": 4,
            "description": (
                "A clear argument that answers the question; 2 to 3 reasons, each developed "
                "with an outcome; relevant real examples or evidence."
            ),
        },
        {
            "name": "Language",
            "max": 3,
            "description": (
                "Complete, grammatically correct sentences; accurate vocabulary suited to a "
                "formal essay; no slang."
            ),
        },
        {
            "name": "Structure",
            "max": 3,
            "description": (
                "Ideas in a logical order; examples after the reasons they support; "
                "connectives used appropriately and not too often."
            ),
        },
    ]
}

NOTES = """\
Structure of an argumentative paragraph (one argument per paragraph):
1. Argument: the first sentence answers the essay question.
2. Justification: 2 to 3 reasons, each developed with an outcome for the person or
   society (knowledge, skills, quality of life, the economy).
3. Examples: relevant examples from social, political or everyday life, or evidence.
Connectives ("for example", "therefore", "for this reason") used well, not too often.
Formal language: complete sentences, correct grammar, no slang.

What the class recalled from the text and video:
Criteria for choosing a profession - future career prospects (job security,
promotion); salary (financial security, quality of life); personal talents
(satisfaction, doing the job well); lifestyle (free time, stress, family life).
Influences - positive: access to information, education, family support;
negative: family pressure, peer influence.

Model paragraph on the board:
Money is an important criterion when choosing a profession. Firstly, a good salary
gives people financial security, because they can pay for a home, food and their
children's education without constant worry. Secondly, a higher income improves
quality of life, since it allows people to travel, take up hobbies and rest
properly. For example, engineers and doctors often earn enough to support a family
comfortably and still save for the future. For this reason, many young people
consider salary carefully before they decide on a career.
"""

ITEMS = [
    {
        "prompt": (
            "Write one paragraph that presents and supports one criterion for choosing "
            "a profession."
        ),
        "hint_templates": {
            Rung.DIAGNOSTIC_QUESTION: (
                "Think back to the text and video. Which criteria for choosing a profession "
                "were mentioned?"
            ),
            Rung.CONCEPTUAL_CUE: (
                "Look at the structure on the board: argument, reasons, examples. "
                "Which part is your paragraph missing?"
            ),
            Rung.TARGETED_HINT: (
                "Pick one reason and say what it changes in a person's life, "
                "such as their security, skills or free time."
            ),
            Rung.ANALOGOUS_EXAMPLE: (
                "In the video, one person chose engineering for its future career prospects. "
                "What did that give them?"
            ),
            Rung.PARTIAL_STEP: (
                "You could build on: \"For example, a doctor's salary can support a family "
                "and pay for their children's education.\""
            ),
        },
    },
    {
        "prompt": (
            "Write one paragraph that presents and explains one factor that may negatively "
            "influence a person's career choice."
        ),
        "hint_templates": {
            Rung.DIAGNOSTIC_QUESTION: (
                "Think back to the board. Which influences on career choice did the class "
                "call negative?"
            ),
            Rung.CONCEPTUAL_CUE: (
                "Your first sentence should name the factor. What should the next sentences "
                "explain about it?"
            ),
            Rung.TARGETED_HINT: (
                "Think about what happens when someone follows their family's wishes "
                "instead of their own talents."
            ),
            Rung.ANALOGOUS_EXAMPLE: (
                "Peer influence is one idea: a student might pick a course only because "
                "their friends did. What could follow from that?"
            ),
            Rung.PARTIAL_STEP: (
                'You could build on: "For this reason, a person may end up in a job that '
                'does not suit their talents."'
            ),
        },
    },
]


async def add_english_lesson(db, teacher: User, klass: Class | None = None) -> LessonContract:
    """The plan, approved and ready to use with any class.

    With a class, a lesson is also booked for today so the teacher can start it.
    The caller commits.
    """
    objective = await db.scalar(select(Objective).where(Objective.code == OBJECTIVE_CODE))
    if objective is None:
        objective = Objective(
            code=OBJECTIVE_CODE,
            title="Write a fully developed argumentative paragraph",
            description="An argument, justified with 2 to 3 reasons and supported by examples.",
        )
        db.add(objective)
        await db.flush()

    now = datetime.now(UTC)
    contract = LessonContract(
        teacher_id=teacher.id,
        class_id=None,
        title=TITLE,
        subject="english",
        status=ContractStatus.ACTIVE.value,
        version=1,
        timeline=TIMELINE,
        assistance_ladder=ASSISTANCE_LADDER,
        exception_thresholds=EXCEPTION_THRESHOLDS,
        material={"notes": NOTES, "images": []},
        activated_at=now,
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
                kind=ItemKind.WRITTEN_RESPONSE.value,
                prompt=spec["prompt"],
                expected_answer=None,
                rubric=RUBRIC,
                hint_templates={k.value: v for k, v in spec["hint_templates"].items()},
                misconception_vocabulary=[],
            )
        )

    if klass is not None:
        db.add(
            Session(
                contract_id=contract.id,
                class_id=klass.id,
                status=SessionStatus.SCHEDULED.value,
                scheduled_for=now,
            )
        )
        await db.flush()
    return contract
