"""Steps that name the objective they serve, and what the lesson card says of them.

A step names its objective as its place in the lesson's list, and the card says what counts as
meeting each objective. A lesson stored before steps could name one reads as it did, and one
stored with an easier step or a deeper question, which a step could carry for a while, loads
with them dropped.
"""

import json

import pytest
from pydantic import ValidationError

from app.agent import scaffold, thread
from app.agent.brief import LessonBrief
from app.agent.llm import FRESH, bare_schema
from app.enums import ContractStatus
from tests.lessons import THREE
from tests.test_activity_in_the_lesson import OLD, _stored, scripted
from tests.test_moving_between_steps import OPEN, script, start
from tests.test_thread import last_card, press, say

# A step as it was stored, and as the agent was shown it, before it could name an objective.
TODAYS_STEP = [
    "name",
    "kind",
    "goal",
    "prompt_ideas",
    "success_criteria",
    "reference_answer",
    "activity",
    "heading",
    "activity_kind",
    "listed_kind",
]
# The current step as the tutor is given it.
TUTORS_STEP = ["name", "kind", "goal", "prompt_ideas", "success_criteria", "activity"]
# The three-step lesson as it was stored before this.
BEFORE = {**OLD, "steps": [{k: s[k] for k in TODAYS_STEP if k in s} for s in OLD["steps"]]}

SIDES = "Solve equations with the unknown on both sides"
BRACKETS = "Solve equations with brackets"
# What a step of a lesson stored while the card's extras could be switched on also held.
EASIER = {
    "question": "What do you get when you divide both sides of 2(x - 3) = 18 by 2?",
    "answer": "x - 3 = 9",
}
DEEPER = {"question": "Why can you divide by 2 before you expand the brackets?", "answer": None}
# The last two steps serve the lesson's one objective.
SERVED = {"Both sides": {"objective": 1}, "Brackets": {"objective": 1}}


def _lesson(on_steps: dict | None = None, **changes) -> dict:
    """The lesson with these fields put on the steps named."""
    steps = [{**s, **(on_steps or {}).get(s["name"], {})} for s in BEFORE["steps"]]
    return {**BEFORE, **changes, "steps": steps}


def _reply(on_steps: dict | None = None, **changes) -> dict:
    return {"reply": "Here it is.", "show": "lesson", "brief": _lesson(on_steps, **changes)}


def _shown(stored: dict) -> list[dict]:
    """The steps of a stored lesson as the agent is shown it."""
    lesson = thread.TeacherTurnServing.lesson.model_validate(stored)
    return json.loads(lesson.for_agent())["steps"]


# ---------- a lesson from before ----------


def test_a_brief_written_before_this_reads_as_it_did():
    brief = LessonBrief.model_validate(BEFORE)
    assert [s.objective for s in brief.steps] == [None] * 3
    assert brief.missing() == THREE.missing() == []
    assert brief.as_text() == THREE.as_text()
    assert LessonBrief.model_validate(brief.model_dump(mode="json")) == brief
    # What the agent is shown of it: each step as it was shown before, with nothing served.
    no_heading = {"heading": "", "activity_kind": "", "listed_kind": ""}
    assert _shown(BEFORE) == [{**s, **no_heading, "objective": None} for s in BEFORE["steps"]]


def test_a_brief_stored_with_an_easier_step_and_a_deeper_question_still_loads():
    stored = _lesson({"Brackets": {"objective": 1, "easier": EASIER, "deeper": DEEPER}})
    for shape in (LessonBrief, thread.TeacherTurnServing.lesson):
        brief = shape.model_validate(stored)
        assert [s.objective for s in brief.steps] == [None, None, 1]
        # The two are dropped: nothing reads them, and they are not written back.
        kept = json.dumps(brief.model_dump(mode="json"))
        assert "easier" not in kept and "deeper" not in kept
        assert EASIER["question"] not in brief.for_agent()


def test_the_objective_survives_being_stored_and_read_back():
    brief = LessonBrief.model_validate(_lesson(SERVED))
    again = LessonBrief.model_validate(brief.model_dump(mode="json"))
    assert again == brief
    assert [s.objective for s in again.steps] == [None, 1, 1]
    # It asks for nothing new before approval.
    assert again.missing() == []


@pytest.mark.parametrize(
    "on_first",
    [{}, {"objective": 1, "easier": EASIER, "deeper": DEEPER}],
    ids=["a lesson from before", "a step with an objective and the old extras"],
)
async def test_the_tutor_is_given_a_step_as_it_always_was(db, client, three, on_first):
    three.contract.brief = _lesson({"Warm up": on_first})
    await db.commit()
    script(three, OPEN)

    await start(client, three)

    system = three.tutor.calls[0]["system"]
    data = json.JSONDecoder().raw_decode(system.split(scaffold.DATA_LABEL, 1)[1])[0]
    for step in (data["where_the_student_is"]["step"], data["lesson_brief"]["steps"][0]):
        assert list(step) == TUTORS_STEP
    assert EASIER["question"] not in system and DEEPER["question"] not in system


# ---------- the reply shape ----------


def test_the_reply_shape_has_steps_that_name_their_objective_and_nothing_more():
    shape = json.dumps(bare_schema(thread.TeacherTurnServing.model_json_schema()))
    assert '"objective"' in shape
    for gone in ('"easier"', '"deeper"', "Extra"):
        assert gone not in shape, gone


def test_an_agent_is_shown_the_step_fields_it_can_write_and_no_others():
    schema = thread.TeacherTurnServing.model_json_schema()
    lesson = schema["$defs"][schema["properties"]["brief"]["anyOf"][0]["$ref"].split("/")[-1]]
    step = schema["$defs"][lesson["properties"]["steps"]["items"]["$ref"].split("/")[-1]]
    shown = _shown(_lesson(SERVED))
    assert [list(s) for s in shown] == [list(step["properties"])] * 3
    # The objective sits where it is read, with the goal.
    assert [name for name in step["properties"] if name != "objective"] == TODAYS_STEP
    assert [s["objective"] for s in shown] == [None, 1, 1]


def test_the_field_says_what_the_objective_number_is():
    step = thread.TeacherTurnServing.lesson.model_fields["steps"].annotation.__args__[0]
    serves = step.model_fields["objective"].description
    assert "1 for the first" in serves and "warm up" in serves


# ---------- what the server keeps ----------


def test_a_step_cannot_name_an_objective_that_is_not_there():
    # One objective on the lesson: a 2 points past the end of the list, and is cleared.
    brief = LessonBrief.model_validate(
        _lesson({"Both sides": {"objective": 1}, "Brackets": {"objective": 2}})
    )
    assert [s.objective for s in brief.steps] == [None, 1, None]
    # The same in a reply the agent has just written.
    reply = thread.TeacherTurnServing.model_validate(
        _reply({"Both sides": {"objective": 1}, "Brackets": {"objective": 2}}),
        context={FRESH: True},
    )
    assert [s.objective for s in reply.brief.steps] == [None, 1, None]
    with_two = LessonBrief.model_validate(
        _lesson({"Brackets": {"objective": 2}}, objectives=[SIDES, BRACKETS])
    )
    assert with_two.steps[2].objective == 2
    for outside in (0, 11):
        with pytest.raises(ValidationError):
            LessonBrief.model_validate(_lesson({"Brackets": {"objective": outside}}))


async def test_the_agent_writes_the_objective_numbers_and_they_are_stored(
    app, client, classroom, db
):
    model = scripted(app, _reply(SERVED))

    card = last_card(await say(client, classroom, "A lesson on linear equations."))

    assert model.calls[-1]["cache_prefix"].startswith(thread.SYSTEM)
    _, brief = await _stored(db, card)
    assert [s.objective for s in brief.steps] == [None, 1, 1]


async def test_a_change_takes_the_numbers_the_agent_writes(app, client, classroom, db):
    renumbered = {"Warm up": {"objective": 1}, "Both sides": {"objective": 1}}
    model = scripted(app, _reply(SERVED), _reply(renumbered, duration_minutes=40))
    card = last_card(await say(client, classroom, "A lesson on linear equations."))

    await say(client, classroom, "Make it 40 minutes.")

    # The agent was shown the numbers, so they are as it wrote them: one on the warm up now,
    # none on Brackets.
    assert '"objective":1' in model.calls[-1]["system"]
    _, kept = await _stored(db, card)
    assert [s.objective for s in kept.steps] == [1, 1, None]


# ---------- the teacher's card ----------

# A step on the card.
CARDS_STEP = [
    "name",
    "kind",
    "goal",
    "objective",
    "questions",
    "criteria",
    "has_reference",
    "answer",
    "activity",
]


async def test_the_card_says_what_counts_as_meeting_each_objective(app, client, classroom):
    scripted(app, _reply(SERVED))

    card = last_card(await say(client, classroom, "A lesson on linear equations."))

    # What counts as meeting an objective is the finish lines of the steps that serve it, in
    # the order of the steps. The warm up serves none, so its line is not among them.
    assert card["met_when"] == [
        {
            "objective": SIDES,
            "lines": ["x = 5 with the x terms collected", "x = 12"],
            "steps": ["Both sides", "Brackets"],
        }
    ]
    assert [s["objective"] for s in card["steps"]] == [None, 1, 1]
    # The card's steps carry no easier step or deeper question.
    assert [list(s) for s in card["steps"]] == [CARDS_STEP] * 3


async def test_two_steps_with_one_finish_line_say_it_once(app, client, classroom):
    same = _lesson(SERVED)
    both_sides, brackets = same["steps"][1:]
    same["steps"][2] = {**brackets, "success_criteria": both_sides["success_criteria"]}
    scripted(app, {"reply": "Here it is.", "show": "lesson", "brief": same})

    card = last_card(await say(client, classroom, "A lesson on linear equations."))

    assert card["met_when"][0]["lines"] == ["x = 5 with the x terms collected"]
    assert card["met_when"][0]["steps"] == ["Both sides", "Brackets"]


async def test_an_objective_no_step_serves_is_shown_and_does_not_block_approval(
    app, client, classroom
):
    scripted(app, _reply(SERVED, objectives=[SIDES, BRACKETS]))

    card = last_card(await say(client, classroom, "A lesson on linear equations."))

    # Both steps that name an objective name the first: the second is on the card with
    # nothing under it, which the card says in words.
    assert [m["objective"] for m in card["met_when"]] == [SIDES, BRACKETS]
    assert card["met_when"][1] == {"objective": BRACKETS, "lines": [], "steps": []}
    assert card["missing"] == []
    approved = await press(client, classroom, "approve", lesson_id=card["lesson_id"])
    assert approved.status_code == 200
    assert last_card(approved)["status"] == ContractStatus.ACTIVE.value


async def test_a_card_with_no_objectives_named_on_its_steps_is_as_it_was(app, client, classroom):
    scripted(app, _reply())

    card = last_card(await say(client, classroom, "A lesson on linear equations."))

    # No step names an objective, so nothing is said under any: not "No step serves this yet"
    # under each one of a lesson made before a step could name one.
    assert card["objectives"] == [SIDES]
    assert card["met_when"] == []
    assert [s["objective"] for s in card["steps"]] == [None] * 3
