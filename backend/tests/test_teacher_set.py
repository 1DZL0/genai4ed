"""The teacher test set is sound as data: enough cases, each one runnable, each check about a
named rule. The replies come from a real model, so they are run by hand (bench.teacher_set),
never here. What runs them is tried here with a scripted model in the real one's place."""

from collections import Counter
from copy import deepcopy

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent import llm, thread
from app.agent.brief import LessonBrief
from app.main import create_app
from bench import teacher_run, teacher_set
from bench.teacher_cases import (
    CASES,
    EQUATIONS,
    EVERY,
    RULES,
    SERVING,
    STATES,
    Case,
    Got,
    at_most_two,
    no_box_words,
    serves,
)
from tests.test_activity_in_the_lesson import _drafted

GROUPS = {"new", "focus", "class"}
ASKING = {"reply": "What should they be able to do by the end?", "show": "nothing"}


def _named(name: str) -> Case:
    return next(c for c in CASES if c.id == name)


# ---------- the cases, as data ----------


def test_the_set_is_forty_to_sixty_messages_each_with_its_own_name():
    assert 40 <= len(CASES) <= 60
    assert not [name for name, n in Counter(c.id for c in CASES).items() if n > 1]
    assert not [text for text, n in Counter((c.state, c.text) for c in CASES).items() if n > 1]


def test_every_message_is_words_sent_in_a_state_the_set_knows_and_checked_for_something():
    for c in CASES:
        assert c.group in GROUPS, c.id
        assert c.state in STATES, c.id
        # There are no headings to press: every message is the teacher's words.
        assert c.text.strip() and c.checks, c.id
        assert not hasattr(c, "picks"), c.id
        # The one button a case can press takes its words as the difficulty to follow up.
        assert c.press in {"", "follow_up"}, c.id


def test_every_rule_is_checked_by_some_message():
    """A rule nothing checks cannot fail, so it would say nothing about the prompt."""
    checked = {c.rule for case in CASES for c in case.checks}
    checked |= {c.rule for c in EVERY}
    assert checked == set(RULES)


def test_no_rule_or_state_is_about_a_switch_or_a_press():
    for gone in ("topic-asks", "sketch", "extras", "deeper-not-bigger", "easier-is-a-part"):
        assert gone not in RULES, gone
    assert not [name for name, state in STATES.items() if hasattr(state, "switches")]
    # No earlier message in a state says what was pressed or offers headings.
    for name, state in STATES.items():
        for said in state.thread:
            assert "activity" not in said.data, name
            assert "The activity I picked" not in said.text, name


def test_every_reply_is_checked_for_pointing_at_a_box_or_a_heading():
    assert "no-box-words" in {c.rule for c in EVERY}


def test_the_lessons_a_state_starts_with_are_ones_the_app_would_keep():
    for name, state in STATES.items():
        for lesson in state.lessons:
            assert LessonBrief.model_validate(lesson.brief).steps, name
        assert len(state.pupils) <= 5, name


# ---------- what a reply has to pass ----------


def _seen(reply: str, out: dict | None = None, **more) -> dict:
    """What the runner collects from one reply, with nothing saved and nothing struck."""
    return {
        "out": out or {"reply": reply, "show": "nothing"},
        "tries": 1,
        "reply": reply,
        "data": {},
        "conflicts": [],
        "before": None,
        "after": None,
        "made": [],
        "session": "",
        "names": {},
    } | more


def _got(reply: str) -> Got:
    return Got(**_seen(reply))


def test_a_topic_alone_is_asked_about_and_not_drafted():
    topic = _named("topic-only")
    assert teacher_run.judge(topic, _seen(ASKING["reply"])) == []
    # Asking for the kind of activity is the old wording's question, and fails now.
    kind = "What kind of activity should it be?"
    failed = teacher_run.judge(topic, _seen(kind, {"reply": kind, "gave": "topic"}))
    assert {f["rule"] for f in failed} == {"ask-first"}


def test_a_message_that_says_what_they_will_do_may_be_drafted_or_asked_about():
    essay = _named("essay-full")

    assert teacher_run.judge(essay, _seen(ASKING["reply"])) == []
    neither = teacher_run.judge(essay, _seen("Tell me a bit more."))
    assert {f["rule"] for f in neither} == {"ask-first"}
    # Drafted, it is held to what its draft is held to.
    wrong_kind = [{"title": "Zoos", "brief": {"heading": "maths", "steps": []}}]
    drafted = teacher_run.judge(essay, _seen("Drafted it.", made=wrong_kind))
    assert "kind" in {f["rule"] for f in drafted}
    assert "ask-first" not in {f["rule"] for f in drafted}


def test_a_lesson_drafted_in_the_reply_is_held_to_what_its_steps_serve():
    for name in ("essay-full", "rename", "ask-all-three"):
        rules = [k.rule for k in _named(name).checks]
        assert rules.count("serves") == 1, name
    # Only when a lesson was drafted: a reply that asks is not held to it.
    essay = _named("essay-full")
    assert "serves" not in {f["rule"] for f in teacher_run.judge(essay, _seen(ASKING["reply"]))}
    unserved = _drafted_with(WARM_UP, TWO_STEPS | {"objective": None})
    seen = _seen("Drafted it.", unserved.out, made=unserved.made)
    assert "serves" in {f["rule"] for f in teacher_run.judge(essay, seen)}


def test_two_numbered_questions_are_two_questions():
    two = (
        "Before I draft, two things.\n"
        "1. What should they be able to do by the end? For example: name the stages, or "
        "explain evaporation. Pick one, change it or write your own.\n"
        "2. What age are they?"
    )
    assert at_most_two().test(_got(two)) == ""


def test_the_age_and_the_length_asked_together_are_one_question():
    """What the model does with all three missing (run v26-switched): the objective, then the
    two facts about the class in one line, which a teacher answers in a breath."""
    together = (
        "Before I draft, two things.\n"
        "1. What should they be able to do by the end? For example: put the planets in order "
        "from the Sun. Pick one, change it or write your own.\n"
        "2. How old are the students, and how long is the lesson?"
    )
    assert at_most_two().test(_got(together)) == ""


def test_three_questions_are_too_many_however_they_are_set_out():
    three = "What should they be able to do by the end? How old are they? How long is it?"
    assert "3 questions" in at_most_two().test(_got(three))
    numbered = (
        "1. What should they be able to do by the end?\n"
        "2. How old are they?\n"
        "3. How long is the lesson?"
    )
    assert "3 questions" in at_most_two().test(_got(numbered))
    # The objective is never one question with a fact about the class.
    packed = (
        "What should they be able to do by the end, and what age are they? And how many "
        "minutes do you have?"
    )
    assert "3 questions" in at_most_two().test(_got(packed))


def test_a_reply_that_points_at_the_activity_box_or_a_heading_is_caught():
    for pointing in (
        "What kind of activity is it? Press a heading below.",
        "Pick one in the activity box.",
        "Choose one of the headings under my reply.",
    ):
        assert no_box_words().test(_got(pointing)), pointing
    in_words = "Help is on the defaults. Tell me if you want it changed."
    assert no_box_words().test(_got(in_words)) == ""
    # The Tutor line is still under the typing box, so pointing at it is fine.
    tutor = "Help is on the defaults; the tutor settings under the box change it."
    assert no_box_words().test(_got(tutor)) == ""


# ---------- the lesson card: what a step serves ----------

TWO_STEPS = {
    "name": "Two steps",
    "goal": "Solve 3x + 5 = 20",
    "prompt_ideas": ["Solve 3x + 5 = 20"],
    "success_criteria": ["x = 5"],
    "reference_answer": "5",
    "objective": 1,
}
WARM_UP = {
    "name": "Warm up",
    "goal": "Take one number from another",
    "prompt_ideas": ["What is 20 - 5?"],
    "success_criteria": ["15"],
    "reference_answer": "15",
    "objective": None,
}


def _drafted_with(*steps: dict, objectives=("Solve two-step equations",), saved=None) -> Got:
    """A reply that drafted a lesson with these steps; `saved` when the server kept other
    steps than the model wrote."""
    wrote = {"objectives": list(objectives), "steps": [dict(s) for s in steps]}
    kept = wrote if saved is None else wrote | {"steps": [dict(s) for s in saved]}
    lesson = {"title": "Equations", "status": "draft", "version": 1, "brief": kept}
    return Got(**_seen("Drafted it.", {"reply": "Drafted it.", "brief": wrote}, made=[lesson]))


def test_every_objective_has_a_step_and_a_warm_up_may_serve_none():
    assert serves().test(_drafted_with(WARM_UP, TWO_STEPS)) == ""
    two = ("Solve two-step equations", "Check a solution by putting it back in")
    assert "objective 2" in serves().test(_drafted_with(WARM_UP, TWO_STEPS, objectives=two))
    nothing_named = serves().test(_drafted_with(WARM_UP, TWO_STEPS | {"objective": None}))
    assert "objective 1" in nothing_named


def test_an_objective_that_is_not_on_the_list_is_read_in_the_models_own_reply():
    """The server clears such a number before it saves, so the saved lesson never shows it."""
    off = TWO_STEPS | {"objective": 3}
    cleared = TWO_STEPS | {"objective": None}
    got = _drafted_with(TWO_STEPS, off, saved=[TWO_STEPS, cleared])
    assert "step 2" in serves().test(got)


def test_the_card_rules_are_serving_and_nothing_more():
    assert [item.rule for item in SERVING] == ["serves"]


# ---------- which cases a run takes ----------


def test_a_run_with_nothing_asked_for_is_the_whole_set():
    assert teacher_set.chosen("") == CASES


def test_a_run_can_take_a_group_a_case_a_state_or_a_rule():
    assert [c.id for c in teacher_set.chosen("ask-topic,rename")] == ["rename", "ask-topic"]
    assert {c.group for c in teacher_set.chosen("class")} == {"class"}
    assert {c.state for c in teacher_set.chosen("offered")} == {"offered"}
    offered = {c.id for c in teacher_set.chosen("offer-objectives")}
    assert offered == {"ask-topic", "ask-document", "ask-you-decide"}
    with pytest.raises(SystemExit, match="No case matches"):
        teacher_set.chosen("pressed-topic")


# ---------- the runner, with a scripted model where the real one goes ----------


def test_the_turn_block_is_what_follows_the_fixed_prompt():
    added = "\n\nReply with a single JSON object, and then this turn's block."
    assert teacher_run.turn_block(thread.SYSTEM + added) == added
    assert teacher_run.turn_block("a prompt from a file") == "a prompt from a file"


async def _run_once(case: Case, model: llm.ScriptedClient, n: int) -> dict:
    """One case through the bench's own runner. The app uses its own sessions, as it does in
    a real run; the numbers start at 901 so no teacher here is one a fixture made."""
    app = create_app()
    app.dependency_overrides[llm.get_llm_client] = lambda: teacher_run.Routed(model)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        return await teacher_run._once(http, case, n)


async def test_a_case_is_run_on_the_one_wording_and_judged_by_its_own_checks(db):
    topic = _named("topic-only")

    row = await _run_once(topic, llm.ScriptedClient([ASKING]), n=901)

    assert row["prompt_version"] == thread.PROMPT_VERSION
    assert row["turn_block"].startswith("\n\nReply with a single JSON object")
    assert (row["tries"], row["made"]) == (1, [])
    assert "switches" not in row
    assert teacher_run.judge(topic, row) == []


async def test_a_case_in_a_state_with_an_offer_drafts_from_the_teachers_pick(db):
    agreed = _drafted(age=11, duration_minutes=30)
    row = await _run_once(_named("ask-offer-agreed"), llm.ScriptedClient([agreed]), n=902)

    assert (row["tries"], len(row["made"])) == (1, 1)
    assert row["sent"] == "The second one"


async def test_a_case_can_press_the_follow_up_button_in_place_of_a_message(db):
    button = Case(
        "pressed-follow-up",
        "class",
        "running_shared",
        "subtracting the denominators",
        (),
        press="follow_up",
    )
    guessed = _drafted(age=None, duration_minutes=None, to_check=["objectives"])

    row = await _run_once(button, llm.ScriptedClient([guessed]), n=904)

    assert (row["tries"], len(row["made"])) == (1, 1)
    assert "follow up a shared difficulty" in row["turn_block"]
    assert row["sent"] == "subtracting the denominators"


def test_the_report_says_which_wording_a_reply_was_given_under():
    row = _seen(ASKING["reply"]) | {
        "id": "ask-topic",
        "group": "new",
        "state": "empty",
        "press": "",
        "status": "pass",
        "failed": [],
        "sent": "A lesson on volcanoes please",
        "latency_ms": 1200,
        "prompt_version": "teacher-v27-1b61f4a4",
    }

    report = teacher_run.as_text([row])

    assert "prompt teacher-v27-1b61f4a4" in report
    assert "switches" not in report
    # A run saved while there were switches and headings to press still reads.
    before = row | {"switches": {"ask_first": True}, "picks": ["maths"]}
    assert "teacher-v27-1b61f4a4" in teacher_run.as_text([before])


def test_the_report_shows_what_each_step_serves():
    steps = [dict(s) for s in EQUATIONS["steps"]]
    steps[1]["objective"] = 1
    steps[2] |= {"objective": 1, "easier": {"question": "An old extra", "answer": None}}
    lesson = {
        "title": "Linear equations",
        "status": "draft",
        "version": 1,
        "brief": EQUATIONS | {"steps": steps},
    }
    row = _seen("Drafted it.", made=[lesson]) | {
        "id": "ask-all-three",
        "group": "new",
        "state": "empty",
        "press": "",
        "status": "pass",
        "failed": [],
        "sent": "Solving equations, age 13, 30 minutes",
        "latency_ms": 1200,
    }

    report = teacher_run.as_text([row])

    assert f"objective 1: {EQUATIONS['objectives'][0]}" in report
    assert "step 3 'Brackets' serves objective 1:" in report
    # An extra a step held in a run saved before they were taken off is not reported.
    assert "An old extra" not in report
    # A lesson where no step names an objective is reported as it always was.
    plain = deepcopy(lesson)
    for step in plain["brief"]["steps"]:
        step["objective"] = None
    assert "serves" not in teacher_run.as_text([row | {"made": [plain]}])
