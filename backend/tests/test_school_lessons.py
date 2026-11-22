"""The school day's lessons: what the teacher types to the class agent for each one, the texts
and files they attach, and keeping a drafted lesson's brief so a later run can seed the very
same lesson. Nothing here calls the platform's API or a model; the seeding tests write to the
test database."""

import json
import re
import sys
import uuid

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent import materials
from app.agent.policy import PolicyRules, from_teachers_words
from app.models import LessonContract
from bench.school.cast import SUBJECTS
from bench.school.lessons import (
    GROUP_LESSONS,
    PART_ONE,
    TEXTS,
    load_brief,
    load_briefs,
    make_files,
    save_briefs,
    seed,
)
from tests.lessons import THREE

EVERY = [PART_ONE, *sum(GROUP_LESSONS.values(), [])]
POEM = GROUP_LESSONS["C"][0]
HISTORY, SCIENCE = GROUP_LESSONS["B"]
# The usual help rules, in the teacher's words, and the three lessons' changes to them.
HINTS = "hints any time"
WORKED = "a worked step after one wrong try"
NEVER = "never give the final answer"
NO_HINTS = "no hints, they must work it out themselves"
SAME = "ask everyone exactly the same questions"
AFTER_TWO = "they can see the answer after two wrong tries"
FREELY = "Pupils can move freely between the parts"
# No file name the run uploads holds one of these, in any case; nor does anything it uploads or
# types hold one as a word.
NOT_IN_NAMES = ("test", "bench", "ai", "simulated", "bot", "character")
NOT_IN_WORDS = re.compile(r"\b(tests?|bench\w*|ai|simulat\w*|bots?|characters?)\b", re.IGNORECASE)
LONG_DASHES = ("—", "–")


def clean(text: str) -> bool:
    return not NOT_IN_WORDS.search(text) and not any(dash in text for dash in LONG_DASHES)


# ---------- what the teacher types ----------


def test_every_lesson_says_its_subject_age_and_help_rules():
    for plan in [PART_ONE, *sum(GROUP_LESSONS.values(), [])]:
        assert str(plan.age) in plan.words and plan.subject.lower() in plan.words.lower()
        assert "worked step" in plan.words or "no hints" in plan.words
    assert "same questions" in GROUP_LESSONS["C"][0].words


def test_the_day_has_the_planned_lessons_in_each_group():
    assert (PART_ONE.key, PART_ONE.subject, PART_ONE.age) == ("full-class", "maths", 14)
    planned = {
        group: [(p.subject.lower(), p.age, p.attachments) for p in plans]
        for group, plans in GROUP_LESSONS.items()
    }
    assert planned == {
        "A": [("maths", 13, []), ("english", 13, []), ("maths", 13, [])],
        "B": [
            ("history", 16, ["source.txt"]),
            ("science", 16, ["worksheet.docx", "diagram.png"]),
        ],
        "C": [("english", 12, ["poem.txt"])],
    }
    topics = [
        ("linear equations", "unknown on both sides"),
        ("fractions and percentages of amounts",),
        ("persuasive writing techniques",),
        ("percentages of amounts", "follow-on"),
        ("causes of the first world war", "source"),
        ("photosynthesis",),
        ("imagery", "short poem"),
    ]
    for plan, words in zip(EVERY, topics, strict=True):
        assert all(w in plan.words.lower() for w in words), plan.key
    keys = [p.key for p in EVERY]
    assert len(set(keys)) == len(keys)
    # The cast picks each lesson's pupils by its subject.
    assert all(p.subject.lower() in SUBJECTS for p in EVERY)


def test_every_lesson_is_typed_as_a_teacher_would_with_an_age_not_a_year_group():
    for plan in EVERY:
        words = plan.words
        assert f"{plan.age} year olds" in words and "40 minutes" in words, plan.key
        # The class agent drafts only once it has an objective, the age and the length.
        assert "by the end they should be able to" in words.lower(), plan.key
        assert re.search(r"\b(three|four) (steps|parts)\b", words, re.IGNORECASE), plan.key
        assert not re.search(r"\byear \d", words, re.IGNORECASE), plan.key
        assert clean(words), plan.key


def test_three_lessons_change_the_usual_help_rules_and_the_rest_keep_them():
    assert NO_HINTS in POEM.words and SAME in POEM.words
    assert HINTS not in POEM.words and "worked step" not in POEM.words
    assert HINTS in HISTORY.words and WORKED in HISTORY.words and AFTER_TWO in HISTORY.words
    assert NEVER not in HISTORY.words
    assert FREELY in SCIENCE.words
    for plan in EVERY:
        if plan not in (POEM, HISTORY):
            assert HINTS in plan.words and WORKED in plan.words and NEVER in plan.words, plan.key
    # Each change is in its own lesson only, so the lessons can be told apart by it.
    for phrase, owner in ((NO_HINTS, POEM), (SAME, POEM), (AFTER_TWO, HISTORY), (FREELY, SCIENCE)):
        assert [p.key for p in EVERY if phrase in p.words] == [owner.key], phrase


def test_the_platform_reads_each_lessons_help_rules_as_the_teacher_meant_them():
    # The teacher's own rule sentences outrank the model's reading of them, read literally.
    meant = {POEM.key: (False, 1, None, False), HISTORY.key: (True, 1, 2, False)}
    meant[SCIENCE.key] = (True, 1, None, True)
    for plan in EVERY:
        rules = from_teachers_words(PolicyRules(), plan.words)
        read = (
            rules.hints_allowed,
            rules.partial_after_attempts,
            rules.full_answer_after_attempts,
            rules.free_movement,
        )
        assert read == meant.get(plan.key, (True, 1, None, False)), plan.key
    # A "never" shortly before "move freely" in one sentence rules moving freely out, and the
    # class agent may copy the rules shorter: so the two are never in the same sentence.
    for sentence in re.split(r"[.!?]", SCIENCE.words):
        assert not ("never" in sentence and "move freely" in sentence), sentence


def test_the_science_lesson_uses_its_labelled_diagram_and_asks_nobody_to_label_it(tmp_path):
    assert "say which go into the leaf and which come out, using the diagram" in SCIENCE.words
    worksheet, _ = make_files(tmp_path)
    text = materials.extract(worksheet.name, None, worksheet.read_bytes()).text
    for words in (SCIENCE.words, text):
        assert not re.search(r"\blabel\b", words, re.IGNORECASE), words


# ---------- what the teacher attaches ----------


def test_the_attached_texts_exist_and_say_nothing_about_a_test(tmp_path):
    made = {p.name for p in make_files(tmp_path)}
    for plan in EVERY:
        for name in plan.attachments:
            assert (TEXTS / name).is_file() or name in made, name
    texts = sorted(TEXTS.glob("*.txt"))
    assert {"poem.txt", "source.txt"} <= {p.name for p in texts}
    for name in made | {p.name for p in texts}:
        assert not any(word in name.lower() for word in NOT_IN_NAMES), name
    for path in texts:
        assert clean(path.read_text(encoding="utf-8")), path.name


def test_the_poem_is_wordsworths_first_stanza_and_the_source_is_a_short_plain_extract():
    poem = (TEXTS / "poem.txt").read_text(encoding="utf-8")
    assert "Wordsworth" in poem and "I Wandered Lonely as a Cloud" in poem
    assert poem.strip().splitlines()[-6:] == [
        "I wandered lonely as a cloud",
        "That floats on high o'er vales and hills,",
        "When all at once I saw a crowd,",
        "A host, of golden daffodils;",
        "Beside the lake, beneath the trees,",
        "Fluttering and dancing in the breeze.",
    ]
    source = (TEXTS / "source.txt").read_text(encoding="utf-8")
    assert 130 <= len(source.split()) <= 175
    for fact in ("28 June 1914", "Sarajevo", "Franz Ferdinand", "Serbia", "Belgium", "4 August"):
        assert fact in source, fact


def test_the_science_lesson_gets_a_word_worksheet_and_a_drawn_leaf_diagram(tmp_path):
    worksheet, diagram = make_files(tmp_path / "files")
    assert (worksheet.name, diagram.name) == tuple(SCIENCE.attachments)
    # The platform reads the worksheet as it reads a teacher's upload.
    text = materials.extract(worksheet.name, None, worksheet.read_bytes()).text
    assert "photosynthesis" in text.lower() and "word equation" in text and clean(text)
    with Image.open(diagram) as picture:
        assert picture.format == "PNG" and min(picture.size) >= 400
        # A drawing, not a blank page: the leaf, the sun, the arrows and the labels.
        assert len(picture.convert("RGB").getcolors(maxcolors=1 << 20)) > 4


def test_without_python_docx_the_worksheet_is_written_as_markdown(tmp_path, monkeypatch):
    # With None in its place, `import docx` fails as it would were python-docx not installed.
    monkeypatch.setitem(sys.modules, "docx", None)
    worksheet, diagram = make_files(tmp_path)
    assert (worksheet.name, diagram.name) == ("worksheet.md", "diagram.png")
    assert not (tmp_path / "worksheet.docx").exists()
    text = materials.extract(worksheet.name, None, worksheet.read_bytes()).text
    assert "Photosynthesis" in text and "word equation" in text and clean(text)


# ---------- keeping the drafted briefs ----------


def test_saved_briefs_come_back_as_they_went(tmp_path):
    maths = GROUP_LESSONS["A"][0].key
    briefs = {PART_ONE.key: THREE.model_dump(mode="json"), maths: {"title": "3/5 of £40"}}
    path = tmp_path / "run" / "briefs.json"
    save_briefs(path, briefs)
    assert load_briefs(path) == briefs
    assert list(json.loads(path.read_text(encoding="utf-8"))) == [PART_ONE.key, maths]


async def test_a_saved_brief_becomes_an_active_lesson_for_the_teacher(db, classroom):
    lesson_id = await seed(db, classroom.teacher.id, THREE.model_dump(mode="json"))
    contract = await db.get(LessonContract, lesson_id)
    assert contract.status == "active" and contract.teacher_id == classroom.teacher.id


async def test_a_seeded_lesson_is_committed_and_reads_back_as_it_was_saved(db, classroom):
    brief = THREE.model_dump(mode="json")
    # The runner's own session, which may expire what it holds on commit, and ids as text.
    async with async_sessionmaker(db.bind)() as other:
        lesson_id = await seed(other, str(classroom.teacher.id), brief)
    contract = await db.get(LessonContract, lesson_id)
    assert (contract.title, contract.subject, contract.version) == (
        "Linear equations",
        "mathematics",
        1,
    )
    assert contract.activated_by == classroom.teacher.id and contract.activated_at is not None
    assert await load_brief(db, str(lesson_id)) == brief


async def test_a_brief_the_platform_would_not_approve_is_not_seeded(db, classroom):
    brief = THREE.model_dump(mode="json")
    brief["steps"][0]["success_criteria"] = []
    with pytest.raises(ValueError, match="what counts as done for step 1"):
        await seed(db, classroom.teacher.id, brief)
    # Only the classroom's own lesson is there.
    assert await db.scalar(select(func.count()).select_from(LessonContract)) == 1


async def test_a_seeded_lesson_has_nothing_left_to_check(db, classroom):
    brief = THREE.model_dump(mode="json") | {"to_check": ["objectives", "step 2 criteria"]}
    lesson_id = await seed(db, classroom.teacher.id, brief)
    assert (await load_brief(db, lesson_id))["to_check"] == []


async def test_a_standing_guess_at_the_activity_is_kept_silently_as_on_approval(db, classroom):
    brief = THREE.model_dump(mode="json") | {"activity_kind": "solving equations"}
    brief["record"]["guess"] = "standing"
    lesson_id = await seed(db, classroom.teacher.id, brief)
    assert (await load_brief(db, lesson_id))["record"]["guess"] == "kept_silent"
    # A guess the teacher has already settled stays as they settled it.
    brief["record"]["guess"] = "corrected"
    lesson_id = await seed(db, classroom.teacher.id, brief)
    assert (await load_brief(db, lesson_id))["record"]["guess"] == "corrected"


async def test_reading_a_lesson_that_is_not_there_says_so(db):
    with pytest.raises(LookupError, match="no lesson"):
        await load_brief(db, uuid.uuid4())
