"""The tutor pitching each step for the student in front of it: when the lesson's teacher lets
it adapt, the tutor is told what stays fixed and what is its own to change, and decides for
itself. The server makes no choice for it: it sends the wording, and keeps the one line the
tutor writes on what it changed and why. A scripted tutor plays the lesson; the prompt it was
handed and the record it left are read back. No model is called."""

from sqlalchemy import select

from app import research
from app.agent import classroom, scaffold
from app.agent.brief import LessonBrief
from app.agent.policy import PolicyRules
from app.agent.tutor_reply import StudentTurnOut
from app.enums import MessageRole, PitchCall, PitchDial
from app.models import AgentTurn, Message
from tests.test_learner_note_written import about, review, shown, written
from tests.test_memory_across_lessons import (
    BRACKETS,
    end,
    first_lesson,
    next_lesson,
    shown_at_the_start,
)
from tests.test_memory_settings import MEMORY, set_memory
from tests.test_what_the_record_shows import lesson, met, turn

HEADING = "Pitching each step for this student"
# The heading as a line of its own. The reply shape, which every tutor is sent, names it too.
TOLD = f"\n{HEADING}\n"
WHY = "One more unknown: got one-step equations right with no help last lesson."
FIRST = "3x = 15 so x = 5"
STRETCHED = {"pitch_call": "stretched", "pitch_changed": ["Load", "Reasoning"]}


async def adapting(client, c):
    return await set_memory(client, c, adapt_to_student=True)


async def turns(db):
    return (await db.scalars(select(AgentTurn).order_by(AgentTurn.created_at))).all()


async def replies(db):
    """What was kept with each of the tutor's messages, in order."""
    said = await db.scalars(
        select(Message).where(Message.role == MessageRole.AGENT.value).order_by(Message.created_at)
    )
    return [m.data for m in said.all()]


# ---------- the switch ----------


async def test_the_tutor_does_not_adapt_until_the_teacher_lets_it(client, three):
    r = await client.get(MEMORY, headers=three.headers(three.teacher))
    assert r.json()["settings"]["adapt_to_student"] is False
    assert (await adapting(client, three))["settings"]["adapt_to_student"] is True
    r = await client.get(MEMORY, headers=three.headers(three.teacher))
    assert r.json()["settings"]["adapt_to_student"] is True


async def test_switched_off_the_tutor_is_told_nothing_of_it_and_no_line_is_kept(db, client, three):
    await lesson(client, three, (FIRST, {**met(FIRST), "pitch": WHY}))

    assert all(TOLD not in call["system"] for call in three.tutor.calls)
    assert [t.context_manifest["pitch"] for t in await turns(db)] == [False, False]
    # A line the tutor wrote without being asked for one is not kept as its judgment.
    assert [kept.get("pitch") for kept in await replies(db)] == [None, None]


# ---------- what the tutor is told ----------


async def test_switched_on_the_tutor_is_told_how_to_pitch_on_every_turn(db, client, three):
    await adapting(client, three)
    await lesson(client, three, (FIRST, met(FIRST)))

    for call in three.tutor.calls:
        system = call["system"]
        assert system.count(TOLD) == 1
        # After the help it may give, which it does not change, and before the counts.
        assert (
            system.index("Allowed right now")
            < system.index(TOLD)
            < system.index("What the platform noticed")
        )
        # This pupil's own, so not in the opening every pupil in the lesson shares.
        assert TOLD not in call["cache_prefix"]
    assert [t.context_manifest["pitch"] for t in await turns(db)] == [True, True]


async def test_it_comes_after_what_is_remembered_of_the_student(db, client, three):
    await adapting(client, three)
    await first_lesson(client, three)
    await next_lesson(db, three)

    system = await shown_at_the_start(client, three)

    assert system.index(scaffold.BEFORE) < system.index(scaffold.BEFORE_USE) < system.index(TOLD)


async def test_a_pupil_in_a_study_arm_is_taught_the_step_as_written(db, client, three):
    await adapting(client, three)
    await next_lesson(db, three, BRACKETS, condition={"memory": False})

    assert TOLD not in await shown_at_the_start(client, three)


def test_the_wording_says_what_stays_fixed_and_what_is_the_tutors_to_change():
    said = scaffold.PITCH
    assert said.startswith(HEADING + "\n")
    for fixed in ("objective", "finish line", "help rules"):
        assert fixed in said, fixed
    for dial in (
        "Support",
        "Openness",
        "Reasoning",
        "Load",
        "Transfer",
        "Precision",
        "Judgement",
        "Voice",
        "Language",
    ):
        assert f"- {dial}." in said, dial
    # The tutor decides: nothing here is a count or a threshold the server worked out.
    assert "yours to decide" in said
    # Whether to stay with its own version or let it go is one judgement, made after every
    # reply from what the student wrote, with no count of goes.
    assert "is my version still within this student's reach today?" in said
    assert "- Within reach:" in said and "- Out of reach:" in said
    assert "There is no set number of goes." in said
    assert "stay with it" in said and "ask the step as written" in said
    # In a run, "i cant do this one" right after one explanation was taken as losing heart.
    assert '"I can\'t do this" says how they feel.' in said
    # A hard step earlier does not settle the next one, and the record yields to today.
    assert "Every new step is a fresh decision" in said
    assert "pitch from where they are today" in said
    assert "ease off" not in said
    # One example, in no one subject, showing both calls and what decided them.
    assert said.count("Example.") == 1
    example = said[said.index("Example.") :]
    assert example.index("You stay") < example.index("You would let it go")
    assert "not how many goes" in example
    # A miss on the tutor's own version is no wrong try at the step.
    assert "student_attempted false" in said
    assert "pitch" in said.splitlines()[-1]
    # The line records what decided a stay or a let go, so the choice can be measured.
    assert "say what you saw that decided it" in said.splitlines()[-1]


# ---------- the tutor's own line on what it changed ----------


async def test_the_tutors_line_on_what_it_changed_is_kept_with_its_reply(db, client, three):
    await adapting(client, three)
    await lesson(client, three, (FIRST, {**met(FIRST), "pitch": WHY, **STRETCHED}))

    kept = await replies(db)
    assert [k.get("pitch") for k in kept] == ["", WHY]
    # Its call and what it changed, in words the research view can count.
    assert [k.get("pitch_call") for k in kept] == [None, "stretched"]
    assert [k.get("pitch_changed") for k in kept] == [[], ["Load", "Reasoning"]]


async def test_switched_off_no_call_is_kept_either(db, client, three):
    await lesson(client, three, (FIRST, {**met(FIRST), **STRETCHED}))

    for kept in await replies(db):
        assert "pitch_call" not in kept and "pitch_changed" not in kept


def test_the_reply_shape_has_the_line_and_it_may_be_left_out():
    left_out = StudentTurnOut.model_validate(turn("Hi."))
    assert (left_out.pitch, left_out.pitch_call, left_out.pitch_changed) == ("", None, [])
    described = StudentTurnOut.model_json_schema()["properties"]["pitch"]["description"]
    assert "student never sees" in described
    assert HEADING in described


def test_the_things_it_may_change_are_the_ones_the_prompt_lists():
    listed = [
        line[2:].split(".")[0]
        for line in scaffold.PITCH.splitlines()
        if line.startswith("- ") and line.split(" ")[1].endswith(".")
    ]
    assert [d.value for d in PitchDial] == listed
    assert [c.value for c in PitchCall] == [
        "as written",
        "stretched",
        "more support",
        "stayed",
        "let go",
    ]


def test_a_label_it_made_up_is_dropped_not_a_broken_reply():
    out = StudentTurnOut.model_validate(
        turn("Hi.", pitch_changed=["Reasoning", "Bananas"], pitch_call="sideways")
    )
    assert out.pitch_changed == [PitchDial.REASONING]
    assert out.pitch_call is None


def test_when_the_words_are_cleared_the_call_and_what_changed_stay_to_be_counted():
    reply = {"message": "Which mattered most?", "pitch": WHY, **STRETCHED}
    kept = research._without_words(reply)
    assert (kept["pitch_call"], kept["pitch_changed"]) == ("stretched", ["Load", "Reasoning"])
    # The line is the tutor's words about a student, so it goes with the rest of the words.
    assert "pitch" not in kept and "message" not in kept


# ---------- the teacher's words for one lesson win over the setting ----------


async def lesson_rule(db, c, adapt):
    brief = LessonBrief.model_validate(c.contract.brief)
    brief.rules.adapt_to_student = adapt
    c.contract.brief = brief.model_dump(mode="json")
    await db.commit()


async def test_same_questions_for_everyone_in_this_lesson_turns_it_off_here(db, client, three):
    await adapting(client, three)
    await lesson_rule(db, three, False)
    await lesson(client, three, (FIRST, met(FIRST)))

    assert all(TOLD not in call["system"] for call in three.tutor.calls)
    assert [t.context_manifest["pitch"] for t in await turns(db)] == [False, False]


async def test_pitch_for_each_student_in_this_lesson_turns_it_on_here(db, client, three):
    await lesson_rule(db, three, True)
    await lesson(client, three, (FIRST, met(FIRST)))

    assert all(TOLD in call["system"] for call in three.tutor.calls)


def test_the_card_and_the_rules_read_back_say_which():
    said = {
        adapt: (
            PolicyRules(adapt_to_student=adapt).labels()["pills"],
            PolicyRules(adapt_to_student=adapt).describe(),
        )
        for adapt in (None, False, True)
    }
    assert "Same questions for everyone" in said[False][0]
    assert "Every student is asked each step as written." in said[False][1]
    assert "Pitched for each student" in said[True][0]
    assert "The tutor pitches each step for each student." in said[True][1]
    # Nothing said: the teacher's setting decides, and the card adds nothing.
    assert not any("questions" in p or "Pitched" in p for p in said[None][0])


# ---------- what the teacher sees, and the student never does ----------

SECOND = "x = 2"


async def stretched_then_met(client, c):
    """Step 1 met; the tutor asks its own version of step 2, which the student then meets."""
    await adapting(client, c)
    await lesson(
        client,
        c,
        (FIRST, {**met(FIRST), "pitch": WHY, **STRETCHED}),
        (SECOND, {**met(SECOND), "pitch": "As written: met it.", "pitch_call": "as written"}),
    )


async def test_the_teacher_sees_the_note_beside_the_tutors_message(db, client, three):
    await stretched_then_met(client, three)

    card = await classroom.student_view(db, three.session, three.alice, conversation=True)
    said = [line for line in card["conversation"] if line["who"] == "agent"]
    assert said[1]["pitch"] == {
        "line": WHY,
        "call": "stretched",
        "changed": ["Load", "Reasoning"],
    }
    # The opening said nothing about pitching, so nothing shows under it.
    assert said[0]["pitch"] is None
    assert all("pitch" not in line for line in card["conversation"] if line["who"] != "agent")


async def test_the_student_never_sees_it(client, three):
    await stretched_then_met(client, three)

    r = await client.get(f"/api/learn/{three.session.id}", headers=three.headers(three.alice))
    assert r.status_code == 200
    assert WHY not in r.text and "pitch" not in r.text


async def test_the_research_pages_show_it_and_count_the_calls_by_model(client, three, researcher):
    await stretched_then_met(client, three)

    url = f"/api/research/lessons/{three.session.id}/students/{three.alice.id}"
    items = (await client.get(url, headers=researcher)).json()["items"]
    assert [i["pitch"]["call"] for i in items if i["kind"] == "agent" and i["pitch"]] == [
        "stretched",
        "as written",
    ]

    for page in ("/api/research/summary", f"/api/research/lessons/{three.session.id}"):
        (row,) = (await client.get(page, headers=researcher)).json()["pitching"]
        assert row["turns"] == 3
        assert row["calls"] == {
            "as written": 1,
            "stretched": 1,
            "more support": 0,
            "stayed": 0,
            "let go": 0,
        }
        # Met while the tutor's own version was the question.
        assert row["met_on_its_version"] == 1
        assert row["changed"] == [{"thing": "Load", "times": 1}, {"thing": "Reasoning", "times": 1}]


async def test_switched_off_nothing_is_counted(client, three, researcher):
    await lesson(client, three, (FIRST, {**met(FIRST), **STRETCHED}))

    summary = await client.get("/api/research/summary", headers=researcher)
    assert summary.json()["pitching"] == []


# ---------- what carries into their next lessons ----------

MEETS = "Meets a harder question once given a first move."


async def test_the_review_is_shown_how_each_step_was_pitched_for_the_student(db, client, three):
    await stretched_then_met(client, three)
    await end(client, three)

    asked = await review(db, three, about(three.alice, MEETS))

    [alice] = shown(asked)["students"]
    assert [(p["call"], p["changed"], p["note"]) for p in alice["pitched"]] == [
        ("stretched", ["Load", "Reasoning"], WHY),
        ("as written", [], "As written: met it."),
    ]
    assert [p["answer_before"] for p in alice["pitched"]] == ["met", "met"]
    # It is asked to carry what that shows into how they learn, which their next lessons read.
    system = asked.calls[-1]["system"]
    assert '"pitched", when present' in system
    assert await written(db, three.alice) == [MEETS]


async def test_a_lesson_without_pitching_hands_the_review_nothing_new(db, client, three):
    await lesson(client, three, (FIRST, {**met(FIRST), "pitch": WHY, **STRETCHED}))
    await end(client, three)

    asked = await review(db, three, about(three.alice, MEETS))

    [alice] = shown(asked)["students"]
    assert "pitched" not in alice


# ---------- the wording has a version ----------


def test_the_version_changes_with_the_pitch_wording(monkeypatch):
    before = scaffold.version(schema={})
    assert before.startswith("student-v21-")
    monkeypatch.setattr(scaffold, "PITCH", scaffold.PITCH + " ")
    assert scaffold.version(schema={}) != before
