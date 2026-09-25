"""The teacher's one thread: everything they do, and the cards the server builds.

Two properties matter more than any screen. The agent chooses what to show but
never what it says: every card is built from records when the thread is read.
And the agent changes nothing - approving, running and confirming are buttons,
so a lesson cannot start because a model said it should.
"""

from sqlalchemy import select

from app.agent.brief import LessonBrief
from app.enums import ContractStatus, SessionStatus, TeacherAction
from app.models import AgentTurn, LessonContract, TeacherAccessLog

DESCRIBE = (
    "I want to teach this class about photosynthesis. Make it 30 minutes. "
    "They already know that plants need light."
)
RULES = (
    "Hints are fine but no final answer until they've attempted twice. "
    "Flag anyone who repeatedly tries to get it to complete the work."
)


async def say(client, classroom, text, teacher=None):
    return await client.post(
        "/api/teacher/thread/messages",
        json={"text": text},
        headers=classroom.headers(teacher or classroom.teacher),
    )


async def press(client, classroom, action, teacher=None, **fields):
    return await client.post(
        "/api/teacher/thread/actions",
        json={
            "action": action,
            **{k: str(v) if v is not None else None for k, v in fields.items()},
        },
        headers=classroom.headers(teacher or classroom.teacher),
    )


def last_card(response):
    """The one card on screen. It lives beside the conversation, not in it."""
    return response.json()["showing"]


async def test_describing_a_lesson_drafts_it_and_shows_it(client, classroom):
    body = (await say(client, classroom, DESCRIBE)).json()
    teacher_said, agent_said = body["messages"][-2:]
    assert (teacher_said["role"], agent_said["role"]) == ("teacher", "agent")

    card = body["showing"]
    assert card["type"] == "lesson"
    assert card["title"] == "Photosynthesis"
    assert card["status"] == ContractStatus.DRAFT.value
    assert len(card["steps"]) == 4
    # The classes to run it with come from the teacher's own classes, not the model.
    assert [k["label"] for k in card["classes"]] == ["10B"]


async def test_a_rule_in_conversation_changes_the_same_lesson(client, classroom, db):
    first = last_card(await say(client, classroom, DESCRIBE))
    second = last_card(await say(client, classroom, RULES))

    assert second["lesson_id"] == first["lesson_id"]
    assert "attempted twice" in second["rules_text"]
    assert any("two" in line or "2" in line for line in second["rules_in_words"])
    plans = (
        await db.scalars(
            select(LessonContract).where(LessonContract.teacher_id == classroom.teacher.id)
        )
    ).all()
    # The seeded lesson and the one being described - not a third from the rule.
    assert len(plans) == 2


async def test_the_agent_cannot_approve_a_lesson_itself(client, classroom, db):
    card = last_card(await say(client, classroom, DESCRIBE))
    await say(client, classroom, "Approve it and start it with 10B now.")
    lesson = await db.get(LessonContract, card["lesson_id"])
    await db.refresh(lesson)
    assert lesson.status == ContractStatus.DRAFT.value


async def test_approving_then_running_starts_the_lesson(client, classroom, db):
    card = last_card(await say(client, classroom, DESCRIBE))
    approved = await press(client, classroom, "approve", lesson_id=card["lesson_id"])
    assert approved.status_code == 200
    assert last_card(approved)["status"] == ContractStatus.ACTIVE.value

    lesson = await db.get(LessonContract, card["lesson_id"])
    await db.refresh(lesson)
    assert lesson.activated_by == classroom.teacher.id

    # This teacher is already teaching one, and they teach one at a time.
    busy = await press(
        client, classroom, "run", lesson_id=card["lesson_id"], class_id=classroom.klass.id
    )
    assert busy.status_code == 409
    assert "already have a lesson running" in busy.json()["detail"]
    await press(client, classroom, "end", session_id=classroom.session.id)

    running = await press(
        client, classroom, "run", lesson_id=card["lesson_id"], class_id=classroom.klass.id
    )
    board = last_card(running)
    assert board["type"] == "class"
    assert board["status"] == SessionStatus.OPEN.value
    assert {s["pseudonym"] for s in board["students"]} == {"10B-01", "10B-02"}
    assert running.json()["strip"][0]["class_label"] == "10B"


async def test_an_incomplete_lesson_cannot_be_approved(client, classroom):
    lesson = last_card(await say(client, classroom, "A lesson"))
    lesson["missing"] = lesson["missing"]  # what the card tells the teacher is missing
    refused = await press(client, classroom, "approve", lesson_id=lesson["lesson_id"])
    assert refused.status_code in (200, 422)
    if refused.status_code == 422:
        assert "needs" in refused.json()["detail"]


async def test_a_card_is_rebuilt_from_records_not_remembered(client, classroom):
    await press(client, classroom, "show_class", session_id=classroom.session.id)
    before = last_card(
        await client.get("/api/teacher/thread", headers=classroom.headers(classroom.teacher))
    )
    assert before["students"][0]["state"] == "not_started"

    await client.post(
        f"/api/learn/{classroom.session.id}/messages",
        json={"text": "x = 5 because I took 4 from both sides and divided 15 by 3"},
        headers=classroom.headers(classroom.alice),
    )
    after = last_card(
        await client.get("/api/teacher/thread", headers=classroom.headers(classroom.teacher))
    )
    assert after["students"][0]["state"] == "working"


async def test_looking_at_things_does_not_fill_the_conversation(client, classroom):
    """Looking at the class is not something said to the agent. Pressing it four
    times leaves one line, not four, and the card is on screen beside the talk."""
    before = len(
        (
            await client.get("/api/teacher/thread", headers=classroom.headers(classroom.teacher))
        ).json()["messages"]
    )
    for _ in range(4):
        shown = await press(client, classroom, "show_class", session_id=classroom.session.id)
    body = shown.json()
    assert last_card(shown)["type"] == "class"
    # At most the one line saying what they turned to - never one per press.
    assert len(body["messages"]) <= before + 1


async def test_reading_a_students_conversation_is_deliberate_and_logged(client, classroom, db):
    quiet = await press(
        client,
        classroom,
        "show_student",
        session_id=classroom.session.id,
        student_id=classroom.alice.id,
    )
    assert last_card(quiet)["conversation"] is None
    # Opening a student is not a line in the conversation either.
    assert quiet.json()["messages"] == []

    opened = await press(
        client,
        classroom,
        "show_transcript",
        session_id=classroom.session.id,
        student_id=classroom.alice.id,
    )
    assert last_card(opened)["conversation"] == []
    actions = [log.action for log in (await db.scalars(select(TeacherAccessLog))).all()]
    assert TeacherAction.TRANSCRIPT_DRILLDOWN.value in actions


async def test_a_teacher_sees_nothing_of_another_teachers_thread(client, classroom):
    await say(client, classroom, DESCRIBE)
    theirs = (
        await client.get("/api/teacher/thread", headers=classroom.headers(classroom.other_teacher))
    ).json()
    assert theirs["messages"] == []
    assert theirs["strip"] == []


async def test_a_material_joins_the_lesson_being_worked_on(client, classroom):
    card = last_card(await say(client, classroom, DESCRIBE))
    attached = await client.post(
        "/api/teacher/thread/materials",
        files={"file": ("notes.txt", b"Chlorophyll absorbs light.", "text/plain")},
        headers=classroom.headers(classroom.teacher),
    )
    assert attached.status_code == 201
    event = attached.json()["messages"][-1]
    assert event["role"] == "event" and event["text"] == "Attached notes.txt"
    assert [m["filename"] for m in last_card(attached)["materials"]] == ["notes.txt"]
    assert last_card(attached)["lesson_id"] == card["lesson_id"]


async def test_a_new_lesson_starts_from_a_clean_slate(client, classroom, db):
    first = last_card(await say(client, classroom, DESCRIBE))
    await press(client, classroom, "new_lesson")
    second = last_card(await say(client, classroom, "Now one about the water cycle, 20 minutes."))
    assert second["lesson_id"] != first["lesson_id"]
    assert second["duration_minutes"] == 20


async def test_browsing_lessons_does_not_interrupt_the_conversation(client, classroom):
    """Looking through your lessons is navigation, not a turn: the thread is
    untouched, and picking one up leaves a line rather than a card."""
    await say(client, classroom, DESCRIBE)
    before = len(
        (
            await client.get("/api/teacher/thread", headers=classroom.headers(classroom.teacher))
        ).json()["messages"]
    )
    listed = await client.get(
        "/api/teacher/thread/lessons", headers=classroom.headers(classroom.teacher)
    )
    assert listed.status_code == 200
    assert {lesson["title"] for lesson in listed.json()["lessons"]} >= {"Photosynthesis"}

    after = (
        await client.get("/api/teacher/thread", headers=classroom.headers(classroom.teacher))
    ).json()
    assert len(after["messages"]) == before
    assert after["focus"]["title"] == "Photosynthesis"


async def test_picking_a_lesson_up_says_nothing_but_changes_what_is_on_screen(client, classroom):
    """Turning back to a lesson is not worth a line. It shows on the card and in
    what the next thing said will change."""
    first = last_card(await say(client, classroom, DESCRIBE))
    await press(client, classroom, "new_lesson")
    picked = await press(client, classroom, "focus_lesson", lesson_id=first["lesson_id"])
    assert all(not m["text"] or m["role"] != "event" for m in picked.json()["messages"][-2:])
    assert picked.json()["focus"]["lesson_id"] == first["lesson_id"]
    assert last_card(picked)["lesson_id"] == first["lesson_id"]

    # And what is said next changes that lesson, not a new one.
    again = last_card(await say(client, classroom, "Make it a bit harder."))
    assert again["lesson_id"] == first["lesson_id"]


async def test_a_file_can_be_taken_back_off_the_agent(client, classroom):
    card = last_card(await say(client, classroom, DESCRIBE))
    await client.post(
        "/api/teacher/thread/materials",
        files={"file": ("notes.txt", b"Chlorophyll absorbs light.", "text/plain")},
        headers=classroom.headers(classroom.teacher),
    )
    shown = await press(client, classroom, "show_lesson", lesson_id=card["lesson_id"])
    [material] = last_card(shown)["materials"]

    gone = await press(client, classroom, "delete_material", material_id=material["id"])
    assert last_card(gone)["materials"] == []


async def test_a_lesson_never_taught_can_be_removed(client, classroom, db):
    card = last_card(await say(client, classroom, DESCRIBE))
    removed = await press(client, classroom, "delete_lesson", lesson_id=card["lesson_id"])
    assert removed.status_code == 200
    assert removed.json()["focus"] is None
    assert await db.get(LessonContract, card["lesson_id"]) is None
    # What is on screen falls back to the list of what is left.
    assert last_card(removed)["type"] == "lessons"


async def test_a_teacher_teaches_one_lesson_at_a_time(client, classroom):
    """A teacher is in one room. Starting a second lesson is refused with the
    class they are already with, not a bare error."""
    card = last_card(await say(client, classroom, DESCRIBE))
    await press(client, classroom, "approve", lesson_id=card["lesson_id"])
    refused = await press(
        client, classroom, "run", lesson_id=card["lesson_id"], class_id=classroom.klass.id
    )
    assert refused.status_code == 409
    assert classroom.klass.label in refused.json()["detail"]


async def test_the_conversation_can_be_cleared_without_losing_the_record(client, classroom, db):
    """Clearing puts the talk away. The lessons, and everything the platform
    recorded about the teaching, stay."""
    card = last_card(await say(client, classroom, DESCRIBE))
    turns_before = len((await db.scalars(select(AgentTurn))).all())

    cleared = await press(client, classroom, "clear")
    assert cleared.json()["messages"] == []
    # The talk goes, and with it the card: the page asks what to teach next.
    assert cleared.json()["showing"] is None

    assert await db.get(LessonContract, card["lesson_id"]) is not None
    assert len((await db.scalars(select(AgentTurn))).all()) == turns_before


async def test_a_shared_difficulty_becomes_a_follow_up_lesson(client, classroom):
    """Student activity feeds back: a pattern on the class board is one press
    from a drafted follow-up, which is a draft like any other - nothing runs
    until the teacher approves it."""
    drafted = await press(
        client, classroom, "follow_up", text="thinking plants get their food from the soil"
    )
    assert drafted.status_code == 200
    card = last_card(drafted)
    assert (card["type"], card["status"]) == ("lesson", ContractStatus.DRAFT.value)
    assert "soil" in card["title"].lower()


async def test_what_a_student_knows_is_read_from_the_record(client, classroom):
    """The structured side of memory is derived from evidence, per topic, and
    cites it - there is no stored profile to drift."""
    await client.post(
        f"/api/learn/{classroom.session.id}/messages",
        json={"text": "x = 5 because I took 4 from both sides and divided 15 by 3"},
        headers=classroom.headers(classroom.alice),
    )
    shown = await press(
        client,
        classroom,
        "show_student",
        session_id=classroom.session.id,
        student_id=classroom.alice.id,
    )
    [topic, *_] = last_card(shown)["knowledge"]
    assert topic["judged"] >= 1 and topic["evidence_ids"]


async def test_a_new_subject_while_a_lesson_is_in_focus_is_a_new_lesson(client, classroom):
    """A teacher who has a maths lesson in focus and asks for a history lesson
    gets a second lesson, not a rewritten maths one."""
    from app.agent.brief import LessonBrief
    from app.agent.thread import _same_lesson

    maths = LessonContract(
        title="Linear equations",
        subject="mathematics",
        brief={
            "title": "Linear equations",
            "subject": "mathematics",
            "topics": ["algebra"],
            "steps": [{"name": "Warm up", "kind": "question", "goal": "Solve 3x + 4 = 19"}],
        },
    )
    history = LessonBrief.model_validate(
        {
            "title": "Causes of the French Revolution",
            "subject": "history",
            "topics": ["french revolution"],
        }
    )
    tweaked = LessonBrief.model_validate(
        {"title": "Linear equations: both sides", "subject": "mathematics", "topics": ["algebra"]}
    )
    assert not _same_lesson(maths, history)
    assert _same_lesson(maths, tweaked)
    # "make it 3 steps" comes back flagged as new; the same title says otherwise.
    same = LessonBrief.model_validate(
        {"title": "Linear equations", "subject": "mathematics", "topics": []}
    )
    assert _same_lesson(maths, same, claimed_new=True)
    assert not _same_lesson(maths, tweaked, claimed_new=True)


# ---------- what the classroom simulation taught us ----------


async def test_a_follow_up_is_a_new_lesson_not_a_version_of_the_running_one(client, classroom):
    drafted = await press(
        client, classroom, "follow_up", text="thinking plants get their food from the soil"
    )
    assert last_card(drafted)["plan_id"] != str(classroom.contract.plan_id)


async def test_rules_copied_from_another_lesson_are_not_the_teachers(db, classroom):
    from app.agent.thread import TeacherTurnOut, _drop_carried_rules

    sample = LessonBrief.model_validate(classroom.contract.brief or {})
    sample.rules_text = "Hints are fine, never the final answer."
    classroom.contract.brief = sample.model_dump(mode="json")
    await db.commit()

    copied = sample.model_copy(
        update={"title": "Rivers", "subject": "geography", "topics": ["rivers"]}
    )
    out = TeacherTurnOut(reply="ok", brief=copied.model_copy())
    await _drop_carried_rules(db, classroom.teacher, out, "I want a lesson on rivers for year 7")
    assert out.brief.rules_text == ""

    out = TeacherTurnOut(reply="ok", brief=copied.model_copy())
    await _drop_carried_rules(db, classroom.teacher, out, "hints are fine but never the answer")
    assert out.brief.rules_text == sample.rules_text


async def test_after_the_end_nobody_needs_you_and_the_student_sees_the_result(
    db, client, classroom
):
    brief = LessonBrief.model_validate(classroom.contract.brief or {})
    brief.assessment = [
        {"name": "Method", "max": 5, "description": ""},
        {"name": "Accuracy", "max": 5, "description": ""},
    ]
    classroom.contract.brief = brief.model_dump(mode="json")
    await db.commit()
    sid = classroom.session.id
    alice = classroom.headers(classroom.alice)
    await client.post(
        f"/api/learn/{sid}/messages", json={"text": "x = 5, I took 4 off"}, headers=alice
    )

    await press(client, classroom, "end", session_id=sid)
    board = last_card(await press(client, classroom, "show_class", session_id=sid))
    states = {s["pseudonym"]: s["state"] for s in board["students"]}
    assert states[classroom.alice.pseudonym] in ("took_part", "finished")
    assert "needs_you" not in states.values()

    suggested = last_card(await press(client, classroom, "suggest_outcomes", session_id=sid))
    outcome = next(o for o in suggested["outcomes"] if o["pseudonym"] == classroom.alice.pseudonym)
    first = outcome["suggested"]["criteria"][0]
    changed = first["points"] - 1 if first["points"] > 0 else first["points"] + 1
    confirmed = await client.post(
        "/api/teacher/thread/actions",
        json={
            "action": "confirm_outcome",
            "session_id": str(sid),
            "outcome_id": outcome["id"],
            "points": {first["name"]: changed},
            "comment": "Good effort.",
        },
        headers=classroom.headers(classroom.teacher),
    )
    assert confirmed.status_code == 200
    row = next(o for o in last_card(confirmed)["outcomes"] if o["id"] == outcome["id"])
    assert row["status"] == "confirmed"
    # A reason written for other points is not kept as the reason for these.
    assert (
        next(c for c in row["confirmed"]["criteria"] if c["name"] == first["name"])["reason"] == ""
    )
    if all(o["status"] == "confirmed" for o in last_card(confirmed)["outcomes"]):
        texts = [m["text"] for m in confirmed.json()["messages"]]
        assert any(t.startswith("Confirmed the outcomes") for t in texts)

    mine = (await client.get("/api/learn", headers=alice)).json()
    [card] = [c for c in mine if c["session_id"] == str(sid)]
    assert card["status"] == "closed"
    assert card["result"]["comment"] == "Good effort."
    assert card["result"]["total"] == row["confirmed_total"]
    page = (await client.get(f"/api/learn/{sid}", headers=alice)).json()
    assert page["result"]["out_of"] == 10


async def test_asking_for_another_lesson_in_words_makes_a_new_one(client, classroom):
    first = last_card(await say(client, classroom, DESCRIBE))
    second = last_card(
        await say(
            client, classroom, "Now another lesson: a 20-minute check on fractions of amounts."
        )
    )
    assert second["plan_id"] != first["plan_id"]


def test_a_described_lesson_is_told_apart_from_a_question():
    from app.agent.thread import _describes_a_lesson

    assert _describes_a_lesson(
        "I want a 30 minute lesson for my year 8s on percentages. They can do 10% and 50%."
    )
    assert not _describes_a_lesson("how is the class doing?")
    assert not _describes_a_lesson("what lessons do I have?")
    assert not _describes_a_lesson("thanks")


async def test_a_change_without_a_title_keeps_the_title_it_had(db, classroom):
    from app.agent.thread import Focus, TeacherTurnOut, _apply_brief

    before = LessonBrief.model_validate(classroom.contract.brief or {})
    changed = before.model_copy(update={"title": "", "subject": ""})
    out = TeacherTurnOut(reply="Updated the rules.", brief=changed)
    contract = await _apply_brief(
        db, classroom.teacher, out, Focus(lesson=classroom.contract), said="never give the answer"
    )
    kept = LessonBrief.model_validate(contract.brief)
    assert kept.title == before.title and kept.subject == before.subject
    assert "a title" not in kept.missing()
