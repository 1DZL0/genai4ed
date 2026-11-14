"""The learner note: one note per student, every change kept as a new version, the latest
one the note, and all of it gone when the student is."""

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent import learner
from app.enums import EvidenceKind
from app.ledger import append
from app.models import LearnerNote

TWO_TRIES = ["Usually gets a step right on the second try."]
FIRST_TIME = ["Usually gets a step right first time."]
EXAMPLE = ["Does better when a worked example comes first."]


async def versions(db, student) -> int:
    return await db.scalar(
        select(func.count(LearnerNote.id)).where(LearnerNote.student_id == student.id)
    )


async def test_a_student_nothing_was_written_about_has_no_note(db, classroom):
    assert await learner.latest(db, classroom.alice.id) is None


async def test_the_latest_version_is_the_note_and_the_one_before_is_kept(db, classroom):
    alice = classroom.alice
    await learner.write(db, student_id=alice.id, worked_out=TWO_TRIES)
    await learner.write(db, student_id=alice.id, worked_out=FIRST_TIME)

    note = await learner.latest(db, alice.id)
    assert (note.version, note.worked_out) == (2, FIRST_TIME)
    assert await versions(db, alice) == 2


async def test_a_part_that_is_not_given_is_carried_over(db, classroom):
    alice = classroom.alice
    knows = [{"subject": "mathematics", "lines": ["Linear equations: 1 of 2 steps right."]}]
    await learner.write(db, student_id=alice.id, worked_out=TWO_TRIES, knows=knows)
    await learner.write(db, student_id=alice.id, written=EXAMPLE)

    note = await learner.latest(db, alice.id)
    assert (note.worked_out, note.written, note.knows) == (TWO_TRIES, EXAMPLE, knows)


async def test_writing_the_same_note_again_adds_no_version(db, classroom):
    alice = classroom.alice
    first = await learner.write(db, student_id=alice.id, worked_out=TWO_TRIES)
    again = await learner.write(db, student_id=alice.id, worked_out=TWO_TRIES)

    assert again.id == first.id
    assert await versions(db, alice) == 1


async def test_a_note_with_nothing_in_it_is_not_written(db, classroom):
    alice = classroom.alice
    assert await learner.write(db, student_id=alice.id, worked_out=[], knows=[]) is None
    assert await versions(db, alice) == 0


async def test_each_student_has_their_own_note(db, classroom):
    await learner.write(db, student_id=classroom.alice.id, worked_out=TWO_TRIES)
    await learner.write(db, student_id=classroom.bob.id, worked_out=FIRST_TIME)

    assert (await learner.latest(db, classroom.alice.id)).worked_out == TWO_TRIES
    bob = await learner.latest(db, classroom.bob.id)
    assert (bob.version, bob.worked_out) == (1, FIRST_TIME)


async def test_a_version_names_the_lesson_that_changed_the_note(db, classroom):
    alice = classroom.alice
    await learner.write(
        db, student_id=alice.id, session_id=classroom.session.id, worked_out=TWO_TRIES
    )

    assert (await learner.latest(db, alice.id)).session_id == classroom.session.id


async def test_writing_the_note_does_not_hold_up_the_students_own_turn(db, engine, classroom):
    """The note is written while a whole class's lesson ends or starts. A turn of the same
    student's in another lesson adds rows that point at the student, and must not wait for it."""
    alice = classroom.alice
    await learner.write(db, student_id=alice.id, worked_out=TWO_TRIES)  # not committed yet

    async with async_sessionmaker(engine)() as turn:
        await turn.execute(text("set local lock_timeout = '500ms'"))
        record = await append(
            turn, session_id=classroom.session.id, student_id=alice.id, kind=EvidenceKind.ASSESSMENT
        )
        assert record.student_id == alice.id
        await turn.rollback()


async def test_the_note_is_deleted_with_the_student(db, classroom):
    alice = classroom.alice
    await learner.write(db, student_id=alice.id, worked_out=TWO_TRIES)
    await learner.write(db, student_id=alice.id, worked_out=FIRST_TIME)
    await db.commit()

    await db.delete(alice)
    await db.commit()

    assert await versions(db, alice) == 0
