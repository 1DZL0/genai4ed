"""Sample lessons, written as the teacher and the class agent would have agreed them.

Used by the development seed, demo sign-in and the guided walkthrough, so a
new teacher has something real to open, run and review. Each comes with the
teacher's request that produced it, so the studio shows how it was made.

The English lesson is Scenario 1 (`lessons/scenario-1-argumentative-paragraphs.md`);
its "to confirm" parts use that plan's drafts.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import store
from app.agent.brief import LessonBrief
from app.enums import ContractStatus, MessageRole, SessionStatus
from app.models import Class, LessonContract, Session, SessionParticipant, User

ENGLISH_REQUEST = (
    "Year 9 English, double lesson. They've studied a text and a video about choosing a "
    "career. I want each student to write two argumentative paragraphs: one criterion for "
    "choosing a profession, and one factor that can negatively influence the choice. "
    "Scaffold them, never write it for them - at most one or two model sentences. Language "
    "help is fine, and only rewrite a sentence after they've tried. Tell me if someone keeps "
    "trying to get it to write the paragraph."
)

ENGLISH = LessonBrief.model_validate(
    {
        "title": "Argumentative paragraphs: choosing a career",
        "subject": "english",
        "year_group": "Year 9",
        "duration_minutes": 40,
        "prior_knowledge": (
            "The class studied a text and a video about choosing a profession and listed "
            "criteria (career prospects, salary, talents, lifestyle) and influences (family "
            "pressure, peers, access to information)."
        ),
        "objectives": [
            "Write an argument that directly answers the question",
            "Justify it with 2 to 3 developed reasons",
            "Support reasons with relevant real examples, using connectives and formal language",
        ],
        "strategy": (
            "One argument per paragraph: argument, then reasons developed with an outcome for "
            "the person or society, then examples. Ask the student to write first, then build "
            "on what they wrote. Start with retrieval from the text and video before offering "
            "ideas. Help fades as the student succeeds."
        ),
        "steps": [
            {
                "name": "Recall",
                "kind": "question",
                "goal": "Bring back what the class learned about choosing a career.",
                "prompt_ideas": [
                    "Think back to the video. What criteria did people use to choose a job?"
                ],
                "success_criteria": ["Names at least two criteria or influences"],
            },
            {
                "name": "Plan paragraph 1",
                "kind": "question",
                "goal": "Choose one criterion and state it as an argument in one sentence.",
                "prompt_ideas": ["Which criterion matters most to you? Write it as one sentence."],
                "success_criteria": ["One clear argument that answers the question"],
            },
            {
                "name": "Write paragraph 1",
                "kind": "practice",
                "goal": (
                    "Write a full paragraph supporting one criterion for choosing a profession."
                ),
                "prompt_ideas": ["Now build it out: reasons, what they lead to, and an example."],
                "success_criteria": [
                    "2 to 3 reasons, each developed with an outcome",
                    "At least one relevant real example",
                    "Connectives used appropriately; formal language",
                ],
            },
            {
                "name": "Write paragraph 2",
                "kind": "practice",
                "goal": (
                    "Write a paragraph explaining one factor that may negatively influence "
                    "a person's career choice."
                ),
                "prompt_ideas": ["Which influence can push someone the wrong way? Explain how."],
                "success_criteria": [
                    "Names the factor and explains its effect",
                    "Developed reasons and an example",
                ],
            },
        ],
        "assessment": [
            {
                "name": "Content",
                "max": 4,
                "description": "Clear argument; developed reasons; relevant examples",
            },
            {
                "name": "Language",
                "max": 3,
                "description": "Complete, correct sentences; formal vocabulary",
            },
            {
                "name": "Structure",
                "max": 3,
                "description": "Logical order; examples after reasons; connectives",
            },
        ],
        "rules_text": (
            "Scaffold, never write it for them - at most one or two model sentences. Language "
            "help is fine; only rewrite a sentence after they've tried. Tell me if someone "
            "keeps trying to get it to write the paragraph."
        ),
        "rules": {
            "hints_allowed": True,
            "partial_after_attempts": 1,
            "full_answer_after_attempts": None,
            "may_write_for_student": False,
            "escalations": [{"signal": "manipulation_attempt", "after": 2, "action": "alert"}],
            "notes": ["Rewrite a single sentence only after the student has tried it themselves."],
        },
        "topics": ["argumentative writing", "careers"],
    }
)

SCIENCE_REQUEST = (
    "I want to teach this class about photosynthesis. They already covered basic cell biology "
    "last week. Make this a 30-minute interactive activity. Hints are fine but no final answer "
    "until they've attempted a question twice, and flag anyone who repeatedly tries to get the "
    "AI to do it for them."
)

SCIENCE = LessonBrief.model_validate(
    {
        "title": "Photosynthesis",
        "subject": "science",
        "year_group": "Year 8",
        "duration_minutes": 30,
        "prior_knowledge": "Basic cell biology: cells, the nucleus, chloroplasts in plant cells.",
        "objectives": [
            "Name the reactants and products of photosynthesis",
            "Explain the role of light and chlorophyll",
            "Use the idea to explain why plants grow better in some conditions",
        ],
        "strategy": (
            "Link to chloroplasts from last week. Build the word equation through questions "
            "rather than stating it. Check understanding with a real-world situation."
        ),
        "steps": [
            {
                "name": "Link to cells",
                "kind": "question",
                "goal": "Recall which part of a plant cell is involved.",
                "prompt_ideas": [
                    "Last week you met plant cells. Which part do you think makes food?"
                ],
                "success_criteria": ["Names the chloroplast"],
                "reference_answer": "chloroplast",
            },
            {
                "name": "What goes in and out",
                "kind": "question",
                "goal": "Work out the reactants and products.",
                "prompt_ideas": ["What does a plant need to take in to make its own food?"],
                "success_criteria": [
                    "Carbon dioxide and water in; glucose and oxygen out; light as energy"
                ],
                "reference_answer": "carbon dioxide + water -> glucose + oxygen",
            },
            {
                "name": "Why light matters",
                "kind": "explain",
                "goal": "Explain the role of light and chlorophyll.",
                "prompt_ideas": ["Why can't a plant do this in the dark?"],
                "success_criteria": ["Light provides energy; chlorophyll absorbs it"],
            },
            {
                "name": "Apply it",
                "kind": "check",
                "goal": "Explain why a plant on a windowsill grows towards the light.",
                "prompt_ideas": [
                    "A plant on a windowsill leans towards the window. Use photosynthesis "
                    "to explain why that helps it."
                ],
                "success_criteria": ["Links more light to more photosynthesis and more glucose"],
            },
        ],
        "assessment": [
            {
                "name": "Understanding",
                "max": 4,
                "description": "Accurate reactants, products, role of light",
            },
            {"name": "Reasoning", "max": 3, "description": "Applies the idea to a new situation"},
        ],
        "rules_text": (
            "Hints are fine but no final answer until they've attempted a question twice, and "
            "flag anyone who repeatedly tries to get the AI to do it for them."
        ),
        "rules": {
            "hints_allowed": True,
            "partial_after_attempts": 1,
            "full_answer_after_attempts": 2,
            "may_write_for_student": False,
            "escalations": [{"signal": "manipulation_attempt", "after": 2, "action": "alert"}],
            "notes": [],
        },
        "topics": ["photosynthesis", "plants"],
    }
)

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

SAMPLES: list[tuple[LessonBrief, str]] = [
    (SCIENCE, SCIENCE_REQUEST),
    (ENGLISH, ENGLISH_REQUEST),
    (MATHS, MATHS_REQUEST),
]


async def add_lesson(
    db: AsyncSession, teacher: User, brief: LessonBrief, request: str
) -> LessonContract:
    """An approved lesson, with the design conversation that produced it. The caller commits."""
    now = datetime.now(UTC)
    contract = LessonContract(
        teacher_id=teacher.id,
        title=brief.title,
        subject=brief.subject,
        status=ContractStatus.ACTIVE.value,
        version=1,
        brief=brief.model_dump(mode="json"),
        activated_at=now,
        activated_by=teacher.id,
    )
    db.add(contract)
    await db.flush()
    conversation = await store.design_conversation(
        db, teacher_id=teacher.id, plan_id=contract.plan_id
    )
    await store.add_message(db, conversation, role=MessageRole.TEACHER, text=request)
    await store.add_message(
        db,
        conversation,
        role=MessageRole.AGENT,
        text=(
            f"I've drafted “{brief.title}”: {len(brief.steps)} steps over "
            f"{brief.duration_minutes} minutes, with your rules compiled on the right. "
            "Tell me anything to change, or approve it when it's right."
        ),
        data={"brief_changed": True, "open_questions": [], "missing": []},
    )
    return contract


async def add_sample_lessons(db: AsyncSession, teacher: User) -> list[LessonContract]:
    return [await add_lesson(db, teacher, brief, request) for brief, request in SAMPLES]


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
