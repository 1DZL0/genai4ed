"""Collecting the records: once a lesson is played, what the platform kept of it is read from the
test database into plain data for the checks. Each lesson here is played in this process the way
the driver plays it, by one pupil signed in with their join code, with a scripted tutor. One
pupil at a time suits the one database session the app and the test share here. What a short
lesson does not make (an outcome, a teacher's note, learner note lines, evidence from another
lesson) is written with the platform's own functions, or as rows. No model is called."""

import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent import learner, llm, student_notes
from app.agent.brief import LessonBrief
from app.agent.student_mode import HELD_BACK, INTENTS
from app.enums import (
    ContractStatus,
    EvidenceKind,
    MessageRole,
    NoteCategory,
    ScoreStatus,
    SessionStatus,
)
from app.ledger import append
from app.models import (
    AgentTurn,
    Exception_,
    LearningState,
    LessonContract,
    LessonOutcome,
    Message,
    Session,
)
from bench.pupils import Beat, Persona, beat
from bench.school.cast import Pupil
from bench.school.collect import LessonFacts, collect, note_lines_of, pitch_call_of
from bench.school.driver import LessonLog, Sent, run_lesson
from bench.school.teacher import Drafted
from tests.test_school_driver import pupil, seats

OPENING = "Hello. Solve 3x + 4 = 19. What do you get?"
ASKS = "How did you get that? Show me your working."
TASK = "Solve 3x + 4 = 19"
# What a pupil says for each move, whoever they are.
SAYS = {
    "right": "x = 5",
    "wrong": "x = 7",
    "what_mean": "what do u mean",
    "closer": "is it 4 or something",
}
HINT = "Give them a hint about the first step."


def tutor(purpose: str, system: str, messages: list[dict]) -> dict:
    """The tutor opens the lesson, then asks for the working whatever it is told."""
    opening = not any(m["role"] == "assistant" for m in messages)
    return {"message": OPENING if opening else ASKS, "move": "ask", "task": TASK}


def pitching(purpose: str, system: str, messages: list[dict]) -> dict:
    """The same tutor, let to pitch: it opens with no call of its own, then asks its own
    version of the step, a stretch."""
    reply = tutor(purpose, system, messages)
    if reply["message"] == OPENING:
        return reply
    return {
        **reply,
        "pitch": "Asked for the working as well as the answer.",
        "pitch_call": "stretched",
        "pitch_changed": ["Reasoning"],
    }


GIVES_IT_AWAY = "The answer is x = 5."


def leaking(purpose: str, system: str, messages: list[dict]) -> dict:
    """The same tutor, let to pitch, but after opening the step as written it states the
    answer, on every draft, and calls that a stretch."""
    reply = tutor(purpose, system, messages)
    if reply["message"] == OPENING:
        return {**reply, "pitch_call": "as written"}
    return {
        "message": GIVES_IT_AWAY,
        "move": "explain",
        "disclosure": "full",
        "pitch": "Gave the answer so they can move on.",
        "pitch_call": "stretched",
        "pitch_changed": ["Load"],
    }


async def let_pitch(db, three) -> None:
    """The lesson lets the tutor pitch each step for the pupil in front of it."""
    brief = LessonBrief.model_validate(three.contract.brief)
    brief.rules = brief.rules.model_copy(update={"adapt_to_student": True})
    three.contract.brief = brief.model_dump(mode="json")
    await db.commit()


class Says:
    """The pupils' words: each move's line from SAYS."""

    async def write(self, persona: Persona, move: Beat, lines: list[dict]) -> tuple[str, bool]:
        return SAYS[move.kind], False


async def no_call(line_id: str) -> str | None:
    return None


def browser(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def play(app, three, pupils, seated, *, read_call=no_call, max_turns: int) -> LessonLog:
    """The lesson played by `pupils`, each in a browser of their own on the app here."""
    return await run_lesson(
        key="maths-1",
        base_url="http://test",
        session_id=str(three.session.id),
        seats=seated,
        pupils=pupils,
        writer=Says(),
        read_call=read_call,
        think=(0, 0),
        max_turns=max_turns,
        client_factory=lambda: browser(app),
    )


def facts(three) -> LessonFacts:
    """The lesson as the runner describes it."""
    brief = three.contract.brief
    return LessonFacts(
        key="maths-1",
        session_id=str(three.session.id),
        subject=brief["subject"],
        age=brief["age"],
        steps=len(brief["steps"]),
        rules=brief["rules"],
        brief=brief,
        teacher=three.teacher.pseudonym,
        drafted=Drafted(str(three.contract.id), 1),
    )


async def act(app, three, action: str, **fields: str) -> None:
    """The teacher presses one of their buttons."""
    async with browser(app) as theirs:
        pressed = await theirs.post(
            "/api/teacher/thread/actions",
            json={"action": action, **fields},
            headers=three.headers(three.teacher),
        )
    assert pressed.status_code == 200, pressed.text


def turn_row(
    session_id: uuid.UUID, student_id: uuid.UUID, manifest: dict, mode: str = "student", **more
) -> AgentTurn:
    """A model call as the platform records one, a tutor's turn unless `mode` says otherwise,
    for a lesson nobody played here."""
    return AgentTurn(
        session_id=session_id,
        student_id=student_id,
        mode=mode,
        context_manifest=manifest,
        policy_version="class-agent-v1",
        prompt_version="p-1",
        provider="scripted",
        model="scripted",
        latency_ms=1200,
        validation_outcome="ok",
        leakage_check="passed",
        conflicts=[],
        request={"text": None, "intent": None, "guidance": None, "step_index": 0},
        response={},
        **more,
    )


def sent(pupil: str, move: str, session_id: str) -> Sent:
    return Sent(pupil, "average", session_id, move, "", 200, 0.2, None, "2026-11-22T10:00Z", False)


def when(at: str | None) -> datetime:
    """An ISO time from the data, which must say its time zone."""
    moment = datetime.fromisoformat(at)
    assert moment.tzinfo is not None, at
    return moment


# ---------- each turn and the message that made it ----------


async def test_collect_matches_each_sent_message_to_its_turn_and_reads_alerts(db, app, three):
    three.tutor = llm.ScriptedClient(tutor)
    seated = await seats(app, three, keen="10B-01")
    log = await play(app, three, [pupil("keen", "right ask_teacher")], seated, max_turns=2)

    assert log.errors == []
    assert [(s.beat, s.text, s.status) for s in log.sent] == [
        ("open", "", 200),
        ("right", "x = 5", 200),
        ("ask_teacher", "", 200),
    ]
    opened, answered, asked = log.sent
    # Asking for the teacher writes no tutor line, so its page shows the reply before it again.
    assert asked.agent_line_id == answered.agent_line_id != opened.agent_line_id

    data = await collect(db, [log], [facts(three)], [])

    [turn] = [t for t in data.turns if t.said == "x = 5"]
    assert turn.agent_line_id == answered.agent_line_id
    # A turn for each line the tutor wrote, with that line's words, and none for the press.
    assert [(t.said, t.agent_line_id, t.reply_text) for t in data.turns] == [
        ("", opened.agent_line_id, OPENING),
        ("x = 5", answered.agent_line_id, ASKS),
    ]
    [alert] = data.alerts
    keen = seated["keen"].pseudonym
    assert (alert["kind"], alert["pupil"], alert["session_id"], alert["status"]) == (
        "teacher_requested",
        keen,
        str(three.session.id),
        "open",
    )
    assert alert["acknowledged_at"] is None
    when(alert["at"])

    # The rest of a turn is the platform's record of it, the reply as the tutor sent it.
    assert turn.reply == {"message": ASKS, "move": "ask", "task": TASK}
    assert (turn.outcome, turn.leak, turn.model) == ("ok", "passed", "scripted")
    kept = {str(r.id): r for r in await db.scalars(select(AgentTurn))}
    assert sorted(kept) == sorted(t.id for t in data.turns)
    for t in data.turns:
        record = kept[t.id]
        assert (t.pupil, t.session_id) == (keen, str(three.session.id))
        assert t.manifest == record.context_manifest and t.manifest["step_index"] == 0
        assert (t.prompt_version, t.conflicts, t.latency_ms) == (
            record.prompt_version,
            record.conflicts,
            record.latency_ms,
        )
        assert when(t.at) == record.created_at


async def test_a_turn_says_what_the_pupil_pressed_or_tapped_and_what_the_teacher_asked(
    db, app, three
):
    three.tutor = llm.ScriptedClient(tutor)
    seated = await seats(app, three, keen="10B-01")
    log = await play(
        app, three, [pupil("keen", "right helped button:why_wrong")], seated, max_turns=3
    )
    keen = three.alice
    await act(
        app,
        three,
        "guide",
        session_id=str(three.session.id),
        student_id=str(keen.id),
        text=HINT,
    )

    data = await collect(db, [log], [facts(three)], [])

    assert log.errors == []
    assert [s.beat for s in log.sent] == ["open", "right", "helped", "button:why_wrong"]
    # The button's words, as the pupil's page shows them; the tap kept on the line it rated;
    # and the turn the teacher's guidance made, which answered nothing of the pupil's.
    assert [(t.said, t.helped, t.request.get("guidance")) for t in data.turns] == [
        ("", None, None),
        ("x = 5", True, None),
        (INTENTS["why_wrong"], None, None),
        ("", None, HINT),
    ]
    page = await db.scalars(
        select(Message.text)
        .where(Message.role == MessageRole.STUDENT.value)
        .order_by(Message.created_at)
    )
    assert [t.said for t in data.turns if t.said] == list(page)
    assert data.turns[2].request["intent"] == "why_wrong"
    assert data.turns[1].agent_line_id == log.sent[2].agent_line_id
    [guided] = data.guidance
    assert (guided["pupil"], guided["session_id"], guided["payload"]) == (
        keen.pseudonym,
        str(three.session.id),
        {"text": HINT, "shown_to_student": False},
    )
    # The turn after it was told of it. (Its time is the database's, the guidance's the app's:
    # two clocks, so not compared here.)
    when(guided["at"])
    assert data.turns[-1].manifest["guidance_ids"] == [guided["id"]]


async def test_a_reply_held_back_is_the_holding_line_the_pupil_saw(db, app, three):
    await let_pitch(db, three)
    three.tutor = llm.ScriptedClient(leaking)
    seated = await seats(app, three, keen="10B-01")
    log = await play(app, three, [pupil("keen", "wrong")], seated, max_turns=1)

    data = await collect(db, [log], [facts(three)], [])

    _, wrong = log.sent
    [turn] = [t for t in data.turns if t.said == "x = 7"]
    # The pupil saw the platform's holding line; what the tutor wrote is kept for the checks.
    assert (turn.agent_line_id, turn.reply_text) == (wrong.agent_line_id, HELD_BACK)
    assert turn.reply["message"] == GIVES_IT_AWAY
    assert (turn.outcome, turn.leak) == ("withheld", "failed")
    assert "answer_leakage" in turn.conflicts
    assert [a["kind"] for a in data.alerts] == ["policy_conflict"]
    # The pitch call is the one kept with the pupil's line, which is what steered them: the
    # holding line keeps none, whatever the held-back draft called itself.
    assert (turn.reply["pitch_call"], turn.reply["pitch_changed"]) == ("stretched", ["Load"])
    assert [(t.call, t.changed) for t in data.turns] == [("as written", []), (None, [])]


async def test_collect_reads_the_records_as_they_are_now_not_an_older_copy(db, app, three, engine):
    three.tutor = llm.ScriptedClient(tutor)
    seated = await seats(app, three, keen="10B-01")
    log = await play(app, three, [pupil("keen", "right")], seated, max_turns=1)
    # The caller's session holds the tutor's reply as it read it; then the pupil taps it, through
    # a connection of the server's own.
    held = await db.get(Message, uuid.UUID(log.sent[-1].agent_line_id))
    assert "helped" not in held.data
    async with async_sessionmaker(engine)() as server:
        line = await server.get(Message, held.id)
        line.data = {**line.data, "helped": True}
        await server.commit()

    data = await collect(db, [log], [facts(three)], [])

    assert [t.helped for t in data.turns] == [None, True]


# ---------- the teacher's side, and where each pupil got to ----------


async def test_collect_reads_what_the_teacher_did_and_where_the_pupil_got_to(db, app, three):
    three.tutor = llm.ScriptedClient(tutor)
    seated = await seats(app, three, keen="10B-01")
    log = await play(app, three, [pupil("keen", "right ask_teacher")], seated, max_turns=2)
    sid, keen, teacher = str(three.session.id), three.alice, three.teacher
    alert_id = str(await db.scalar(select(Exception_.id)))
    await act(app, three, "show_transcript", session_id=sid, student_id=str(keen.id))
    await act(app, three, "acknowledge", exception_id=alert_id)
    # An outcome the teacher confirmed, and a note they asked the tutor to keep for a week. A
    # note on a pupil who is not in the run is not the run's.
    marks = {"criteria": [{"name": "Solves it", "points": 2, "max": 3}]}
    confirmed_at = datetime.now(UTC)
    db.add(
        LessonOutcome(
            session_id=three.session.id,
            student_id=keen.id,
            status=ScoreStatus.CONFIRMED.value,
            suggested=marks,
            suggested_total=2,
            confirmed=marks,
            confirmed_total=2,
            confirmed_at=confirmed_at,
            provider="scripted",
            model="scripted",
            prompt_version="p-1",
        )
    )
    gently = "Go gently with 10B-01 this week, keep your questions short for them."
    await student_notes.keep(db, teacher_id=teacher.id, student_id=keen.id, text=gently, days=7)
    await student_notes.keep(
        db, teacher_id=teacher.id, student_id=three.outsider.id, text="Not in the run.", days=7
    )
    await db.commit()

    data = await collect(db, [log], [facts(three)], ["10B-01 asked for you."])

    assert [(a["action"], a["teacher"], a["pupil"], a["session_id"]) for a in data.access] == [
        ("transcript_drilldown", teacher.pseudonym, keen.pseudonym, sid),
        ("acknowledge_exception", teacher.pseudonym, keen.pseudonym, sid),
    ]
    assert data.access[1]["detail"] == {"exception_id": alert_id, "kind": "teacher_requested"}
    [alert] = data.alerts
    assert (alert["id"], alert["status"]) == (alert_id, "acknowledged")
    when(alert["acknowledged_at"])
    [outcome] = data.outcomes
    assert outcome == {
        "session_id": sid,
        "pupil": keen.pseudonym,
        "status": "confirmed",
        "suggested": marks,
        "confirmed": marks,
        "confirmed_at": confirmed_at.isoformat(),
    }
    [note] = data.notes
    assert {k: v for k, v in note.items() if k != "at"} == {
        "teacher": teacher.pseudonym,
        "pupil": keen.pseudonym,
        "text": gently,
        "until": (student_notes.today() + timedelta(days=6)).isoformat(),
    }
    when(note["at"])
    assert data.states == [
        {"pupil": keen.pseudonym, "session_id": sid, "status": "in_progress", "step_index": 0}
    ]
    assert data.teacher_replies == ["10B-01 asked for you."]
    # All of it plain data, ready to be written out for the report.
    written = json.loads(json.dumps(asdict(data)))
    assert written["alerts"] == data.alerts and written["turns"][1]["said"] == "x = 5"
    assert written["lessons"][0]["drafted"] == {
        "lesson_id": str(three.contract.id),
        "asked": 1,
        "reason": "",
    }


# ---------- what the tutor was given from before ----------


async def test_collect_reads_the_note_lines_and_the_subject_of_each_recalled_record(db, three):
    keen, quiet, other = three.alice, three.outsider, three.bob
    # An English lesson that is not one of the run's. Its brief names no subject, so its
    # subject is the one it was saved under; this lesson's brief names one, which counts over
    # the one it was saved under.
    three.contract.subject = "Maths"
    english = LessonContract(
        teacher_id=three.teacher.id,
        title="Poems",
        subject="English",
        status=ContractStatus.ACTIVE.value,
        version=1,
        brief={},
    )
    db.add(english)
    await db.flush()
    poems = Session(
        contract_id=english.id, class_id=three.klass.id, status=SessionStatus.CLOSED.value
    )
    db.add(poems)
    await db.flush()
    # 10B-01's note in three versions. The first, from no lesson, has a line counted from the
    # record. The English lesson's review adds a line of its own, and this lesson's review then
    # writes the counted line's sentence as its own. 10B-02 has a note too, but is not in the run.
    first = learner.Line("Gets a step right on the first try.", NoteCategory.NEED_FOR_ASSISTANCE)
    await learner.write(db, student_id=keen.id, worked_out=[first])
    await db.commit()
    explains = "Explains their working when asked."
    await learner.write(db, student_id=keen.id, session_id=poems.id, written=[explains])
    await db.commit()
    await learner.write(
        db, student_id=keen.id, session_id=three.session.id, written=[first.sentence]
    )
    await db.commit()
    await learner.write(db, student_id=other.id, written=["Likes a worked example first."])
    await db.commit()
    in_maths = await append(
        db,
        session_id=three.session.id,
        student_id=keen.id,
        kind=EvidenceKind.ASSESSMENT,
        payload={"judgment": "met"},
    )
    in_english = await append(
        db,
        session_id=poems.id,
        student_id=keen.id,
        kind=EvidenceKind.ASSESSMENT,
        payload={"judgment": "partial"},
    )
    shown = {
        "step_index": 0,
        "retrieved_ids": [str(in_maths.id)],
        "knowledge_evidence_ids": [str(in_english.id), str(uuid.uuid4()), "not-an-id"],
    }
    db.add_all(
        [
            turn_row(three.session.id, keen.id, shown, usage={"total_tokens": 120}),
            # A turn of the English lesson, and the model call of this lesson's end-of-lesson
            # review, which is not a tutor turn.
            turn_row(poems.id, keen.id, {"step_index": 0}),
            turn_row(three.session.id, keen.id, {}, mode="review"),
            # And a record of each other kind in the English lesson.
            Exception_(
                session_id=poems.id,
                student_id=keen.id,
                kind="struggling",
                priority=2,
                summary="Stuck on the second verse.",
            ),
            LessonOutcome(
                session_id=poems.id,
                student_id=keen.id,
                suggested={},
                suggested_total=0,
                provider="scripted",
                model="scripted",
                prompt_version="p-1",
            ),
            LearningState(session_id=poems.id, student_id=keen.id),
        ]
    )
    await append(
        db,
        session_id=poems.id,
        student_id=keen.id,
        kind=EvidenceKind.TEACHER_GUIDANCE,
        payload={"text": "Ask them to read it aloud.", "shown_to_student": False},
    )
    await db.commit()
    cast = {keen.pseudonym: {"name": "keen"}, quiet.pseudonym: {"name": "quiet"}}
    log = LessonLog("maths-1", str(three.session.id), [], [], [], [], cast)

    data = await collect(db, [log], [facts(three)], [])

    # Each line written for a pupil of the run once, at the time it was first written, with
    # who wrote it and the lesson whose end or review made the version that first held it.
    # The later versions hold the counted line again, and it stays one line; the review
    # writing the same sentence is a line of its own. A pupil with none has an empty list.
    lines = data.note_lines[keen.pseudonym]
    assert [{k: v for k, v in line.items() if k != "at"} for line in lines] == [
        {
            "sentence": first.sentence,
            "source": "counted",
            "category": "need_for_assistance",
            "session_id": None,
        },
        {
            "sentence": explains,
            "source": "review",
            "category": "review_note",
            "session_id": str(poems.id),
        },
        {
            "sentence": first.sentence,
            "source": "review",
            "category": "review_note",
            "session_id": str(three.session.id),
        },
    ]
    once, then, last = (when(line["at"]) for line in lines)
    assert once < then < last
    assert data.note_lines == {keen.pseudonym: lines, quiet.pseudonym: []}
    # Nothing of the English lesson's own reaches the run's data.
    assert data.alerts == data.outcomes == data.guidance == data.states == []
    # Each record the tutor was shown, by the subject of the lesson it came from; ids that
    # name no record are left out.
    assert data.evidence_subject == {str(in_maths.id): "mathematics", str(in_english.id): "English"}
    # Only the tutor's turns in the run's own lessons, each with its request and what it cost.
    [turn] = data.turns
    assert (turn.session_id, turn.manifest, turn.usage) == (
        str(three.session.id),
        shown,
        {"total_tokens": 120},
    )
    assert (turn.said, turn.reply, turn.reply_text, turn.agent_line_id) == ("", {}, "", None)
    assert turn.request["step_index"] == 0
    written = json.loads(json.dumps(asdict(data)))
    assert written["note_lines"] == data.note_lines


async def test_lines_captured_before_a_teacher_deletes_what_is_remembered_are_kept(db, app, three):
    keen = three.alice
    first = learner.Line("Gets a step right on the first try.", NoteCategory.NEED_FOR_ASSISTANCE)
    await learner.write(db, student_id=keen.id, session_id=three.session.id, worked_out=[first])
    await db.commit()
    # Just before the teacher deletes what is remembered of their pupils, the run reads it.
    captured = await note_lines_of(db, [keen.pseudonym])
    async with browser(app) as theirs:
        deleted = await theirs.delete("/api/research/memory", headers=three.headers(three.teacher))
    assert deleted.status_code == 200, deleted.text
    assert await note_lines_of(db, [keen.pseudonym]) == {keen.pseudonym: []}
    # A later lesson writes the same line again, and a new one.
    finishes = learner.Line("Finishes every lesson.", NoteCategory.TASK_COMPLETION)
    await learner.write(db, student_id=keen.id, worked_out=[first, finishes])
    await db.commit()
    [again, new] = (await note_lines_of(db, [keen.pseudonym]))[keen.pseudonym]
    log = LessonLog("maths-1", str(three.session.id), [], [], [], [], {keen.pseudonym: {}})

    data = await collect(db, [log], [facts(three)], [], captured_note_lines=captured)

    # The deleted line is back from what was captured: once, at the time it was first written,
    # from the lesson that first wrote it.
    [kept] = captured[keen.pseudonym]
    assert (kept["sentence"], again["sentence"], new["sentence"]) == (
        first.sentence,
        first.sentence,
        finishes.sentence,
    )
    assert when(kept["at"]) < when(again["at"])
    assert kept["session_id"] == str(three.session.id)
    assert data.note_lines == {keen.pseudonym: [kept, new]}


async def test_collect_with_captured_lines_still_reads_the_lessons_turns(db, app, three):
    # Group C's order: the lesson is played and its pupil's note written; the run keeps the
    # lines; the teacher deletes what is remembered; then the records are collected.
    three.tutor = llm.ScriptedClient(tutor)
    seated = await seats(app, three, keen="10B-01")
    log = await play(app, three, [pupil("keen", "right")], seated, max_turns=1)
    keen = three.alice
    first = learner.Line("Gets a step right on the first try.", NoteCategory.NEED_FOR_ASSISTANCE)
    await learner.write(db, student_id=keen.id, session_id=three.session.id, worked_out=[first])
    await db.commit()
    captured = await note_lines_of(db, [keen.pseudonym])
    async with browser(app) as theirs:
        deleted = await theirs.delete("/api/research/memory", headers=three.headers(three.teacher))
    assert deleted.status_code == 200, deleted.text

    data = await collect(db, [log], [facts(three)], [], captured_note_lines=captured)

    opened, answered = log.sent
    assert [(t.said, t.agent_line_id, t.reply_text) for t in data.turns] == [
        ("", opened.agent_line_id, OPENING),
        ("x = 5", answered.agent_line_id, ASKS),
    ]
    assert data.note_lines == captured and len(captured[keen.pseudonym]) == 1


# ---------- the logs of every lesson together ----------


async def test_collect_puts_every_lessons_log_together_and_adds_the_probes(db):
    a_maths, a_english = str(uuid.uuid4()), str(uuid.uuid4())
    first = LessonLog(
        key="a-maths",
        session_id=a_maths,
        sent=[sent("8A-01", "open", a_maths), sent("8A-01", "right", a_maths)],
        events=[{"what": "paused", "pupil": "8A-01"}],
        view_seconds=[0.4],
        errors=["8A-02, wrong: 500 Internal Server Error"],
        cast={"8A-01": {"name": "a-keen"}, "8A-02": {"name": "a-quiet"}},
    )
    second = LessonLog(
        key="a-english",
        session_id=a_english,
        sent=[sent("8A-01", "open", a_english)],
        events=[{"what": "pupils stopped"}],
        view_seconds=[1.2, 0.8],
        errors=[],
        cast={"8A-01": {"name": "a-keen", "note_target": True}},
    )
    # A lesson the class agent never drafted, so it never ran.
    never = LessonFacts(
        key="c-science",
        session_id="",
        subject="science",
        age=12,
        steps=0,
        rules={},
        brief={},
        teacher="sd-c",
        drafted=Drafted(None, 3, "The class agent did not draft the lesson."),
    )
    probes = [{"probe": "x1", "path": "/api/teacher/thread", "status": 403}]

    data = await collect(db, [first, second], [never], ["Nobody."], extra_events=probes)

    assert data.sent == first.sent + second.sent
    assert data.events == first.events + second.events + probes
    assert (data.view_seconds, data.errors) == ([0.4, 1.2, 0.8], first.errors)
    # Each pupil once, as the later lesson describes them.
    assert data.cast == {
        "8A-01": {"name": "a-keen", "note_target": True},
        "8A-02": {"name": "a-quiet"},
    }
    assert (data.lessons, data.teacher_replies) == ([never], ["Nobody."])
    # The database holds nothing of these lessons, and one that never ran is no mistake.
    assert data.turns == data.alerts == data.access == data.outcomes == []
    assert data.notes == data.guidance == data.states == []
    assert (data.note_lines, data.evidence_subject) == ({"8A-01": [], "8A-02": []}, {})


# ---------- the tutor's pitch call, for the driver ----------


async def test_the_drivers_read_call_reads_the_tutors_call_from_its_line(db, app, three):
    await let_pitch(db, three)
    three.tutor = llm.ScriptedClient(pitching)
    seated = await seats(app, three, slow="10B-01")
    read: list[str | None] = []

    async def call_of(line_id: str) -> str | None:
        call = await pitch_call_of(db, line_id)
        read.append(call)
        return call

    slow = Pupil("average", Persona("slow", "14, slow and careful", [beat("right")]), steer="slow")
    log = await play(app, three, [slow], seated, read_call=call_of, max_turns=3)

    # The opening makes no call, so they answer the step as written. Then each reply is the
    # tutor's own version, a stretch, which a slow pupil meets slowly.
    assert [s.beat for s in log.sent] == ["open", "right", "what_mean", "closer"]
    assert read == [None, "stretched", "stretched", "stretched"]
    assert log.errors == []
    # Each turn carries the call kept with its line, the one the pupil was steered by.
    data = await collect(db, [log], [facts(three)], [])
    assert [(t.call, t.changed) for t in data.turns] == [
        (None, []),
        *[("stretched", ["Reasoning"])] * 3,
    ]
    # A pupil's line makes no call, and neither does a line that is not there or no id at all.
    theirs = await db.scalar(select(Message.id).where(Message.role == MessageRole.STUDENT.value))
    for line in (str(theirs), str(uuid.uuid4()), "not-a-line"):
        assert await pitch_call_of(db, line) is None
