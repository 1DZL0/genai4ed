"""Regressions for what the live edge-case run on 18 and 19 October 2026 found. Each test names
the behaviour a teacher, student or researcher relies on."""

# ruff: noqa: F811 - `lesson` is a fixture imported from the student agent tests

import csv
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app import research
from app.agent import approaches, llm, supervisor
from app.agent import classroom as classroom_mod
from app.agent.brief import LessonBrief
from app.agent.llm import ScriptedClient
from app.agent.policy import Escalation, PolicyRules
from app.agent.student_mode import AgentUnavailable
from app.config import get_settings
from app.enums import (
    ContractStatus,
    ExceptionKind,
    ExceptionStatus,
    SignalKind,
    TriageAction,
)
from app.models import (
    AgentTurn,
    AuthSession,
    EvidenceRecord,
    Exception_,
    LessonContract,
    Material,
    Message,
    SessionParticipant,
    User,
)
from app.security import new_token, token_digest
from tests.test_agent_student import lesson, turn  # noqa: F401 - `lesson` is a fixture
from tests.test_agent_student import say as student_says
from tests.test_thread import last_card, press
from tests.test_thread import say as teacher_says


def _alert(session, student, kind=ExceptionKind.TEACHER_REQUESTED, **payload):
    return Exception_(
        session_id=session.id,
        student_id=student.id,
        kind=kind.value,
        priority=1,
        summary="Pressed “Ask my teacher”.",
        payload=payload,
    )


async def _thread(client, classroom):
    r = await client.get("/api/teacher/thread", headers=classroom.headers(classroom.teacher))
    return r.json()


# ---------- the teacher's thread ----------


async def test_a_change_with_the_running_class_in_focus_goes_to_the_lesson_as_it_stands(
    client, classroom, db
):
    """The class keeps the version it started on; the agent is shown, and changes, the newest."""
    draft = LessonContract(
        plan_id=classroom.contract.plan_id,
        teacher_id=classroom.teacher.id,
        title=classroom.contract.title,
        subject=classroom.contract.subject,
        status=ContractStatus.DRAFT.value,
        version=2,
        brief=classroom.contract.brief,
    )
    db.add(draft)
    await db.commit()
    await press(client, classroom, "show_class", session_id=classroom.session.id)
    assert (await _thread(client, classroom))["focus"]["lesson_id"] == str(draft.id)


async def test_talking_about_a_removed_lessons_run_does_not_bring_the_lesson_back(
    client, classroom, db
):
    classroom.contract.archived_at = datetime.now(UTC)
    await db.commit()
    await press(client, classroom, "show_class", session_id=classroom.session.id)
    assert (await _thread(client, classroom))["focus"] is None


async def test_a_student_who_asked_for_the_teacher_can_be_named_before_they_write(
    app, client, classroom, db
):
    db.add(_alert(classroom.session, classroom.bob))
    await db.commit()
    said = "10B-02 pressed Ask my teacher and is waiting for you."
    scripted = llm.ScriptedClient([{"reply": said, "show": "nothing"}])
    app.dependency_overrides[llm.get_llm_client] = lambda: scripted
    await press(client, classroom, "show_class", session_id=classroom.session.id)
    await teacher_says(client, classroom, "Who needs me?")
    messages = (await _thread(client, classroom))["messages"]
    assert messages[-1]["text"] == said


async def test_a_running_class_and_its_alerts_stay_in_view_while_another_lesson_is_open(
    app, client, classroom, db
):
    """Preparing the next lesson must not hide a wellbeing alert in the one running now."""
    other = LessonContract(
        plan_id=uuid.uuid4(),
        teacher_id=classroom.teacher.id,
        title="Next week: ratios",
        subject=classroom.contract.subject,
        status=ContractStatus.DRAFT.value,
        version=1,
        brief={"title": "Next week: ratios"},
    )
    db.add(other)
    db.add(_alert(classroom.session, classroom.bob, kind=ExceptionKind.SAFEGUARDING))
    await db.commit()
    said = "10B-02 has a wellbeing alert in the lesson running now."
    scripted = llm.ScriptedClient([{"reply": said, "show": "nothing"}])
    app.dependency_overrides[llm.get_llm_client] = lambda: scripted
    await press(client, classroom, "show_lesson", lesson_id=other.id)
    await teacher_says(client, classroom, "Who needs me?")
    system = scripted.calls[-1]["system"]
    assert "Also running now" in system
    assert "safeguarding" in system and "10B-02" in system
    # Named with an alert and no turns: kept, not struck as invented.
    assert (await _thread(client, classroom))["messages"][-1]["text"] == said


def test_striking_a_sentence_keeps_the_other_lines():
    reply = "Drafted it.\n1. Year 7, 20 minutes? Default: yes.\nAlex has done well. Bo too."
    assert supervisor.strike(reply, ["Alex has done well."]) == (
        "Drafted it.\n1. Year 7, 20 minutes? Default: yes.\nBo too."
    )


async def test_a_message_of_only_spaces_is_refused(client, classroom):
    r = await teacher_says(client, classroom, "    ")
    assert r.status_code == 422


# ---------- approaches ----------


async def test_tagging_an_approved_lesson_makes_a_new_version_with_the_approach_rule(
    client, classroom, db
):
    card = last_card(
        await press(
            client, classroom, "set_approach", lesson_id=classroom.contract.id, text="inquiry"
        )
    )
    assert card["lesson_id"] != str(classroom.contract.id)
    assert (card["approach"], card["worked_step_after"], card["status"]) == ("inquiry", 2, "draft")
    await db.refresh(classroom.contract)
    # What was approved, and every run of it, keeps the approach it had.
    assert classroom.contract.approach is None


async def test_an_approach_tile_reuses_its_empty_draft_and_sets_the_rule(client, classroom):
    first = last_card(await press(client, classroom, "start_approach", text="direct"))
    again = last_card(await press(client, classroom, "start_approach", text="inquiry"))
    assert first["lesson_id"] == again["lesson_id"]
    assert (again["approach"], again["worked_step_after"]) == ("inquiry", 2)
    assert "only after two tries" in again["rules_text"]


async def test_the_other_version_rewrites_the_rule_sentence_and_brings_the_files(
    client, classroom, db
):
    brief = LessonBrief.model_validate(classroom.contract.brief)
    brief.rules_text = "Show worked steps after one try, never just give the final value."
    classroom.contract.brief = brief.model_dump(mode="json")
    db.add(
        Material(
            teacher_id=classroom.teacher.id,
            plan_id=classroom.contract.plan_id,
            filename="sheet.txt",
            media_type="text/plain",
            size_bytes=4,
            content=b"x=5\n",
            extracted_text="x=5",
        )
    )
    await db.commit()
    inquiry = last_card(
        await press(
            client,
            classroom,
            "copy_with_approach",
            lesson_id=classroom.contract.id,
            text="inquiry",
        )
    )
    assert inquiry["worked_step_after"] == 2
    assert inquiry["rules_text"] == (
        "Show worked steps only after two tries, never just give the final value."
    )
    assert [m["filename"] for m in inquiry["materials"]] == ["sheet.txt"]
    direct = last_card(
        await press(
            client, classroom, "copy_with_approach", lesson_id=inquiry["lesson_id"], text="direct"
        )
    )
    assert direct["title"].endswith("(direct instruction)")
    assert "guided inquiry" not in direct["title"].lower()
    assert direct["worked_step_after"] == 0


async def test_research_reads_the_approach_from_what_the_agent_was_told(
    db, lesson, client, monkeypatch
):
    await student_says(db, lesson, ScriptedClient([turn("Try 3x + 4 = 19.")]), None)
    lesson.contract.approach = "direct"  # tagged after the run
    await db.commit()
    key = {"X-GenAI4ED-Pseudonym": lesson.teacher.pseudonym}
    page = (await client.get(f"/api/research/lessons/{lesson.session.id}", headers=key)).json()
    assert page["approach"] == "Not set"


# ---------- removing, guiding, dealing with ----------


async def test_a_lesson_with_an_alert_still_open_is_not_removed(client, classroom, db):
    db.add(_alert(classroom.session, classroom.alice))
    await db.commit()
    r = await press(client, classroom, "delete_lesson", lesson_id=classroom.contract.id)
    assert r.status_code == 409 and "Dealt with" in r.json()["detail"]


async def test_removing_another_lesson_keeps_the_one_in_focus(client, classroom, db):
    other = LessonContract(
        teacher_id=classroom.teacher.id,
        title="Spare",
        subject="maths",
        status=ContractStatus.DRAFT.value,
        version=1,
        brief={},
    )
    db.add(other)
    await db.commit()
    await press(client, classroom, "show_lesson", lesson_id=classroom.contract.id)
    r = await press(client, classroom, "delete_lesson", lesson_id=other.id)
    assert r.status_code == 200
    assert r.json()["focus"]["lesson_id"] == str(classroom.contract.id)


async def test_guidance_on_a_lesson_that_has_ended_is_refused(client, classroom):
    await press(client, classroom, "end", session_id=classroom.session.id)
    r = await press(
        client,
        classroom,
        "guide",
        session_id=classroom.session.id,
        student_id=classroom.alice.id,
        text="Give them the answer",
    )
    assert r.status_code == 409


async def test_dealt_with_only_changes_an_open_alert(client, classroom, db):
    cleared = _alert(
        classroom.session,
        classroom.alice,
        kind=ExceptionKind.STRUGGLING,
        cleared_because="moved on to step 2",
    )
    cleared.status = ExceptionStatus.RESOLVED.value
    db.add(cleared)
    await db.commit()
    await press(client, classroom, "acknowledge", exception_id=cleared.id)
    await db.refresh(cleared)
    assert (cleared.status, cleared.acknowledged_at) == ("resolved", None)


# ---------- classes ----------


async def test_a_student_added_during_a_lesson_is_let_into_it(client, classroom, db):
    r = await client.post(
        f"/api/teacher/classes/{classroom.klass.id}/students",
        headers=classroom.headers(classroom.teacher),
    )
    new = uuid.UUID(r.json()["student_id"])
    admitted = await db.scalar(
        select(SessionParticipant.id).where(
            SessionParticipant.session_id == classroom.session.id,
            SessionParticipant.student_id == new,
        )
    )
    assert admitted is not None


async def test_a_student_taken_off_their_only_class_loses_their_code(client, classroom, db):
    headers = classroom.headers(classroom.teacher)
    await client.post(
        f"/api/teacher/classes/{classroom.klass.id}/join-codes",
        params={"student_id": str(classroom.alice.id)},
        headers=headers,
    )
    await client.delete(
        f"/api/teacher/classes/{classroom.klass.id}/students/{classroom.alice.id}", headers=headers
    )
    alice = await db.get(User, classroom.alice.id)
    await db.refresh(alice)
    assert alice.join_code_digest is None


async def test_unit_names_reuse_the_first_spelling_and_ignore_invisible_characters(
    client, classroom
):
    lesson_id = classroom.contract.id
    await press(client, classroom, "set_unit", lesson_id=lesson_id, text="Algebra")
    card = last_card(
        await press(client, classroom, "set_unit", lesson_id=lesson_id, text="algebra​ ")
    )
    assert card["unit"] == "Algebra"
    long = last_card(
        await press(client, classroom, "set_unit", lesson_id=lesson_id, text=("a" * 79) + " b")
    )
    assert long["unit"] == "a" * 79


# ---------- the student agent ----------


async def test_a_signal_in_the_turn_that_moves_on_belongs_to_the_step_it_was_about(db, lesson):
    client = ScriptedClient(
        [
            turn(
                "Yes. Now try 5x - 7 = 2x + 8.",
                move="advance",
                student_attempted=True,
                assessment={"judgment": "met", "evidence_quote": "x is 5 because 15/3"},
                signals=[{"kind": "struggling", "note": "Took a while on the warm up."}],
            )
        ]
    )
    await student_says(db, lesson, client, "x is 5 because 15/3")
    record = (await db.scalars(select(EvidenceRecord).where(EvidenceRecord.kind == "signal"))).one()
    assert record.payload["step_index"] == 0
    pulse = await classroom_mod.pulse(db, lesson.session)
    alice = next(s for s in pulse.students if s.student_id == lesson.alice.id)
    assert alice.state == "working"


async def test_the_teachers_alert_rule_raises_the_alert_even_when_the_agent_does_not(db, lesson):
    brief = LessonBrief.model_validate(lesson.contract.brief)
    brief.rules = PolicyRules(
        escalations=[Escalation(signal=SignalKind.STRUGGLING, after=1, action=TriageAction.ALERT)]
    )
    lesson.contract.brief = brief.model_dump(mode="json")
    await db.commit()
    client = ScriptedClient(
        [
            turn(
                "Not quite. What did you do first?",
                move="hint",
                student_attempted=True,
                assessment={"judgment": "not_met", "evidence_quote": "x is 7"},
                signals=[{"kind": "struggling", "note": "Stuck.", "tell_teacher": False}],
            )
        ]
    )
    await student_says(db, lesson, client, "x is 7")
    kinds = (await db.scalars(select(Exception_.kind))).all()
    assert kinds == [ExceptionKind.STRUGGLING.value]


async def test_a_wellbeing_alert_keeps_what_was_first_said(db, lesson):
    def upset(note):
        return turn(
            "That sounds hard. Shall we take it slowly?",
            signals=[{"kind": "wellbeing", "note": note, "tell_teacher": True}],
        )

    client = ScriptedClient([upset("First: says everyone hates them."), upset("Back to work.")])
    await student_says(db, lesson, client, "everyone hates me")
    await student_says(db, lesson, client, "ok what next")
    alert = (await db.scalars(select(Exception_))).one()
    assert alert.summary.startswith("First: says everyone hates them.")
    assert "Later: Back to work." in alert.summary


def test_the_example_button_never_gets_through_a_lesson_without_hints():
    from app.agent.brief import Step
    from app.enums import AgentMove, Disclosure, StepKind

    step = Step(name="Warm up", kind=StepKind.QUESTION, goal="Solve 3x + 4 = 19")
    no_hints = PolicyRules(hints_allowed=False)
    verdict = supervisor.review(
        message="Here is a similar one worked through: 2x + 1 = 7, so 2x = 6, x = 3.",
        move=AgentMove.EXAMPLE,
        disclosure=Disclosure.PARTIAL,
        judgment=None,
        step=step,
        rules=no_hints,
        attempts_on_step=0,
        is_retry=False,
        worked_example=True,
    )
    assert not verdict.accepted


async def test_a_student_who_only_opened_the_lesson_is_not_marked(client, db, lesson):
    await student_says(db, lesson, ScriptedClient([turn("Hi! Solve 3x + 4 = 19.")]), None)
    ended = await press(client, lesson, "end", session_id=lesson.session.id)
    card = last_card(ended)
    assert (card["took_part"], card["can_suggest"], card["students_without_outcome"]) == (
        False,
        False,
        [],
    )


# ---------- research ----------


async def test_previous_and_next_follow_the_students_who_took_part(db, lesson, client):
    for student in (lesson.alice, lesson.bob):
        await student_says(db, lesson, ScriptedClient([turn("Hi!")]), None, student=student)
    key = {"X-GenAI4ED-Pseudonym": lesson.teacher.pseudonym}
    base = f"/api/research/lessons/{lesson.session.id}/students"
    alice = (await client.get(f"{base}/{lesson.alice.id}", headers=key)).json()
    bob = (await client.get(f"{base}/{lesson.bob.id}", headers=key)).json()
    assert alice["next"]["pseudonym"] == "10B-02" and alice["previous"] is None
    assert bob["previous"]["pseudonym"] == "10B-01" and bob["next"] is None
    # Nobody else's page: a student who was never in the lesson, or the teacher.
    for who in (lesson.outsider.id, lesson.teacher.id):
        assert (await client.get(f"{base}/{who}", headers=key)).status_code == 404


async def test_the_export_carries_lessons_ratings_outcomes_and_the_approach(
    db, lesson, tmp_path: Path
):
    await student_says(db, lesson, ScriptedClient([turn("Hi!")]), None)
    await research.export(db, tmp_path)
    for name in ("lessons", "participants", "ratings", "outcomes", "turns", "alerts"):
        assert (tmp_path / f"{name}.csv").exists(), name
    header = (tmp_path / "turns.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "approach" in header and "answered" in header


# ---------- the second round: the code review and the browser tests of 19 October ----------


def _hint(message="Think about what is added to 3x."):
    return turn(
        message,
        move="hint",
        student_attempted=True,
        disclosure="hint",
        assessment={"judgment": "not_met", "evidence_quote": "x is 7"},
    )


async def test_the_research_conversation_shows_an_alert_that_cleared_itself(db, lesson, client):
    await student_says(db, lesson, ScriptedClient([turn("Hi!")]), None)
    alert = _alert(lesson.session, lesson.alice, kind=ExceptionKind.STRUGGLING)
    alert.status = ExceptionStatus.RESOLVED.value
    alert.payload = {"cleared_because": "moved on to step 2", "cleared_at": "2026-10-19T08:00:00Z"}
    db.add(alert)
    await db.commit()
    key = {"X-GenAI4ED-Pseudonym": lesson.teacher.pseudonym}
    url = f"/api/research/lessons/{lesson.session.id}/students/{lesson.alice.id}"
    r = await client.get(url, headers=key)
    assert r.status_code == 200
    cleared = [e for e in r.json()["teacher"] if e["what"] == "cleared"]
    assert [e["at"] for e in cleared] == ["2026-10-19T08:00:00Z"]


async def test_the_purge_takes_the_words_and_keeps_the_counts_the_ratings_and_who_took_part(
    db, lesson, client, tmp_path: Path
):
    await student_says(db, lesson, ScriptedClient([_hint()]), "x is 7")
    reply = (await db.scalars(select(Message).where(Message.role == "agent"))).one()
    reply.data = {**reply.data, "helped": True, "rated_at": "2026-10-19T08:00:00Z"}
    await db.commit()
    key = {"X-GenAI4ED-Pseudonym": lesson.teacher.pseudonym}

    async def totals():
        return (await client.get("/api/research/summary", headers=key)).json()["totals"]

    assert ((before := await totals())["hints"], before["helped"]) == (1, 1)
    gone = await research.purge(db, now=datetime.now(UTC) + timedelta(days=8))
    assert gone["messages"] == 2 and gone["turn_texts"] == 1
    kept = (await db.scalars(select(AgentTurn).where(AgentTurn.mode == "student"))).one()
    assert "text" not in kept.request and kept.request["answered"] is True
    assert "raw" not in kept.response and kept.response["kept"]["disclosure"] == "hint"
    assert "message" not in kept.response["kept"]
    after = await totals()
    assert (after["hints"], after["helped"]) == (1, 1)
    assert lesson.alice.id in await classroom_mod.students_who_wrote(db, lesson.session.id)
    await research.export(db, tmp_path)
    rows = list(csv.DictReader((tmp_path / "ratings.csv").open(encoding="utf-8")))
    assert [r["helped"] for r in rows] == ["True"]
    # A second purge finds nothing more to take.
    assert (await research.purge(db, now=datetime.now(UTC) + timedelta(days=9)))["turn_texts"] == 0


async def test_a_failed_turn_loses_the_students_words_with_the_chat(db, lesson):
    with pytest.raises(AgentUnavailable):
        await student_says(db, lesson, ScriptedClient([]), "my own words here")
    await research.purge(db, now=datetime.now(UTC) + timedelta(days=8))
    failed = (await db.scalars(select(AgentTurn))).one()
    assert "text" not in failed.request and "error" in failed.response


async def test_dealt_with_on_the_outcomes_card_keeps_the_card_on_screen(client, db, lesson):
    db.add(_alert(lesson.session, lesson.alice))
    await db.commit()
    ended = await press(client, lesson, "end", session_id=lesson.session.id)
    assert last_card(ended)["type"] == "outcomes"
    alert = (await db.scalars(select(Exception_))).one()
    kept = await press(client, lesson, "acknowledge", exception_id=alert.id)
    assert last_card(kept)["type"] == "outcomes" and last_card(kept)["alerts"] == []


def test_a_line_without_a_full_stop_is_its_own_sentence_for_the_checks():
    reply = "Here is the class right now:\nAva is stuck on step 2.\nBen has finished."
    invented = supervisor.names_without_evidence(reply, {"Ava"})
    assert supervisor.strike(reply, invented) == "Here is the class right now:\nBen has finished."
    claim = "I've approved the lesson for 10B\n1. Fine with the default timing?"
    assert supervisor.claims_teacher_action(claim) == ["I've approved the lesson for 10B"]


def test_copying_a_rule_that_turns_worked_steps_round_never_says_it_backwards():
    rewrite = approaches.rules_text_for
    assert rewrite("No worked steps until after two tries.", "direct") == (
        "Worked steps from the start, before any try."
    )
    fine = "Worked examples are fine, but never write their paragraph for them."
    assert rewrite(fine, "inquiry") == (
        "Never write their paragraph for them. Worked steps only after two tries."
    )
    plain = "Show worked steps after one try, never just give the final value."
    assert rewrite(plain, "direct") == (
        "Show worked steps from the start, never just give the final value."
    )


async def test_moving_on_clears_only_the_struggling_from_the_steps_behind(db, lesson):
    for step in (0, 1):
        alert = _alert(lesson.session, lesson.alice, kind=ExceptionKind.STRUGGLING)
        alert.payload = {"step_index": step}
        db.add(alert)
    await db.commit()
    right = turn(
        "Yes. Now try 5x - 7 = 2x + 8.",
        move="advance",
        student_attempted=True,
        assessment={"judgment": "met", "evidence_quote": "x is 5 because 15/3"},
    )
    await student_says(db, lesson, ScriptedClient([right]), "x is 5 because 15/3")
    alerts = (await db.scalars(select(Exception_))).all()
    assert {a.payload["step_index"]: a.status for a in alerts} == {0: "resolved", 1: "open"}


async def test_a_misconception_raised_by_the_teachers_rule_stays_with_its_student(db, lesson):
    brief = LessonBrief.model_validate(lesson.contract.brief)
    brief.rules = PolicyRules(
        escalations=[
            Escalation(signal=SignalKind.MISCONCEPTION, after=1, action=TriageAction.ALERT)
        ]
    )
    lesson.contract.brief = brief.model_dump(mode="json")
    await db.commit()

    def wrong(note):
        return turn(
            "Not quite. What did you do first?",
            move="hint",
            student_attempted=True,
            assessment={"judgment": "not_met", "evidence_quote": "x is 23"},
            signals=[{"kind": "misconception", "note": note}],
        )

    await student_says(db, lesson, ScriptedClient([wrong("Adds 4 to both sides.")]), "x is 23")
    await student_says(
        db, lesson, ScriptedClient([wrong("Divides first.")]), "x is 19/3", student=lesson.bob
    )
    alerts = {a.student_id: a.summary for a in (await db.scalars(select(Exception_))).all()}
    assert alerts == {lesson.alice.id: "Adds 4 to both sides.", lesson.bob.id: "Divides first."}


async def test_the_export_takes_a_runs_approach_from_the_students_turns_only(
    db, lesson, tmp_path: Path
):
    lesson.contract.approach = "direct"
    await db.commit()
    await student_says(db, lesson, ScriptedClient([turn("Hi!")]), None)
    # The end-of-lesson review is a turn of the run too, with no approach in it.
    db.add(
        AgentTurn(
            session_id=lesson.session.id,
            mode="review",
            context_manifest={},
            policy_version="class-agent-v1",
            prompt_version="review-v2",
            provider="scripted",
            model="scripted",
            latency_ms=0,
            validation_outcome="ok",
            leakage_check="skipped",
            conflicts=[],
            request={},
            response={},
        )
    )
    await db.commit()
    await research.export(db, tmp_path)
    rows = list(csv.DictReader((tmp_path / "lessons.csv").open(encoding="utf-8")))
    assert [r["approach"] for r in rows] == ["direct"]


async def test_ask_my_teacher_waits_for_dealt_with_and_the_lesson_still_opens_after_a_pause(
    app, client, db, lesson
):
    sid, alice = lesson.session.id, lesson.headers(lesson.alice)
    lesson.session.status = "paused"
    await db.commit()
    first = (await client.post(f"/api/learn/{sid}/request-teacher", headers=alice)).json()
    again = (await client.post(f"/api/learn/{sid}/request-teacher", headers=alice)).json()
    assert first["asked_teacher"] and again["asked_teacher"]
    signals = (
        await db.scalars(select(EvidenceRecord).where(EvidenceRecord.kind == "signal"))
    ).all()
    assert len(signals) == 1 and [line["who"] for line in again["lines"]] == ["note"]

    lesson.session.status = "open"
    await db.commit()
    scripted = llm.ScriptedClient([turn("Hi! Solve 3x + 4 = 19.")])
    app.dependency_overrides[llm.get_llm_client] = lambda: scripted
    opened = (await client.post(f"/api/learn/{sid}/start", headers=alice)).json()
    assert "agent" in [line["who"] for line in opened["lines"]]

    alert = (await db.scalars(select(Exception_))).one()
    await press(client, lesson, "acknowledge", exception_id=alert.id)
    assert (await client.get(f"/api/learn/{sid}", headers=alice)).json()["asked_teacher"] is False


async def test_a_first_code_leaves_a_signed_in_student_signed_in(client, db, classroom):
    signed_in = AuthSession(
        token_digest=token_digest(new_token()),
        user_id=classroom.alice.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(signed_in)
    await db.commit()
    url = f"/api/teacher/classes/{classroom.klass.id}/join-codes"
    teacher = classroom.headers(classroom.teacher)
    params = {"student_id": str(classroom.alice.id)}
    assert (await client.post(url, params=params, headers=teacher)).status_code == 200
    await db.refresh(signed_in)
    assert signed_in.revoked_at is None
    # A second code replaces the first, and that does sign them out.
    assert (await client.post(url, params=params, headers=teacher)).status_code == 200
    await db.refresh(signed_in)
    assert signed_in.revoked_at is not None


# ---------- the third round: the review of the second ----------


async def test_opening_a_lesson_page_never_puts_it_in_a_study_arm(client, db, lesson, monkeypatch):
    monkeypatch.setattr(get_settings(), "study_active", True)
    seen = await client.get(f"/api/learn/{lesson.session.id}", headers=lesson.headers(lesson.alice))
    assert seen.status_code == 200
    here = (
        await db.scalars(
            select(SessionParticipant).where(
                SessionParticipant.session_id == lesson.session.id,
                SessionParticipant.student_id == lesson.alice.id,
            )
        )
    ).one()
    await db.refresh(here)
    assert not here.condition


async def test_a_copy_of_a_lesson_with_long_rules_is_still_a_lesson_the_thread_can_read(
    client, db, lesson
):
    brief = LessonBrief.model_validate(lesson.contract.brief)
    brief.rules_text = ("Be patient and kind with every student. " * 80)[:2990]
    lesson.contract.brief = brief.model_dump(mode="json")
    await db.commit()
    copied = await press(
        client, lesson, "copy_with_approach", lesson_id=lesson.contract.id, text="inquiry"
    )
    assert copied.status_code == 200
    rules = last_card(copied)["rules_text"]
    assert len(rules) <= 3000 and rules.endswith("Worked steps only after two tries.")
    thread = await client.get("/api/teacher/thread", headers=lesson.headers(lesson.teacher))
    assert thread.status_code == 200


def test_the_direct_rule_copied_as_inquiry_leaves_no_stray_clause():
    direct = approaches.RULE_WORDS["direct"]
    assert approaches.rules_text_for(direct, "inquiry") == approaches.RULE_WORDS["inquiry"]


def test_a_purged_retry_reason_keeps_the_kind_of_problem_and_no_draft_words():
    said = "Your reply did not fit what was asked: 1 error, input_value='Jordan, 14 Birch Road'"
    assert research._before_draft(said) == "Your reply did not fit what was asked"
    assert research._before_draft("Not JSON. The draft began: 'hello'") == "Not JSON."


def test_a_struck_list_item_goes_with_its_number_and_the_truth_is_said_once():
    reply = "Here is what I did:\n1. I've approved the lesson for 10B.\n2. Pick a class next."
    out = supervisor.without_claims(reply, supervisor.claims_teacher_action(reply))
    assert "1." not in out.split("\n") and out.count("I haven't done that.") == 1
    again = supervisor.without_claims(out, supervisor.claims_teacher_action(out))
    assert again.count("I haven't done that.") == 1


def test_a_silent_student_is_found_by_their_whole_name_only():
    assert supervisor.names_without_evidence("The class will start soon.", {"Will"}) == []
    named = supervisor.names_without_evidence("Ava Smith is doing great.", {"Ava Smith"})
    assert named == ["Ava Smith is doing great."]
