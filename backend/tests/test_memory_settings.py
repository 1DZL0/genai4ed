"""What a teacher sets about memory: whether their lessons' tutor is told anything of a pupil's
earlier lessons, how far back, whether the lines a model wrote are among them, and whether the
end of the last lesson is repeated word for word. And the delete: what is remembered of their
pupils is removed, and nothing from before it is counted again. One pupil is taken through
lessons with a scripted tutor and the prompt the next lesson's tutor was handed is read back."""

from datetime import timedelta

from sqlalchemy import func, select, update

from app.agent import learner
from app.config import get_settings
from app.models import AgentTurn, EvidenceRecord, LearnerNote, Message
from tests.test_learner_note_written import EXAMPLE, about, review
from tests.test_memory_across_lessons import (
    BRACKETS,
    EARLIER,
    KNOWN,
    SIGN,
    end,
    first_lesson,
    line,
    next_lesson,
    shown_at_the_start,
)
from tests.test_what_the_record_shows import lesson, met

MEMORY = "/api/research/memory"
AS_IT_WAS = {
    "remember": True,
    "forget_after_days": None,
    "written_lines": True,
    "recent_lines": 0,
    "harder_questions": False,
    "adapt_to_student": False,
}
LEARNS = "How this student learns"
SAID = "The end of their last lesson in mathematics, word for word:"
POEM = BRACKETS.model_copy(update={"subject": "English", "topics": ["poetry"]})


async def set_memory(client, c, teacher=None, **changed):
    """The teacher saves their memory settings, with these changed from how they start."""
    r = await client.put(
        MEMORY, json={**AS_IT_WAS, **changed}, headers=c.headers(teacher or c.teacher)
    )
    assert r.status_code == 200, r.text
    return r.json()


async def delete_memory(client, c, teacher=None):
    r = await client.delete(MEMORY, headers=c.headers(teacher or c.teacher))
    assert r.status_code == 200, r.text
    return r.json()


async def days_pass(db, days: int):
    """Everything kept so far is made `days` older."""
    for kept in (LearnerNote, EvidenceRecord, Message):
        await db.execute(update(kept).values(created_at=kept.created_at - timedelta(days=days)))
    await db.commit()


async def a_second_lesson(db, client, c):
    """Alice gets the one step of the brackets lesson right, and the teacher ends it."""
    await next_lesson(db, c)
    await lesson(client, c, ("x = 5", met("x = 5")))
    await end(client, c)


# ---------- the settings themselves ----------


async def test_a_teacher_who_set_nothing_has_memory_as_it_always_was(client, three):
    await first_lesson(client, three)

    r = await client.get(MEMORY, headers=three.headers(three.teacher))

    assert r.status_code == 200, r.text
    assert r.json() == {"settings": AS_IT_WAS, "students": 1}


async def test_what_a_teacher_saves_is_what_they_read_back(client, three):
    saved = await set_memory(client, three, forget_after_days=7, recent_lines=7)

    read = (await client.get(MEMORY, headers=three.headers(three.teacher))).json()
    assert saved == read
    assert read["settings"] == {**AS_IT_WAS, "forget_after_days": 7, "recent_lines": 7}


async def test_a_setting_out_of_range_is_refused(client, three):
    teacher = three.headers(three.teacher)
    for wrong in ({"forget_after_days": 0}, {"forget_after_days": 366}, {"recent_lines": 21}):
        r = await client.put(MEMORY, json={**AS_IT_WAS, **wrong}, headers=teacher)
        assert r.status_code == 422, wrong


async def test_only_a_teacher_has_memory_settings(client, three, monkeypatch):
    monkeypatch.setattr(get_settings(), "research_key", "open-sesame")
    key = {"X-Research-Key": "open-sesame"}

    assert (await client.get(MEMORY, headers=three.headers(three.alice))).status_code == 404
    assert (await client.get(MEMORY, headers=key)).status_code == 404
    assert (await client.delete(MEMORY, headers=key)).status_code == 404


# ---------- remembering, on and off ----------


async def test_with_remembering_off_the_next_lessons_tutor_is_shown_none_of_it(db, client, three):
    await first_lesson(client, three)
    await set_memory(client, three, remember=False)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert [line(system, opening) for opening in (LEARNS, KNOWN, EARLIER)] == ["", "", ""]
    assert SIGN not in system


async def test_another_teachers_setting_does_not_change_this_teachers_lessons(db, client, three):
    await first_lesson(client, three)
    await set_memory(client, three, teacher=three.other_teacher, remember=False)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert SIGN in line(system, EARLIER)


async def test_each_turn_keeps_the_settings_it_was_made_under(db, client, three):
    await set_memory(client, three, recent_lines=7)
    await shown_at_the_start(client, three)

    turn = await db.scalar(select(AgentTurn).order_by(AgentTurn.created_at.desc()).limit(1))
    assert turn.context_manifest["memory_settings"] == {**AS_IT_WAS, "recent_lines": 7}


# ---------- forgetting after some days ----------


async def test_a_lesson_older_than_the_days_set_is_not_shown(db, client, three):
    await first_lesson(client, three)
    await days_pass(db, 10)
    await set_memory(client, three, forget_after_days=7)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert [line(system, opening) for opening in (LEARNS, KNOWN, EARLIER)] == ["", "", ""]


async def test_a_lesson_inside_the_days_set_is_still_shown(db, client, three):
    await first_lesson(client, three)
    await days_pass(db, 10)
    await set_memory(client, three, forget_after_days=30)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert SIGN in line(system, EARLIER)
    assert line(system, LEARNS) and line(system, KNOWN)


async def test_only_the_lessons_inside_the_days_set_are_counted(db, client, three):
    """A lesson 22 days ago and one 2 days ago, with 7 days set: the tutor is told what the
    second lesson found, counted from that lesson alone."""
    await first_lesson(client, three)
    await days_pass(db, 20)
    await a_second_lesson(db, client, three)
    await days_pass(db, 2)
    await set_memory(client, three, forget_after_days=7)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert "Equations with brackets" in line(system, EARLIER)
    assert "(from 1 step)" in line(system, LEARNS)
    assert SIGN not in system


async def test_hiding_removes_nothing_so_taking_the_days_off_shows_it_again(db, client, three):
    await first_lesson(client, three)
    await days_pass(db, 10)
    await set_memory(client, three, forget_after_days=7)
    await set_memory(client, three)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert SIGN in line(system, EARLIER)


# ---------- the lines a model wrote ----------


async def test_without_the_written_lines_the_tutor_is_shown_only_what_was_counted(
    db, client, three
):
    await first_lesson(client, three)
    await review(db, three, about(three.alice, EXAMPLE))
    await set_memory(client, three, written_lines=False)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert EXAMPLE not in system
    assert line(system, LEARNS)


async def test_a_written_line_older_than_the_days_set_is_not_shown(db, client, three):
    """The review wrote its line 22 days ago. A lesson 2 days ago made a new version of the
    note, which carries the line over; it is still as old as the review."""
    await first_lesson(client, three)
    await review(db, three, about(three.alice, EXAMPLE))
    await days_pass(db, 20)
    await a_second_lesson(db, client, three)
    await days_pass(db, 2)
    await set_memory(client, three, forget_after_days=7)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert EXAMPLE not in system
    assert line(system, LEARNS)


# ---------- the end of the last lesson, word for word ----------


async def test_the_last_lines_of_the_last_lesson_are_shown_with_the_tutors_replies(
    db, client, three
):
    await first_lesson(client, three)
    await set_memory(client, three, recent_lines=2)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert line(system, SAID) == (
        f"{SAID} "
        "Student: “x = 1 / 7” Tutor: “Not yet: what do you do with the 4?” "
        "Student: “x = 15 / 7” Tutor: “Not yet: what do you do with the 4?”"
    )


async def test_no_words_are_carried_over_unless_the_teacher_asks_for_them(db, client, three):
    await first_lesson(client, three)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert "x = 15 / 7" not in system


async def test_words_from_a_lesson_in_another_subject_are_not_carried_over(db, client, three):
    await first_lesson(client, three)
    await set_memory(client, three, recent_lines=7)
    await next_lesson(db, three, POEM)

    system = await shown_at_the_start(client, three)

    assert "x = 15 / 7" not in system


async def test_words_older_than_the_days_set_are_not_carried_over(db, client, three):
    await first_lesson(client, three)
    await days_pass(db, 10)
    await set_memory(client, three, recent_lines=7, forget_after_days=7)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert "x = 15 / 7" not in system


# ---------- deleting what is remembered ----------


async def test_deleting_removes_what_is_remembered_of_the_teachers_students(db, client, three):
    await first_lesson(client, three)

    after = await delete_memory(client, three)

    assert after == {"settings": AS_IT_WAS, "students": 0}
    assert await db.scalar(select(func.count(LearnerNote.id))) == 0


async def test_after_a_delete_the_next_lessons_tutor_is_shown_nothing(db, client, three):
    await first_lesson(client, three)
    await set_memory(client, three, recent_lines=7)
    await delete_memory(client, three)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert [line(system, opening) for opening in (LEARNS, KNOWN, EARLIER)] == ["", "", ""]
    assert "x = 15 / 7" not in system


async def test_what_was_deleted_is_not_counted_again_when_the_next_lesson_ends(db, client, three):
    await first_lesson(client, three)
    await delete_memory(client, three)

    await a_second_lesson(db, client, three)

    note = await learner.latest(db, three.alice.id)
    assert any("(from 1 step)" in said for said in note.worked_out)
    assert SIGN not in str(note.knows)


async def test_a_delete_leaves_the_lessons_themselves_as_they_were(db, client, three):
    await first_lesson(client, three)
    kept = await db.scalar(select(func.count(EvidenceRecord.id)))
    said = await db.scalar(select(func.count(Message.id)))

    await delete_memory(client, three)

    assert await db.scalar(select(func.count(EvidenceRecord.id))) == kept
    assert await db.scalar(select(func.count(Message.id))) == said


async def test_a_teacher_deletes_only_what_is_remembered_of_their_own_students(db, client, three):
    await first_lesson(client, three)
    await learner.write(db, student_id=three.outsider.id, written=[EXAMPLE])
    await db.commit()

    await delete_memory(client, three, teacher=three.other_teacher)
    assert await db.scalar(select(func.count(LearnerNote.id))) == 2

    await delete_memory(client, three)
    assert (await learner.latest(db, three.outsider.id)).written == [EXAMPLE]
    assert await learner.latest(db, three.alice.id) is None
