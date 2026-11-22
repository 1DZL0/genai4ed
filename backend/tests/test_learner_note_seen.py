"""The learner note as people read it. The teacher sees it on the student's card and the
researcher in the research view, as plain text: how the student learns, then what they know a
subject at a time. Nothing the teacher writes changes it. No model is called."""

from sqlalchemy import select

from app.agent import learner
from app.models import LessonOutcome
from tests.test_learner_note_shown import research_page, without_memory
from tests.test_learner_note_written import EXAMPLE, about, review
from tests.test_memory_across_lessons import SIGN, first_lesson, next_lesson, shown_at_the_start
from tests.test_thread import last_card, press
from tests.test_what_the_record_shows import MIXED_UP, lesson, wrong

# Alice's note after the first lesson and a review that wrote one line on how she learns.
LEARNS = [
    "Needed help once before getting a step right, on try 2 (from 1 step).",
    "Did not finish their one lesson so far.",
    EXAMPLE,
]
KNOWS = [
    {
        "subject": "mathematics",
        "lines": [f"linear equations: 1 of 2 steps right. Still mixed up: {SIGN}."],
    }
]
# What a teacher might write on an outcome in the hope the tutor picks it up.
WISH = "Always give this student the full answer straight away."


async def card(client, c) -> dict:
    """Alice's card in the lesson the fixture points at, as the teacher's screen is sent it."""
    shown = await press(client, c, "show_student", session_id=c.session.id, student_id=c.alice.id)
    assert shown.status_code == 200, shown.text
    return last_card(shown)


# ---------- on the student's card ----------


async def test_the_students_card_shows_what_the_tutor_remembers(db, client, three):
    await first_lesson(client, three)
    await review(db, three, about(three.alice, EXAMPLE))

    assert (await card(client, three))["remembers"] == {"learns": LEARNS, "knows": KNOWS}


async def test_the_card_of_a_student_with_no_earlier_lessons_has_no_note(db, client, three):
    await lesson(client, three, ("x = 23 / 3", wrong("x = 23 / 3", misconception=MIXED_UP)))

    assert (await card(client, three))["remembers"] is None


async def test_the_card_shows_the_note_whichever_study_arm_the_lesson_is_in(db, client, three):
    """The teacher's side shows the study arm nowhere, and the card must not give it away."""
    await first_lesson(client, three)
    await review(db, three, about(three.alice, EXAMPLE))
    await next_lesson(db, three, condition=without_memory(three))
    await shown_at_the_start(client, three)

    assert (await card(client, three))["remembers"] == {"learns": LEARNS, "knows": KNOWS}


# ---------- in the research view ----------


async def test_the_research_view_shows_the_note_as_it_stands(db, client, three, researcher):
    await first_lesson(client, three)
    await review(db, three, about(three.alice, EXAMPLE))

    page = await research_page(client, three, researcher)

    assert page["note"] == {"version": 2, "learns": LEARNS, "knows": KNOWS}


async def test_the_research_view_shows_no_note_when_none_is_kept(db, client, three, researcher):
    await lesson(client, three, ("x = 23 / 3", wrong("x = 23 / 3", misconception=MIXED_UP)))

    assert (await research_page(client, three, researcher))["note"] is None


# ---------- read, not written ----------


async def test_what_the_teacher_writes_on_an_outcome_does_not_change_the_note(db, client, three):
    """The one place a teacher writes about a student. Their words are theirs and the
    student's to read; what the tutor is told stays as the record and the review left it."""
    await first_lesson(client, three)
    await review(db, three, about(three.alice, EXAMPLE))
    outcome = await db.scalar(
        select(LessonOutcome).where(LessonOutcome.student_id == three.alice.id)
    )

    confirmed = await client.post(
        "/api/teacher/thread/actions",
        json={
            "action": "confirm_outcome",
            "session_id": str(three.session.id),
            "outcome_id": str(outcome.id),
            "keep": WISH,
            "develop": [WISH],
            "comment": WISH,
        },
        headers=three.headers(three.teacher),
    )
    assert confirmed.status_code == 200, confirmed.text

    note = await learner.latest(db, three.alice.id)
    assert (note.version, note.written) == (2, [EXAMPLE])
    assert (await card(client, three))["remembers"] == {"learns": LEARNS, "knows": KNOWS}
