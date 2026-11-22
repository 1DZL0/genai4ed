"""The lessons of the school day: what the teacher types to the class agent for each one, the
texts and files they attach, and the briefs the agent drafted, kept so that a later run can
teach the very same lessons.

A run drafts each lesson the way a teacher does: the teacher uploads the lesson's attachments,
then types its words. The words name the subject, the pupils' age (an age, never a year group),
the length (40 minutes), an objective, three or four steps and the help rules. Most lessons
have the usual rules (RULES); three change them: Group C's poem lesson gives no hints and asks
everyone the same questions, Group B's history lets pupils see the answer after two wrong
tries, and Group B's science lets them move freely between the parts.

A run that drafts reads each brief the agent drafted back from the database (load_brief) and
saves them all (save_briefs). A later run loads them (load_briefs) and seeds each one straight
into the database as an approved lesson (seed), so that another model meets the very same
lessons.

Nothing the platform is given says the day is a rehearsal: no file name, text or line of the
teacher's here names a test, a bench, AI, a simulation, a bot or a character.
"""

import copy
import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.brief import LessonBrief
from app.enums import ContractStatus
from app.models import LessonContract

# The texts lessons attach, kept with the code. make_files writes the science lesson's two
# files into a run's own folder.
TEXTS = Path(__file__).parent / "texts"

# The help rules most lessons are given, as the teacher types them.
RULES = "hints any time, a worked step after one wrong try, never give the final answer"


@dataclass
class LessonPlan:
    """A lesson as the teacher asks for it. `words` is what they type to the class agent; each
    attachment is a file name in TEXTS or one that make_files writes."""

    key: str
    subject: str
    age: int
    words: str
    attachments: list[str] = field(default_factory=list)


PART_ONE = LessonPlan(
    key="full-class",
    subject="maths",
    age=14,
    words=(
        "Hi, can you set up a maths lesson for my 14 year olds? It's 40 minutes, on solving "
        "linear equations with the unknown on both sides. By the end they should be able to "
        "solve equations like 5x + 3 = 2x + 18 and check the answer by putting it back in. "
        "They can already do two-step equations. Four steps please: a quick warm up with a "
        "two-step equation, then equations with x on both sides, then ones with brackets, "
        "then a short word problem they turn into an equation and solve. "
        f"Help rules: {RULES}."
    ),
)

GROUP_LESSONS: dict[str, list[LessonPlan]] = {
    "A": [
        LessonPlan(
            key="a-maths",
            subject="maths",
            age=13,
            words=(
                "Hello, I need a maths lesson for my 13 year olds on fractions and percentages "
                "of amounts. 40 minutes. By the end they should be able to find a fraction or "
                "a percentage of an amount without a calculator, like 3/5 of 40 or 15% of 60. "
                "Three steps: fractions of amounts, then percentages of amounts using 10% and "
                "5%, then some mixed money problems. "
                f"Help rules: {RULES}."
            ),
        ),
        LessonPlan(
            key="a-english",
            subject="English",
            age=13,
            words=(
                "Next an English lesson for the same class of 13 year olds: persuasive writing "
                "techniques, 40 minutes. By the end they should be able to spot persuasive "
                "techniques like rhetorical questions, the rule of three and emotive language, "
                "and use them in their own writing. Four steps: match each technique to a "
                "short example, find the techniques in a short persuasive letter, write a "
                "paragraph persuading the head teacher to start the school day later, then "
                "improve it by adding one more technique. "
                f"Help rules: {RULES}."
            ),
        ),
        LessonPlan(
            key="a-maths-2",
            subject="maths",
            age=13,
            words=(
                "A follow-on maths lesson for my 13 year olds: percentages of amounts again, "
                "picking up from last time. It's 40 minutes. By the end they should be able to "
                "find any percentage of an amount, like 35% of 80, and use it to work out a "
                "sale price. Three steps: a warm up on 10%, 5% and 1% of amounts, then "
                "building harder percentages like 35% out of those, then sale problems where "
                "they find the discount and take it off the price. "
                f"Help rules: {RULES}."
            ),
        ),
    ],
    "B": [
        LessonPlan(
            key="b-history",
            subject="history",
            age=16,
            words=(
                "I've attached a short source on the July Crisis of 1914. Please draft a "
                "history lesson from it for my 16 year olds on the causes of the First World "
                "War, 40 minutes. By the end they should be able to explain how the murder of "
                "Franz Ferdinand led to a war between the great powers, using evidence from "
                "the source. Four steps: put the main events in the source in order, pick out "
                "the causes it shows, like the alliances and Germany's war plan, explain how "
                "each event led to the next, then decide which cause mattered most and say "
                "why. Help rules: hints any time, a worked step after one wrong try, and they "
                "can see the answer after two wrong tries."
            ),
            attachments=["source.txt"],
        ),
        LessonPlan(
            key="b-science",
            subject="science",
            age=16,
            words=(
                "Science next for my 16 year olds: photosynthesis, 40 minutes. I've attached "
                "our worksheet and a leaf diagram. By the end they should be able to give the "
                "word equation for photosynthesis, say where in the leaf it happens and "
                "explain what limits its rate. Four parts: first say which go into the leaf "
                "and which come out, using the diagram, then write the word equation, then "
                "explain what chlorophyll and light do, and last the effect of light, carbon "
                "dioxide and temperature on the rate. "
                f"Help rules: {RULES}. Pupils can move freely between the parts."
            ),
            attachments=["worksheet.docx", "diagram.png"],
        ),
    ],
    "C": [
        LessonPlan(
            key="c-english",
            subject="English",
            age=12,
            words=(
                "I've attached the first stanza of I Wandered Lonely as a Cloud by Wordsworth. "
                "Can you draft an English lesson for my 12 year olds on the imagery in this "
                "short poem? 40 minutes. By the end they should be able to find a simile and "
                "personification in the poem and explain the picture each one creates. Three "
                "steps: find the simile in the first line and say what it compares, find "
                "where the daffodils are made to seem like people, then explain the mood the "
                "images create. Help rules: no hints, they must work it out themselves, never "
                "give them the answer, and ask everyone exactly the same questions."
            ),
            attachments=["poem.txt"],
        ),
    ],
}


# ---------- the science lesson's files ----------

_WORKSHEET_TITLE = "Photosynthesis"
_WORKSHEET_LINES = (
    "Use the leaf diagram to help you, and answer in full sentences.",
    "1. Which of sunlight, water, carbon dioxide, glucose and oxygen does the leaf take in, and "
    "which does it make?",
    "2. Write the word equation for photosynthesis.",
    "3. Photosynthesis happens in the chloroplasts. What does chlorophyll do, and why does the "
    "plant need light?",
    "4. Name three things that can limit the rate of photosynthesis. Explain how one of them "
    "changes the rate.",
)
_LEAF, _VEIN, _SUN, _SUN_EDGE = "#5aa845", "#2f6b23", "#f5c400", "#d08c00"
_TAKEN_IN, _MADE = "#1f5fbf", "#c0392b"
# Each arrow of the diagram: its label, where it starts and ends, its colour and where its
# label goes. The leaf lies between (230, 300) and (590, 300).
_ARROWS = (
    ("sunlight", (150, 160), (300, 240), _SUN_EDGE, (30, 185)),
    ("carbon dioxide", (720, 140), (525, 245), _TAKEN_IN, (560, 95)),
    ("water", (110, 530), (185, 360), _TAKEN_IN, (30, 515)),
    ("oxygen", (555, 325), (735, 425), _MADE, (680, 435)),
    ("glucose", (420, 400), (420, 505), _MADE, (440, 490)),
)


def make_files(folder: Path) -> list[Path]:
    """Writes the science lesson's two attachments into `folder` and returns their paths in the
    order the lesson lists them: the worksheet, then the leaf diagram.

    The worksheet is worksheet.docx, or worksheet.md when python-docx does not import, so the
    name returned says which was written, for the run log. With worksheet.md, attach the names
    returned rather than the lesson's own list."""
    folder.mkdir(parents=True, exist_ok=True)
    return [_worksheet(folder), _diagram(folder / "diagram.png")]


def _worksheet(folder: Path) -> Path:
    try:
        from docx import Document
    except ImportError:
        path = folder / "worksheet.md"
        lines = [f"# {_WORKSHEET_TITLE}", *_WORKSHEET_LINES]
        path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
        return path
    document = Document()
    document.add_heading(_WORKSHEET_TITLE, level=1)
    for line in _WORKSHEET_LINES:
        document.add_paragraph(line)
    path = folder / "worksheet.docx"
    document.save(str(path))
    return path


def _diagram(path: Path) -> Path:
    """A leaf in the sun, with arrows for what it takes in (sunlight, water, carbon dioxide)
    and what it makes (glucose, oxygen), each labelled."""
    from PIL import Image, ImageDraw, ImageFont

    picture = Image.new("RGB", (800, 560), "white")
    draw = ImageDraw.Draw(picture)
    font, heading = ImageFont.load_default(size=26), ImageFont.load_default(size=32)
    title = "Photosynthesis in a leaf"
    width = draw.textbbox((0, 0), title, font=heading)[2]
    draw.text(((800 - width) / 2, 20), title, fill="black", font=heading)
    # The leaf: two curves from its base to its tip, its stalk and its veins.
    top = [(230 + 9 * i, 300 - 115 * math.sin(math.pi * i / 40)) for i in range(41)]
    shape = top + [(x, 600 - y) for x, y in reversed(top)]
    draw.polygon(shape, fill=_LEAF, outline=_VEIN, width=4)
    draw.line([(230, 300), (590, 300)], fill=_VEIN, width=4)
    draw.line([(230, 300), (170, 480)], fill=_VEIN, width=9)
    for x in (300, 370, 440, 510):
        reach = 80 * math.sin(math.pi * (x + 40 - 230) / 360)
        draw.line([(x + 40, 300 - reach), (x, 300), (x + 40, 300 + reach)], fill=_VEIN, width=3)
    # The sun and its rays.
    draw.ellipse((52, 72, 128, 148), fill=_SUN, outline=_SUN_EDGE, width=3)
    for k in range(8):
        c, s = math.cos(k * math.pi / 4), math.sin(k * math.pi / 4)
        ray = [(90 + 48 * c, 110 + 48 * s), (90 + 64 * c, 110 + 64 * s)]
        draw.line(ray, fill=_SUN_EDGE, width=4)
    for label, start, end, colour, at in _ARROWS:
        _arrow(draw, start, end, colour)
        draw.text(at, label, fill="black", font=font)
    picture.save(path, format="PNG")
    return path


def _arrow(draw, start: tuple[float, float], end: tuple[float, float], colour: str) -> None:
    draw.line([start, end], fill=colour, width=5)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    head = [
        (end[0] - 20 * math.cos(angle + turn), end[1] - 20 * math.sin(angle + turn))
        for turn in (-0.45, 0.45)
    ]
    draw.polygon([end, *head], fill=colour)


# ---------- keeping the drafted lessons ----------


def save_briefs(path: Path, briefs: dict[str, dict]) -> None:
    """Writes the lessons' briefs to `path` as JSON, keyed by each lesson's key (replacing any
    file there), so that a later run can seed the very same lessons."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(briefs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_briefs(path: Path) -> dict[str, dict]:
    """The briefs save_briefs wrote, keyed by lesson key."""
    return json.loads(path.read_text(encoding="utf-8"))


async def seed(db: AsyncSession, teacher_id: uuid.UUID | str, brief: dict) -> uuid.UUID:
    """Writes a saved brief straight into the database as one of this teacher's approved
    lessons, as run_bench.seed_lesson does, and returns the lesson's id. It is committed, so a
    test API in another process sees it at once.

    The brief is read as the platform reads one and refused (ValueError) when the platform
    would not approve it. As on approval, nothing is left marked to check, and a guess at the
    activity still standing is kept without a word about it."""
    lesson = LessonBrief.model_validate(brief)
    gaps = lesson.missing()
    if gaps:
        raise ValueError("The saved lesson can't be approved: it needs " + ", ".join(gaps) + ".")
    lesson.to_check = []
    if lesson.guessing:
        lesson.record = lesson.record.model_copy(update={"guess": "kept_silent"})
    teacher = uuid.UUID(str(teacher_id))
    contract = LessonContract(
        plan_id=uuid.uuid4(),
        teacher_id=teacher,
        title=lesson.title.strip(),
        subject=lesson.subject.strip(),
        status=ContractStatus.ACTIVE.value,
        version=1,
        brief=lesson.model_dump(mode="json"),
        activated_at=datetime.now(UTC),
        activated_by=teacher,
    )
    db.add(contract)
    await db.flush()
    # Read before the commit, which may expire it: reading it after would mean a query.
    lesson_id = contract.id
    await db.commit()
    return lesson_id


async def load_brief(db: AsyncSession, lesson_id: uuid.UUID | str) -> dict:
    """The lesson's brief as the database holds it now (not as this session may remember it):
    what save_briefs keeps, and what the pupils' cheat sheet is made from. LookupError when
    there is no such lesson."""
    contract = await db.get(LessonContract, uuid.UUID(str(lesson_id)), populate_existing=True)
    if contract is None:
        raise LookupError(f"There is no lesson {lesson_id}.")
    return copy.deepcopy(contract.brief)
