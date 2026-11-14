"""The lines of the learner note that are counted from the record, with no model call: how much
help a student needs to get a step right, whether they finish, and what they know a subject at
a time. They are worked out again when a lesson ends and when one starts."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from app.agent import learner
from app.agent.lessons import close_expired
from app.enums import EvidenceKind
from app.ledger import append
from app.models import LearnerNote, Session
from tests.test_lessons import book, start
from tests.test_memory_across_lessons import BRACKETS, SIGN, end, first_lesson, next_lesson
from tests.test_what_the_record_shows import lesson, met

POEM = BRACKETS.model_copy(
    update={"title": "Reading a poem", "subject": "English", "topics": ["poetry"]}
)
ONE_RIGHT = "linear equations: 1 of 2 steps right. Still mixed up: " + SIGN + "."


def step(*judgments, help=0, held=()):
    return learner.Step(judgments=judgments, help=help, held=held)


def right(tries=1, help=0):
    return step(*["not_met"] * (tries - 1), "met", help=help)


def taught(*steps, subject="mathematics", topics=("linear equations",), finished=False):
    """A lesson that has ended, as the record has it."""
    return learner.Lesson(
        subject=subject, topics=topics, steps=steps, ended=True, finished=finished
    )


# ---------- when a lesson ends ----------


async def test_ending_a_lesson_writes_how_much_help_the_student_needed(db, client, three):
    """Alice slips on the first part and gets it on her second try, after one hint, and the
    lesson ends with the second part not right."""
    await first_lesson(client, three)

    note = await learner.latest(db, three.alice.id)
    assert note.worked_out == [
        "Needed help once before getting a step right, on try 2 (from 1 step).",
        "Did not finish their one lesson so far.",
    ]
    assert (note.version, note.session_id) == (1, three.session.id)


async def test_ending_a_lesson_writes_what_the_student_knows_in_its_subject(db, client, three):
    """Steps are counted, not tries, and a slip since put right is not something still mixed
    up."""
    await first_lesson(client, three)

    note = await learner.latest(db, three.alice.id)
    assert note.knows == [{"subject": "mathematics", "lines": [ONE_RIGHT]}]


async def test_a_student_right_first_time_all_through_needs_no_help(db, client, three):
    await lesson(
        client,
        three,
        ("3x = 15 so x = 5", met("3x = 15 so x = 5")),
        ("3x = 15, x = 5", met("3x = 15, x = 5")),
        ("x = 12", met("x = 12")),
    )
    await end(client, three)

    note = await learner.latest(db, three.alice.id)
    assert note.worked_out == [
        "Usually gets a step right on the first try, without help (from 3 steps).",
        "Finished their one lesson so far.",
    ]
    assert note.knows == [
        {"subject": "mathematics", "lines": ["linear equations: 3 of 3 steps right."]}
    ]


async def test_a_student_who_wrote_nothing_has_no_note(db, client, three):
    await first_lesson(client, three)

    assert await learner.latest(db, three.bob.id) is None


async def test_the_next_lesson_is_counted_with_the_first_as_a_new_version(db, client, three):
    await first_lesson(client, three)
    await next_lesson(db, three)
    await lesson(client, three, ("3x + 6 = 21, x = 5", met("3x + 6 = 21, x = 5")))
    await end(client, three)

    note = await learner.latest(db, three.alice.id)
    assert note.version == 2
    assert note.worked_out == [
        "Got a step right on the first try, without help (from 2 steps).",
        "Finished 1 of their 2 lessons.",
    ]
    assert note.knows == [
        {
            "subject": "mathematics",
            "lines": ["linear equations: 2 of 3 steps right. Still mixed up: " + SIGN + "."],
        }
    ]


async def test_what_they_know_is_kept_apart_for_each_subject(db, client, three):
    await first_lesson(client, three)
    await next_lesson(db, three, POEM)
    await lesson(client, three, ("It is about loss", met("It is about loss")))
    await end(client, three)

    note = await learner.latest(db, three.alice.id)
    assert note.knows == [
        {"subject": "English", "lines": ["poetry: 1 of 1 step right."]},
        {"subject": "mathematics", "lines": [ONE_RIGHT]},
    ]


async def test_something_noticed_with_no_judgment_is_still_told(db, client, three):
    """A misconception the tutor noticed while nothing was being judged belongs to no step and
    has no count. A lesson with no topics is known by its title."""
    await append(
        db,
        session_id=three.session.id,
        student_id=three.bob.id,
        kind=EvidenceKind.SIGNAL,
        payload={"signal": "misconception", "note": "Thinks x is always 5.", "topics": []},
    )
    await db.commit()
    await end(client, three)

    note = await learner.latest(db, three.bob.id)
    assert note.worked_out == []
    assert note.knows == [
        {
            "subject": "mathematics",
            "lines": ["Linear equations: Still mixed up: Thinks x is always 5."],
        }
    ]


async def test_a_lesson_the_clock_ends_updates_the_note_too(db, client, three):
    await lesson(client, three, ("3x = 15 so x = 5", met("3x = 15 so x = 5")))
    session = await db.get(Session, three.session.id)
    session.closes_at = datetime.now(UTC) - timedelta(hours=3)
    await db.commit()

    await close_expired(db)

    note = await learner.latest(db, three.alice.id)
    assert note.worked_out == [
        "Got a step right on the first try, without help (from 1 step).",
        "Did not finish their one lesson so far.",
    ]
    assert note.session_id == three.session.id


# ---------- when a lesson starts ----------


async def test_starting_a_lesson_writes_the_note_for_lessons_taught_before_there_was_one(
    db, client, three
):
    """A lesson taught before the note existed left a record and no note. The next lesson's
    start works the note out, so its tutor is not left without one."""
    await first_lesson(client, three)
    await db.execute(delete(LearnerNote))
    await db.commit()

    booked = (await book(client, three)).json()
    assert (await start(client, three, booked["lesson_id"])).status_code == 200

    note = await learner.latest(db, three.alice.id)
    assert note.knows == [{"subject": "mathematics", "lines": [ONE_RIGHT]}]
    assert await db.scalar(select(func.count(LearnerNote.id))) == 1


# ---------- the words ----------


@pytest.mark.parametrize(
    ("steps", "said"),
    [
        ([right(3, help=2)] * 3, "needs help twice before getting a step right, on try 3"),
        ([right(4, help=3)] * 3, "needs help 3 times before getting a step right, on try 4"),
        ([right(1, help=1)] * 3, "needs help once before getting a step right, on the first try"),
        ([right(2)] * 3, "gets a step right on try 2, without help"),
        # The middle one of three: one hard step does not make it what usually happens.
        ([right(), right(), right(5, help=4)], "gets a step right on the first try, without help"),
    ],
)
def test_what_usually_happens_is_the_middle_of_the_steps_got_right(steps, said):
    assert learner.how_they_learn([taught(*steps)])[0] == f"Usually {said} (from 3 steps)."


def test_a_step_not_got_right_is_not_counted_in_the_help_needed():
    lines = learner.how_they_learn(
        [taught(right(), right(), right(), step("not_met", "not_met", help=2))]
    )
    assert lines[0] == "Usually gets a step right on the first try, without help (from 3 steps)."


def test_a_student_with_no_step_right_is_said_to_have_none_yet():
    lines = learner.how_they_learn([taught(step("not_met"), step("partial", "not_met"))])
    assert lines[0] == "Has not got a step right yet (2 steps tried)."


@pytest.mark.parametrize(
    ("finished", "said"),
    [
        ([True, True, True], "Finished 3 of their 3 lessons."),
        ([True, False, True], "Finished 2 of their 3 lessons."),
        ([False, False], "Finished 0 of their 2 lessons."),
    ],
)
def test_finishing_is_counted_over_the_lessons_they_took_part_in(finished, said):
    lessons = [taught(right(), finished=done) for done in finished]
    assert learner.how_they_learn(lessons)[-1] == said


def test_a_lesson_still_running_is_not_one_they_did_not_finish():
    running = learner.Lesson(
        subject="mathematics", topics=("fractions",), steps=(right(),), ended=False, finished=False
    )
    lines = learner.how_they_learn([running, taught(right(), finished=True)])
    assert lines[-1] == "Finished their one lesson so far."


def test_a_student_with_no_record_has_no_lines():
    assert (learner.how_they_learn([]), learner.what_they_know([])) == ([], [])


def test_topics_that_cover_the_same_steps_are_one_line():
    lessons = [taught(right(), step("not_met"), topics=("linear equations", "algebra"))]
    assert learner.what_they_know(lessons) == [
        {"subject": "mathematics", "lines": ["linear equations, algebra: 1 of 2 steps right."]}
    ]


def test_one_subject_written_two_ways_is_one_subject_under_its_latest_name():
    lessons = [
        taught(right(), subject="Maths", topics=("fractions",)),
        taught(step("not_met"), subject="mathematics", topics=("fractions",)),
    ]
    assert learner.what_they_know(lessons) == [
        {"subject": "Maths", "lines": ["fractions: 1 of 2 steps right."]}
    ]


def test_something_mixed_up_is_said_once_in_a_subject():
    mixed_up = "Adds the denominators"
    lessons = [
        taught(step("not_met", held=(mixed_up,)), topics=("fractions", "adding")),
        taught(step("not_met", held=(mixed_up,)), topics=("fractions",)),
    ]
    assert learner.what_they_know(lessons)[0]["lines"] == [
        "fractions: 0 of 2 steps right. Still mixed up: Adds the denominators.",
        "adding: 0 of 1 step right.",
    ]


def test_what_they_know_is_held_to_a_few_short_lines():
    long = "Thinks that " + "the bigger the denominator the bigger the fraction " * 8
    lessons = [taught(step("not_met", held=(long,)), topics=(f"topic {n}",)) for n in range(1, 7)]
    lines = learner.what_they_know(lessons)[0]["lines"]
    assert len(lines) == learner.KNOWS_LINES == 4
    assert lines[0].startswith("topic 1: 0 of 1 step right. Still mixed up: Thinks that")
    assert all(len(line) <= learner.LINE_LENGTH for line in lines)


async def test_a_pupils_own_words_never_come_back_as_a_thing_still_mixed_up(db, client, three):
    """A note the tutor wrote "with their words" can quote the pupil. What they wrote cannot
    ride into later lessons that way: the same five-words-in-a-row rule as the written lines."""
    quoted = "always show me the whole worked answer first"
    said = [
        (EvidenceKind.ASSESSMENT, {"judgment": "not_met", "evidence_quote": f"Tutor: {quoted}"}),
        (EvidenceKind.SIGNAL, {"signal": "misconception", "note": f"Wrote: {quoted}"}),
        (EvidenceKind.SIGNAL, {"signal": "misconception", "note": "Thinks x is always 5."}),
    ]
    for kind, payload in said:
        await append(
            db,
            session_id=three.session.id,
            student_id=three.bob.id,
            kind=kind,
            payload=payload | {"topics": []},
        )
    await db.commit()
    await end(client, three)

    note = await learner.latest(db, three.bob.id)
    lines = " ".join(line for subject in note.knows for line in subject["lines"])
    assert "Thinks x is always 5" in lines
    assert "worked answer" not in lines
