"""The structured student prompt (v9 and v10): fixed prose, scaffold slots the server fills,
checks and measures, and the depth of knowledge a step asks for."""

# ruff: noqa: F811 - `lesson` is a fixture imported from the student agent tests

import json

import pytest
from sqlalchemy import select

from app.agent import llm, scaffold, supervisor
from app.agent.brief import LessonBrief, Step
from app.agent.llm import ScriptedClient, bare_schema
from app.agent.policy import PolicyRules
from app.agent.student_mode import StudentTurnOut
from app.enums import AgentMove, Disclosure, Judgment, StepKind
from app.models import AgentTurn, EvidenceRecord
from tests.test_agent_student import BRIEF, lesson, turn  # noqa: F401 - `lesson` is a fixture
from tests.test_agent_student import say as student_says
from tests.test_thread import last_card, press

# ---------- the scaffold ----------


def test_the_step_block_carries_the_finish_line_and_the_next_question_but_no_later_answer():
    block = scaffold.step_block(BRIEF, 0, task="Solve 3x + 4 = 19")
    assert 'Step 1 of 2, "Warm up", a question step' in block
    assert "Done when: x = 5 with working" in block
    assert 'reference answer is "5"' in block and "For judging only" in block
    assert 'Coming next: step 2, "Both sides"' in block
    assert "This is the last step" not in block
    last = scaffold.step_block(BRIEF, 1, task=None)
    assert "This is the last step" in last and "Target depth:" in last


def test_a_step_without_a_finish_line_says_so_and_keeps_the_lesson_from_approval():
    brief = BRIEF.model_copy(deep=True)
    brief.steps[1].success_criteria = []
    assert "No finish line was written" in scaffold.step_block(brief, 1, task=None)
    assert "what counts as done for step 2" in brief.missing()
    brief.steps[1].success_criteria = ["x = 5 with the x terms collected"]
    assert not brief.missing()


def test_the_allowed_block_says_now_next_and_never_from_the_rules():
    rules = PolicyRules(partial_after_attempts=2, full_answer_after_attempts=None)
    brief = BRIEF.model_copy(update={"rules": rules})
    first = scaffold.allowed_block(brief, attempts=0, allowed=Disclosure.HINT, guidance=[])
    assert "a hint (a cue to the idea" in first
    assert "A worked example or a step done together: after 2 more wrong tries." in first
    assert "The answer itself: never in this lesson." in first
    assert "Teacher's guidance for this student: none." in first
    later = scaffold.allowed_block(
        brief, attempts=2, allowed=Disclosure.PARTIAL, guidance=["Go gently with them."]
    )
    assert "one step of this problem done together" in later
    assert "outranks everything above" in later and "Go gently with them." in later


def test_the_noticed_block_counts_instead_of_the_prose_guessing():
    text = scaffold.noticed_block(
        scaffold.Noticed(
            attempts=2,
            hints=1,
            bare_streak=3,
            bare_gap_seconds=40,
            minutes_in=12,
            planned_minutes=20,
            steps_after=1,
            asked_teacher_open=True,
            class_slip="Adds 4 to both sides",
            class_slip_count=2,
        )
    )
    assert "Wrong tries on this step: 2. Help given on this step: 1 hint, 0 worked examples" in text
    assert "The last 3 messages were bare answers with no working, about 40 seconds apart" in text
    assert "12 minutes in, of 20 planned, with 1 step after this one" in text
    assert "pressed Ask my teacher" in text
    assert "2 others in this class slipped on this step: Adds 4 to both sides" in text


def test_the_version_names_the_wording_and_the_schema(monkeypatch):
    schema = bare_schema(StudentTurnOut.model_json_schema())
    v10 = scaffold.version(schema=schema)
    assert v10.startswith("student-v10-")
    # Descriptions reach the model now: the schema the version is named by carries them.
    assert "depth_shown" in schema["$defs"]["AssessmentOut"]["properties"]
    assert (
        "lower level"
        in schema["$defs"]["AssessmentOut"]["properties"]["depth_shown"]["description"]
    )
    assert "description" in json.dumps(schema)
    monkeypatch.setattr(scaffold, "TALK", scaffold.TALK + " ")
    assert scaffold.version(schema=schema) != v10


async def test_the_tutor_is_told_the_step_as_sentences_and_the_data_block_stays(db, lesson):
    client = ScriptedClient([turn("Hi! Solve 3x + 4 = 19.", task="Solve 3x + 4 = 19")])
    await student_says(db, lesson, client, None)
    system = client.calls[0]["system"]
    assert "This step\nStep 1 of 2" in system
    assert "Allowed right now\nHelp you may give on this try: a hint" in system
    assert "What the platform noticed\nWrong tries on this step: 0" in system
    assert "Right now\nThe student has just opened the lesson" in system
    assert "Never\n- State this step's reference answer" in system
    # The later step's answer is not in the prompt at all; the current one is, for judging.
    # The schema follows the data block, so read only the first object.
    data, _ = json.JSONDecoder().raw_decode(
        system.split("The lesson and where this student is:\n", 1)[1]
    )
    assert "reference_answer" not in json.dumps(data)
    assert system.count('reference answer is "5"') == 1


async def test_the_prompt_is_filled_from_one_record_and_says_what_the_turn_is(db, lesson):
    """The record is read once. The prose says what the turn is every time; the data block
    carries it only when it is an event (an opening, the teacher's words, a finished lesson)."""
    client = ScriptedClient(
        [
            turn("Hi! Solve 3x + 4 = 19.", task="Solve 3x + 4 = 19"),
            turn("Nearly: what do you take from both sides first?", task="Solve 3x + 4 = 19"),
            turn("You added 4 instead of taking it away.", task="Solve 3x + 4 = 19"),
        ]
    )
    await student_says(db, lesson, client, None)
    await student_says(db, lesson, client, "x = 4")
    await student_says(db, lesson, client, "why is it wrong?", intent="why_wrong")
    opening, reply, pressed = (c["system"] for c in client.calls)

    def data_of(system: str) -> dict:
        return json.JSONDecoder().raw_decode(system.split(scaffold.DATA_LABEL, 1)[1])[0]

    assert "Right now\nThe student has just opened" in opening
    assert data_of(opening)["now"].startswith("The student has just opened")
    assert 'reference answer is "5"' in opening
    assert "Right now\nCarry on from what they just wrote." in reply
    assert "now" not in data_of(reply)
    assert "Right now\nThey pressed a help button: Why is my answer wrong?" in pressed
    assert data_of(pressed)["student_used_button"] == "Why is my answer wrong?"
    assert "now" not in data_of(pressed)
    audit = (await db.scalars(select(AgentTurn).order_by(AgentTurn.created_at))).all()
    assert all(a.prompt_version.startswith("student-v10-") for a in audit)


# ---------- checks and measures ----------


def test_moving_on_with_a_partly_right_answer_is_sent_back():
    verdict = supervisor.review(
        message="Nearly. Let's move on to the next one.",
        move=AgentMove.ADVANCE,
        disclosure=Disclosure.NONE,
        judgment=Judgment.PARTIAL,
        step=BRIEF.steps[0],
        rules=PolicyRules(),
        attempts_on_step=1,
        is_retry=False,
    )
    assert not verdict.accepted and "partial answer, not a met one" in verdict.reason


def test_the_measures_count_what_the_prose_used_to_ask_for():
    m = supervisor.measures(
        message="Good try, 9B-02 found this hard too.\nWhat is 10% of 80?",
        task="What is 10% of 80?",
        previous="Good try, keep going.\nWhat is 10% of 50?",
        classmates=["9B-02", "9B-03"],
        target_dok=2,
        depth_shown=1,
    )
    assert m["classmate_mention"] and m["question_marks"] == 1 and not m["no_next_action"]
    assert m["depth"] == {"target": 2, "shown": 1, "relation": "under", "uncertain": False}
    quiet = supervisor.measures(
        message="You get 5 marks for that. When I was at school we did this too. **Well done**",
        task=None,
        previous="You get 5 marks for that.",
    )
    assert quiet["no_next_action"] and quiet["marks_in_message"] and quiet["human_claim"]
    assert quiet["markup_chars"] == 4 and quiet["repeated_reassurance"]
    assert not supervisor.measures(message="3/4 of 12 is 9.", task="x")["marks_in_message"]


async def test_depth_and_the_measures_are_recorded_with_the_turn(db, lesson):
    reply = turn(
        "Yes, 5. How did you get there?",
        move="follow_up",
        student_attempted=True,
        task="How did you get there?",
        assessment={
            "judgment": "met",
            "evidence_quote": "5",
            "depth_shown": 1,
            "uncertain": False,
        },
    )
    await student_says(db, lesson, ScriptedClient([reply]), "5")
    judged = (
        await db.scalars(select(EvidenceRecord).where(EvidenceRecord.kind == "assessment"))
    ).one()
    assert (judged.payload["depth_shown"], judged.payload["target_dok"]) == (1, 2)
    recorded = (await db.scalars(select(AgentTurn))).one()
    assert recorded.response["measures"]["depth"]["relation"] == "under"
    assert recorded.prompt_version.startswith("student-v10-")
    assert recorded.context_manifest["target_dok"] == 2


async def test_help_given_on_a_step_is_counted_for_the_next_turn(db, lesson):
    hint = turn(
        "Think about the 4 first.",
        move="hint",
        student_attempted=True,
        disclosure="hint",
        assessment={"judgment": "not_met", "evidence_quote": "x is 7"},
    )
    await student_says(db, lesson, ScriptedClient([hint]), "x is 7")
    client = ScriptedClient([turn("What do you do to both sides?", move="ask")])
    await student_says(db, lesson, client, "i dont know")
    assert "Help given on this step: 1 hint" in client.calls[0]["system"]


# ---------- the teacher's side of it ----------


async def test_a_preview_shows_the_teacher_how_step_1_opens_without_touching_a_student(
    app, client, db, lesson
):
    scripted = llm.ScriptedClient([turn("Hi there! Let's start: solve 3x + 4 = 19.")])
    app.dependency_overrides[llm.get_llm_client] = lambda: scripted
    shown = await press(client, lesson, "preview_lesson", lesson_id=lesson.contract.id)
    assert shown.status_code == 200 and last_card(shown)["type"] == "lesson"
    texts = [m["text"] for m in shown.json()["messages"]]
    assert any(t.startswith("How step 1 would open for a student") for t in texts)
    assert "Hi there!" in texts[-1]
    assert "This step\nStep 1 of 2" in scripted.calls[0]["system"]
    turns = (await db.scalars(select(AgentTurn))).all()
    assert [t.mode for t in turns] == ["preview"] and turns[0].student_id is None


async def test_approval_clears_what_the_agent_filled_in(client, db, lesson):
    brief = LessonBrief.model_validate(lesson.contract.brief)
    brief.to_check = ["objectives", "step 2 criteria"]
    for step in brief.steps:
        step.success_criteria = step.success_criteria or ["x = 5 with working"]
    lesson.contract.brief = brief.model_dump(mode="json")
    lesson.contract.status = "draft"
    await db.commit()
    card = last_card(await press(client, lesson, "show_lesson", lesson_id=lesson.contract.id))
    assert card["to_check"] == ["objectives", "step 2 criteria"]
    assert [s["depth"] for s in card["steps"]] == [2, 2]
    approved = await press(client, lesson, "approve", lesson_id=lesson.contract.id)
    assert approved.status_code == 200
    assert last_card(approved)["to_check"] == []


def test_a_step_knows_its_depth_in_any_subject():
    history = Step(
        name="Causes",
        kind=StepKind.QUESTION,
        goal="Which cause of the fire mattered most?",
        success_criteria=["Names a cause and gives a reason from the source"],
        target_dok=3,
    )
    assert history.depth == 3
    assert Step(name="Date", kind=StepKind.CHECK, goal="When was it?").depth == 2
    with pytest.raises(ValueError):
        Step(name="x", kind=StepKind.CHECK, goal="y", target_dok=5)


def test_explaining_on_an_explain_step_is_not_over_disclosure():
    explain = Step(
        name="Remember: per cent",
        kind=StepKind.EXPLAIN,
        goal="Recall that per cent means out of 100.",
        success_criteria=["States that 10% means dividing by 10"],
    )
    verdict = supervisor.review(
        message="Per cent means out of 100. 10% is one tenth, so divide by 10. What is 10% of 50?",
        move=AgentMove.EXPLAIN,
        disclosure=Disclosure.FULL,
        judgment=None,
        step=explain,
        rules=PolicyRules(),
        attempts_on_step=0,
        is_retry=False,
    )
    assert verdict.accepted
    brief = BRIEF.model_copy(update={"steps": [explain, *BRIEF.steps]})
    block = scaffold.allowed_block(
        brief, attempts=0, allowed=Disclosure.HINT, guidance=[], explain=True
    )
    assert block.startswith("This is an explain step")
    assert "explain step" in scaffold.assemble(
        brief=brief,
        index=0,
        task=None,
        attempts=0,
        allowed=Disclosure.HINT,
        guidance=[],
        noticed=scaffold.Noticed(),
        now="x",
    )


def test_out_of_100_in_a_percentages_lesson_is_not_a_mark():
    assert not supervisor.measures(message="50% means 50 out of 100.", task="x")["marks_in_message"]
    assert supervisor.measures(message="That's 3 out of 5 marks.", task="x")["marks_in_message"]


async def test_the_tutor_is_told_when_it_has_already_asked_for_the_why(db, lesson):
    bare_right = turn(
        "Yes, 5. How did you get there?",
        move="follow_up",
        student_attempted=True,
        task="How did you get there?",
        assessment={"judgment": "met", "evidence_quote": "5", "depth_shown": 1},
    )
    await student_says(db, lesson, ScriptedClient([bare_right]), "5")
    client = ScriptedClient(
        [turn("Fine, we can leave the why. Now try 5x - 7 = 2x + 8.", move="ask")]
    )
    await student_says(db, lesson, client, "just 5")
    assert "already asked for the why on this step once" in client.calls[0]["system"]
