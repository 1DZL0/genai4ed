"""What a teacher asks the tutor to keep in mind about one student for a few days: "go gently
with 10B-01 this week". The class agent passes it on with the days the teacher gave; the server
keeps it and says so in the thread; the tutor reads it in each of that teacher's lessons until
then. A scripted class agent and a scripted tutor play it; no model is called."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import research
from app.agent import classroom, llm, scaffold
from app.enums import SessionStatus
from app.models import AgentTurn, Conversation, Message, StudentNote
from tests.test_thread import say
from tests.test_what_the_record_shows import OPEN

GENTLY = "Go gently with them this week."


def today():
    return datetime.now(UTC).date()


async def told(client, app, c, text, guide):
    """The teacher says `text`; the class agent passes on `guide`. Returns the thread."""
    agent = llm.ScriptedClient([{"reply": "I'll pass that on.", "show": "class", "guide": guide}])
    app.dependency_overrides[llm.get_llm_client] = lambda: agent
    r = await say(client, c, text)
    app.dependency_overrides[llm.get_llm_client] = lambda: c.tutor
    assert r.status_code == 200, r.text
    return r.json()["messages"]


async def week(client, app, c, student=None):
    pupil = (student or c.alice).pseudonym
    return await told(
        client,
        app,
        c,
        f"Go gently with {pupil} this week",
        {"student_ref": pupil, "text": GENTLY, "days": 7},
    )


async def notes(db):
    return (await db.scalars(select(StudentNote))).all()


async def opened(client, c):
    """The tutor's prompt as the student opens the lesson."""
    c.tutor._replies.append(OPEN)
    r = await client.post(f"/api/learn/{c.session.id}/start", headers=c.headers(c.alice))
    assert r.status_code == 200, r.text
    return c.tutor.calls[-1]["system"]


# ---------- kept, and said in the thread ----------


async def test_it_is_kept_for_the_days_the_teacher_gave(db, client, app, three):
    thread = await week(client, app, three)

    [note] = await notes(db)
    assert (note.teacher_id, note.student_id) == (three.teacher.id, three.alice.id)
    assert note.text == GENTLY
    # A week from today, today included.
    assert note.until == today() + timedelta(days=6)
    # The server says what it kept, since the agent's own words cannot do it.
    assert any(
        "10B-01" in m["text"] and "until" in m["text"] and GENTLY in m["text"] for m in thread
    )


async def test_with_no_lesson_running_it_is_still_kept_and_nothing_fails(db, client, app, three):
    three.session.status = SessionStatus.CLOSED.value
    await db.commit()

    thread = await week(client, app, three)

    assert len(await notes(db)) == 1
    assert not any("Couldn't" in m["text"] for m in thread)


async def test_said_again_it_replaces_the_one_before(db, client, app, three):
    await week(client, app, three)
    pupil = three.alice.pseudonym
    await told(
        client,
        app,
        three,
        f"For the next two days push {pupil} a little more",
        {"student_ref": pupil, "text": "Push them a little more.", "days": 2},
    )

    [note] = await notes(db)
    assert note.text == "Push them a little more."
    assert note.until == today() + timedelta(days=1)


async def test_none_days_takes_it_back(db, client, app, three):
    await week(client, app, three)
    pupil = three.alice.pseudonym
    thread = await told(
        client,
        app,
        three,
        f"Forget what I said about {pupil}",
        {"student_ref": pupil, "text": "Forget it.", "days": 0},
    )

    assert await notes(db) == []
    assert any("Took back" in m["text"] for m in thread)


async def test_a_student_outside_the_teachers_classes_gets_nothing(db, client, app, three):
    thread = await week(client, app, three, student=three.outsider)

    assert await notes(db) == []
    assert any("isn't in your classes" in m["text"] for m in thread)


async def test_a_note_the_teacher_did_not_ask_for_is_not_kept(db, client, app, three):
    pupil = three.alice.pseudonym
    await told(
        client,
        app,
        three,
        "How is the class getting on?",
        {"student_ref": pupil, "text": GENTLY, "days": 7},
    )

    assert await notes(db) == []


# ---------- what the tutor reads ----------


async def test_the_tutor_reads_it_in_that_students_lesson(db, client, app, three):
    await week(client, app, three)

    system = await opened(client, three)

    assert GENTLY in system
    block = system.index(f"\n{scaffold.TEACHER_NOTE}")
    assert block < system.index(GENTLY) < system.index("What the platform noticed")
    # Kept for later lessons, not passed on as this lesson's guidance to act on at once.
    assert "Your teacher has just asked" not in system
    turn = (await db.scalars(select(AgentTurn).order_by(AgentTurn.created_at.desc()))).first()
    assert turn.context_manifest["teacher_note"] is True


async def test_after_its_last_day_it_is_not_read_and_the_purge_removes_it(db, client, three):
    db.add(
        StudentNote(
            teacher_id=three.teacher.id,
            student_id=three.alice.id,
            text=GENTLY,
            until=today() - timedelta(days=1),
        )
    )
    await db.commit()

    assert GENTLY not in await opened(client, three)
    assert (await research.purge(db))["student_notes"] == 1
    assert await notes(db) == []


async def test_another_teachers_note_is_not_read_in_this_teachers_lesson(db, client, three):
    db.add(
        StudentNote(
            teacher_id=three.other_teacher.id,
            student_id=three.alice.id,
            text=GENTLY,
            until=today() + timedelta(days=3),
        )
    )
    await db.commit()

    assert GENTLY not in await opened(client, three)


# ---------- what the teacher and the student see ----------


async def test_the_teacher_sees_it_on_the_students_card(db, client, app, three):
    await week(client, app, three)

    card = await classroom.student_view(db, three.session, three.alice)

    assert card["teacher_note"] == {
        "text": GENTLY,
        "until": (today() + timedelta(days=6)).isoformat(),
    }


async def test_the_student_never_sees_it(db, client, app, three):
    await week(client, app, three)
    await opened(client, three)

    r = await client.get(f"/api/learn/{three.session.id}", headers=three.headers(three.alice))
    assert GENTLY not in r.text
    theirs = (
        await db.scalars(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.student_id == three.alice.id)
        )
    ).all()
    assert theirs and not any(GENTLY in m.text for m in theirs)
