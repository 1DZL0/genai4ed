"""A pupil's second lesson: what the tutor is shown about the first. One pupil is taken through
two lessons with a scripted tutor, and the prompt the second lesson's tutor was handed is read
back. No model is called."""

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import study
from app.agent import memory
from app.agent.brief import LessonBrief
from app.enums import ContractStatus, EvidenceKind, SessionStatus
from app.ledger import append
from app.models import AgentTurn, EvidenceRecord, LessonContract, Session, SessionParticipant
from tests.lessons import THREE
from tests.test_what_the_record_shows import MIXED_UP, OPEN, lesson, met, turn, wrong

SIGN = "Moves a term across the equals sign without changing its sign"

BRACKETS = LessonBrief.model_validate(
    {
        "title": "Equations with brackets",
        "subject": "mathematics",
        "age": 13,
        "activity": "answers",
        "duration_minutes": 30,
        "objectives": ["Solve equations that have brackets"],
        "steps": [
            {
                "name": "Expand first",
                "kind": "question",
                "goal": "Solve 3(x + 2) = 21",
                "prompt_ideas": ["Solve 3(x + 2) = 21"],
                "success_criteria": ["x = 5 with the bracket expanded"],
                "reference_answer": "5",
            }
        ],
        "topics": ["linear equations"],
    }
)


async def end(client, c):
    """The teacher ends the lesson the fixture points at."""
    r = await client.post(
        f"/api/teacher/sessions/{c.session.id}/state",
        params={"to": SessionStatus.CLOSED.value},
        headers=c.headers(c.teacher),
    )
    assert r.status_code == 200, r.text


async def next_lesson(db, c, brief=BRACKETS, *, condition=None):
    """A second lesson, started for the same class. The fixture now points at it. `condition`
    is the study arm the pupils were given for it."""
    now = datetime.now(UTC)
    contract = LessonContract(
        teacher_id=c.teacher.id,
        title=brief.title,
        subject=brief.subject,
        status=ContractStatus.ACTIVE.value,
        version=1,
        brief=brief.model_dump(mode="json"),
        activated_at=now,
        activated_by=c.teacher.id,
    )
    db.add(contract)
    await db.flush()
    session = Session(
        contract_id=contract.id,
        class_id=c.klass.id,
        status=SessionStatus.OPEN.value,
        opened_at=now,
        closes_at=now + timedelta(minutes=30),
    )
    db.add(session)
    await db.flush()
    db.add_all(
        [
            SessionParticipant(session_id=session.id, student_id=s.id, condition=condition or {})
            for s in (c.alice, c.bob)
        ]
    )
    await db.commit()
    c.contract, c.session = contract, session


async def shown_at_the_start(client, c) -> str:
    """Alice opens the lesson the fixture points at. Returns the prompt the tutor was handed."""
    c.tutor._replies.append(OPEN)
    r = await client.post(f"/api/learn/{c.session.id}/start", headers=c.headers(c.alice))
    assert r.status_code == 200, r.text
    return c.tutor.calls[-1]["system"]


def line(system: str, opening: str) -> str:
    """The one line of the prompt that starts with `opening`, or "" when there is none."""
    return next((row for row in system.splitlines() if row.startswith(opening)), "")


EARLIER = "From this student's earlier lessons:"
KNOWN = "What this student knows in"
WARM_UP = "In “Linear equations”, “Warm up” (Solve 3x + 4 = 19)"


async def recalled_in_the_next_lesson(db, client, c) -> str:
    """The teacher ends the lesson, a second one starts, and Alice opens it. Returns the line
    about her earlier lessons that the second lesson's tutor was handed."""
    await end(client, c)
    await next_lesson(db, c)
    return line(await shown_at_the_start(client, c), EARLIER)


async def judged(db, c, index, *, name, judgment="met"):
    """One judgment of Alice written straight into the record of the lesson the fixture
    points at."""
    return await append(
        db,
        session_id=c.session.id,
        student_id=c.alice.id,
        kind=EvidenceKind.ASSESSMENT,
        payload={
            "topics": ["linear equations"],
            "step_index": index,
            "step_name": name,
            "judgment": judgment,
        },
    )


async def first_lesson(client, c):
    """Alice slips on the first part and puts it right, then is twice wrong on the second
    with the same idea mixed up, and the teacher ends the lesson there."""
    await lesson(
        client,
        c,
        ("x = 23 / 3", wrong("x = 23 / 3", misconception=MIXED_UP)),
        ("3x = 15 so x = 5", met("3x = 15 so x = 5", task="Solve 5x - 7 = 2x + 8")),
        ("x = 1 / 7", wrong("x = 1 / 7", misconception=SIGN)),
        ("x = 15 / 7", wrong("x = 15 / 7", misconception=SIGN)),
    )
    await end(client, c)


async def test_the_second_lessons_tutor_is_shown_what_the_first_lesson_found(db, client, three):
    await first_lesson(client, three)
    await next_lesson(db, three)
    system = await shown_at_the_start(client, three)

    assert line(system, EARLIER) == (
        f"{EARLIER} "
        "In “Linear equations”, “Both sides” (Solve 5x - 7 = 2x + 8): not right yet after "
        f"2 tries. Still mixed up: {SIGN}. "
        "In “Linear equations”, “Warm up” (Solve 3x + 4 = 19): right on try 2."
    )


async def test_a_slip_put_right_in_the_first_lesson_is_not_carried_into_the_second(
    db, client, three
):
    await first_lesson(client, three)
    await next_lesson(db, three)
    system = await shown_at_the_start(client, three)
    assert MIXED_UP not in system


async def test_what_is_still_mixed_up_is_said_once(db, client, three):
    """Each judgment that names a misconception also raises a signal with the same words."""
    await first_lesson(client, three)
    await next_lesson(db, three)
    system = await shown_at_the_start(client, three)
    assert line(system, EARLIER).count(SIGN) == 1


async def test_the_tutor_reads_words_not_the_records_own_codes(db, client, three):
    await first_lesson(client, three)
    await next_lesson(db, three)
    system = await shown_at_the_start(client, three)
    assert "not_met" not in line(system, EARLIER) + line(system, KNOWN)


async def test_a_part_got_right_at_once_is_right_first_time(db, client, three):
    await lesson(client, three, ("3x = 15 so x = 5", met("3x = 15 so x = 5")))
    assert await recalled_in_the_next_lesson(db, client, three) == (
        f"{EARLIER} {WARM_UP}: right first time."
    )


async def test_being_asked_why_after_a_right_answer_is_not_a_second_try(db, client, three):
    asked_why = turn(
        "Yes. Why take the 4 away first?",
        student_attempted=True,
        assessment={"judgment": "met", "evidence_quote": "x = 5"},
    )
    await lesson(
        client,
        three,
        ("x = 5", asked_why),
        ("to leave 3x by itself", met("to leave 3x by itself")),
    )
    assert await recalled_in_the_next_lesson(db, client, three) == (
        f"{EARLIER} {WARM_UP}: right first time."
    )


async def test_a_wrong_idea_noticed_without_a_judgment_is_recalled(db, client, three):
    noticed = turn(
        "What happens to the sign when a term crosses over?",
        signals=[{"kind": "misconception", "note": SIGN}],
    )
    await lesson(client, three, ("is it like moving house", noticed))
    assert await recalled_in_the_next_lesson(db, client, three) == (
        f"{EARLIER} {WARM_UP}: Still mixed up: {SIGN}."
    )


async def test_one_wrong_idea_put_two_ways_in_one_turn_is_said_in_the_judgments_words(
    db, client, three
):
    both = {
        **wrong("x = 1 / 7", misconception=SIGN),
        "signals": [{"kind": "misconception", "note": "Forgets that the sign flips"}],
    }
    await lesson(client, three, ("x = 1 / 7", both))
    assert await recalled_in_the_next_lesson(db, client, three) == (
        f"{EARLIER} {WARM_UP}: not right yet after 1 try. Still mixed up: {SIGN}."
    )


TAXI = (
    "Adds the £3 starting charge to the £15 fare instead of taking it off, treating it as "
    "extra on top of the total"
)
TAXI_BEFORE = (
    "Added the £3 starting charge to the total fare instead of taking it away, as if it came "
    "on top of the £15."
)


async def test_one_wrong_idea_named_on_two_tries_in_other_words_is_said_once(db, client, three):
    """From the lesson of 8 November: the tutor named one mistake on two tries running, each
    time in new words, and both were kept. The latest wording is the one told."""
    await lesson(
        client,
        three,
        ("15 + 3 = 18", wrong("15 + 3 = 18", misconception=TAXI_BEFORE)),
        ("18 / 2 = 9", wrong("18 / 2 = 9", misconception=TAXI)),
    )
    assert await recalled_in_the_next_lesson(db, client, three) == (
        f"{EARLIER} {WARM_UP}: not right yet after 2 tries. Still mixed up: {TAXI}."
    )


async def test_two_different_wrong_ideas_on_one_part_are_both_said(db, client, three):
    await lesson(
        client,
        three,
        ("x = 23 / 3", wrong("x = 23 / 3", misconception=MIXED_UP)),
        ("x = 1 / 7", wrong("x = 1 / 7", misconception=SIGN)),
    )
    assert await recalled_in_the_next_lesson(db, client, three) == (
        f"{EARLIER} {WARM_UP}: not right yet after 2 tries. Still mixed up: {SIGN}; {MIXED_UP}."
    )


def test_notes_too_short_to_compare_are_one_finding_only_when_they_are_the_same():
    assert memory._same_finding("x is y", "X is y")
    assert not memory._same_finding("x is y", "y is z")


async def test_a_long_question_is_cut_short(db, client, three):
    long = "Solve 3x + 4 = 19" + ", then say what you did at each line and why" * 4
    steps = [THREE.steps[0].model_copy(update={"goal": long})]
    await next_lesson(db, three, THREE.model_copy(update={"steps": steps}))
    await lesson(client, three, ("3x = 15 so x = 5", met("3x = 15 so x = 5")))
    recalled = await recalled_in_the_next_lesson(db, client, three)
    [question] = re.findall(r"“Warm up” \((.*)\): right first time\.$", recalled)
    assert question.startswith("Solve 3x + 4 = 19, then say what you did")
    assert question.endswith("…")
    assert len(question) <= 120


async def test_only_the_eight_latest_parts_are_recalled(db, client, three):
    for title in ("First", "Second", "Third"):
        await next_lesson(db, three, THREE.model_copy(update={"title": title}))
        for index, step in enumerate(THREE.steps):
            await judged(db, three, index, name=step.name)
    await db.commit()
    await next_lesson(db, three)
    recalled = line(await shown_at_the_start(client, three), EARLIER)
    assert recalled.count("In “") == 8
    assert recalled.startswith(f"{EARLIER} In “Third”, “Brackets”")
    assert "In “First”, “Both sides”" in recalled
    assert "In “First”, “Warm up”" not in recalled


async def test_a_judgment_on_a_part_the_lesson_does_not_list_still_reads_as_a_sentence(
    db, client, three
):
    await judged(db, three, 7, name="Extra")
    await db.commit()
    await next_lesson(db, three)
    assert line(await shown_at_the_start(client, three), EARLIER) == (
        f"{EARLIER} In “Linear equations”, “Extra”: right first time."
    )


async def test_the_turn_records_every_record_behind_what_the_tutor_was_shown(db, client, three):
    await first_lesson(client, three)
    first = three.session.id
    await next_lesson(db, three)
    await shown_at_the_start(client, three)
    read = (
        await db.scalars(
            select(EvidenceRecord.id).where(
                EvidenceRecord.session_id == first,
                EvidenceRecord.kind.in_([EvidenceKind.ASSESSMENT.value, EvidenceKind.SIGNAL.value]),
            )
        )
    ).all()
    opening = (await db.scalars(select(AgentTurn).order_by(AgentTurn.created_at.desc()))).first()
    assert len(read) == 7
    assert set(opening.context_manifest["retrieved_ids"]) == {str(i) for i in read}


async def test_a_pupil_with_no_earlier_lesson_is_shown_no_memory(db, client, three):
    system = await shown_at_the_start(client, three)
    assert (line(system, EARLIER), line(system, KNOWN)) == ("", "")


async def test_a_lesson_on_something_else_recalls_nothing(db, client, three):
    await first_lesson(client, three)
    poem = BRACKETS.model_copy(update={"subject": "English", "topics": ["poetry"]})
    await next_lesson(db, three, poem)
    system = await shown_at_the_start(client, three)
    assert line(system, EARLIER) == ""


# ---------- the same subject, whatever it was called and however it was tagged ----------


async def recalled_from(db, client, c, earlier: dict, later: dict) -> str:
    """Alice gets the warm-up right in a lesson that differs from the shared one as `earlier`
    says, then opens one that differs from the brackets lesson as `later` says. Returns the
    line about her earlier lessons that the later lesson's tutor was handed."""
    await next_lesson(db, c, THREE.model_copy(update=earlier))
    await lesson(client, c, ("3x = 15 so x = 5", met("3x = 15 so x = 5")))
    await end(client, c)
    await next_lesson(db, c, BRACKETS.model_copy(update=later))
    return line(await shown_at_the_start(client, c), EARLIER)


async def test_a_lesson_in_the_same_subject_is_recalled_without_a_shared_tag(db, client, three):
    """Seen in the prompt check: the agent wrote "Maths" for a lesson where another lesson said
    "mathematics", and tagged the two differently."""
    recalled = await recalled_from(
        db,
        client,
        three,
        {"subject": "mathematics", "topics": ["algebra"]},
        {"subject": "Maths", "topics": ["equations"]},
    )
    assert recalled == f"{EARLIER} {WARM_UP}: right first time."


async def test_a_shared_tag_is_still_recalled_in_another_subject(db, client, three):
    recalled = await recalled_from(
        db,
        client,
        three,
        {"subject": "mathematics", "topics": ["linear equations"]},
        {"subject": "Physics", "topics": ["linear equations"]},
    )
    assert recalled == f"{EARLIER} {WARM_UP}: right first time."


async def test_two_lessons_with_no_subject_given_are_not_the_same_subject(db, client, three):
    recalled = await recalled_from(
        db,
        client,
        three,
        {"subject": "", "topics": ["algebra"]},
        {"subject": "", "topics": ["equations"]},
    )
    assert recalled == ""


def test_a_subject_has_one_name_however_it_was_written():
    assert {memory.subject_key(s) for s in ("Maths", " MATH ", "mathematics", "Mathematics.")} == {
        "mathematics"
    }
    assert memory.subject_key("PE") == memory.subject_key("Physical  Education")
    assert memory.subject_key("English") != memory.subject_key("Maths")
    assert memory.subject_key("") == ""


async def test_in_the_study_arm_without_memory_the_tutor_is_shown_none_of_it(db, client, three):
    await first_lesson(client, three)
    arm = {**study.condition_for(three.alice.id, 1), "memory": False}
    await next_lesson(db, three, condition=arm)
    system = await shown_at_the_start(client, three)
    assert (line(system, EARLIER), line(system, KNOWN)) == ("", "")
    assert SIGN not in system
