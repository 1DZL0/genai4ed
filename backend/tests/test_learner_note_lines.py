"""The learner note as rows. Each line of a note is also kept as a row that names what kind of
line it is and holds the numbers it was counted from, so a person can read what is remembered
about a student a column at a time, without opening the note's lists."""

import importlib.util
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import func, select

from app.agent import learner
from app.enums import NoteCategory, NoteSource
from app.models import LearnerNote, LearnerNoteLine
from tests.test_learner_note_from_the_record import right, step, taught
from tests.test_learner_note_written import EXAMPLE, about, review
from tests.test_memory_across_lessons import SIGN, first_lesson


async def rows(db, student, version=None):
    """A student's note and its rows in the order they are read: the latest, or `version`."""
    note = await learner.latest(db, student.id)
    if version is not None:
        note = await db.scalar(
            select(LearnerNote).where(
                LearnerNote.student_id == student.id, LearnerNote.version == version
            )
        )
    found = await db.scalars(
        select(LearnerNoteLine)
        .where(LearnerNoteLine.note_id == note.id)
        .order_by(LearnerNoteLine.position)
    )
    return note, found.all()


# ---------- when a lesson ends ----------


async def test_ending_a_lesson_keeps_each_counted_line_as_a_row_with_its_numbers(db, client, three):
    """Alice gets one step right on her second try after one hint, and the lesson ends with the
    second step not right and one thing still mixed up."""
    await first_lesson(client, three)

    _, (needs, finishes, knows) = await rows(db, three.alice)
    assert (needs.category, needs.source) == (NoteCategory.NEED_FOR_ASSISTANCE, NoteSource.COUNTED)
    assert (needs.tries, needs.help, needs.steps_right, needs.steps_counted) == (2, 1, 1, 1)
    assert (finishes.category, finishes.lessons_finished, finishes.lessons_counted) == (
        NoteCategory.TASK_COMPLETION,
        0,
        1,
    )
    assert (knows.category, knows.subject, knows.topics) == (
        NoteCategory.TOPIC_KNOWLEDGE,
        "mathematics",
        "linear equations",
    )
    assert (knows.steps_right, knows.steps_counted, knows.mixed_up) == (1, 2, SIGN)


async def test_the_rows_say_what_the_note_says_in_the_order_a_lesson_reads_it(db, client, three):
    await first_lesson(client, three)
    await review(db, three, about(three.alice, EXAMPLE))

    note, lines = await rows(db, three.alice)
    said = [*note.worked_out, *note.written, *(s for known in note.knows for s in known["lines"])]
    assert [line.sentence for line in lines] == said
    assert [line.position for line in lines] == [1, 2, 3, 4]


async def test_a_line_the_review_wrote_is_a_row_with_nothing_counted(db, client, three):
    await first_lesson(client, three)
    await review(db, three, about(three.alice, EXAMPLE))

    _, lines = await rows(db, three.alice)
    [wrote] = [line for line in lines if line.source == NoteSource.REVIEW]
    assert (wrote.category, wrote.sentence) == (NoteCategory.REVIEW_NOTE, EXAMPLE)
    assert (wrote.tries, wrote.help, wrote.steps_counted, wrote.subject) == (None, None, None, None)


async def test_a_part_carried_over_keeps_its_numbers_in_the_new_version(db, client, three):
    """The review changes only the lines it writes. The counted lines carried into the new
    version are rows there too, with the numbers they had."""
    await first_lesson(client, three)
    await review(db, three, about(three.alice, EXAMPLE))

    note, (needs, *_) = await rows(db, three.alice)
    assert note.version == 2
    assert (needs.category, needs.tries, needs.help) == (NoteCategory.NEED_FOR_ASSISTANCE, 2, 1)


async def test_the_version_before_keeps_its_own_rows(db, client, three):
    await first_lesson(client, three)
    await review(db, three, about(three.alice, EXAMPLE))

    _, before = await rows(db, three.alice, version=1)
    _, now = await rows(db, three.alice)
    assert (len(before), len(now)) == (3, 4)


async def test_the_rows_are_deleted_with_the_student(db, client, three):
    await first_lesson(client, three)
    assert await db.scalar(select(func.count(LearnerNoteLine.id))) > 0

    await db.delete(three.alice)
    await db.commit()

    assert await db.scalar(select(func.count(LearnerNoteLine.id))) == 0


# ---------- the counting on its own ----------


def test_help_needed_is_kept_as_the_try_and_the_help_of_the_middle_step():
    steps = (right(tries=1), right(tries=2, help=1), right(tries=3, help=2), step("not_met"))
    needs, _ = learner.learning_lines([taught(*steps)])
    assert (needs.tries, needs.help, needs.steps_right, needs.steps_counted) == (2, 1, 3, 3)


def test_no_step_right_yet_is_none_right_of_the_steps_tried():
    needs, _ = learner.learning_lines([taught(step("not_met"), step("partial", "not_met"))])
    assert (needs.tries, needs.help, needs.steps_right, needs.steps_counted) == (None, None, 0, 2)


def test_lessons_finished_are_kept_as_a_count_of_the_lessons_that_ended():
    lessons = [taught(right(), finished=True), taught(right()), taught(right(), finished=True)]
    _, finishes = learner.learning_lines(lessons)
    assert (finishes.lessons_finished, finishes.lessons_counted) == (2, 3)


def test_everything_still_mixed_up_on_a_topic_is_kept_whole_beside_the_line():
    lessons = [taught(step("not_met", held=("Adds before multiplying", SIGN)), right())]
    [knows] = learner.knowing_lines(lessons)
    assert (knows.steps_right, knows.steps_counted) == (1, 2)
    assert knows.mixed_up == f"Adds before multiplying; {SIGN}"


# ---------- the notes written before there were rows ----------

MIGRATION = Path(__file__).parents[1] / "alembic/versions/d0e1f2a3b4c5_learner_note_lines.py"


def written_before():
    """The migration that gives the notes already written their rows."""
    spec = importlib.util.spec_from_file_location("learner_note_lines", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def filled(columns):
    """The columns of a line that hold something, apart from who made it and its sentence."""
    return {
        name: value
        for name, value in columns.items()
        if value is not None and name not in ("source", "sentence")
    }


def test_a_note_written_before_gets_the_numbers_its_sentences_give():
    """The numbers read back out of a sentence are the ones it was counted from."""
    before = written_before()
    lessons = [
        [taught(right(tries=1), right(tries=2, help=1), right(tries=3, help=3), finished=True)],
        [taught(right(tries=2, help=1))],
        [taught(right())],
        [taught(step("not_met"), step("partial", "not_met"))],
        [taught(right(), finished=True), taught(right()), taught(right(), finished=True)],
    ]
    for taught_so_far in lessons:
        for line in learner.learning_lines(taught_so_far):
            assert filled(before._learns(line.sentence)) == filled(asdict(line))


def test_a_note_written_before_gets_what_was_mixed_up_out_of_its_sentence():
    before = written_before()
    lessons = [taught(step("not_met", held=("Adds before multiplying.", SIGN)), right())]
    [line] = learner.knowing_lines(lessons)

    assert filled(before._knows(line.subject, line.sentence)) == filled(asdict(line))


def test_a_sentence_in_no_form_the_server_writes_gets_a_row_with_no_numbers():
    before = written_before()
    assert before._learns("Got there in the end.") == {"category": "need_for_assistance"}
    assert before._knows("mathematics", "Knows fractions well.") == {
        "category": "topic_knowledge",
        "subject": "mathematics",
    }
