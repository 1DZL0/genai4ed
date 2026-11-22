"""The teacher agent's prompt: modules, each one matter, each there because replies failed
without it on the live test set."""

import re

from app.agent import activities
from app.agent.brief import LessonBrief, Step
from app.agent.teacher_prompt import MODULES, TRACES
from app.agent.thread import PROMPT_VERSION, SYSTEM, WORD_ACTIONS, TeacherTurnOut
from bench.teacher_cases import CASES, EVERY

# The modules by name, each with the heading it opens on, in the order they come. The schema
# points at "How to talk" by name, so that heading is not free to change.
ORDER = {
    "who": "Who you are",
    "activity": "The activity",
    "talk": "How to talk",
    "buttons": "Starting and ending",
    "class": "The class",
}


def test_the_prompt_is_its_modules_in_one_order():
    assert {name: text.split("\n", 1)[0] for name, text in MODULES.items()} == ORDER
    assert list(MODULES) == list(ORDER)
    assert SYSTEM == "\n".join(MODULES.values())
    assert "How to talk" in TeacherTurnOut.model_fields["reply"].description


def test_the_version_names_this_wording():
    assert PROMPT_VERSION.startswith("teacher-v27-")


def said() -> str:
    return " ".join(SYSTEM.split())


def test_the_prompt_carries_every_heading_and_kind_from_the_one_list():
    for heading in activities.PICKS:
        assert heading.label in SYSTEM and f'("{heading.key}")' in SYSTEM
        for kind in heading.kinds:
            assert kind.name in SYSTEM
    # What a lesson of each kind looks like was cut: no reply on the live set needed it.
    assert "Such a lesson" not in SYSTEM


def test_every_module_answers_a_failure_seen_on_the_live_set():
    """A module is in the prompt because replies failed a rule without it (bench/RESULTS.md).
    "Who you are" is the one every run had, so nothing was seen to fail without it."""
    assert set(TRACES) == set(MODULES) - {"who"}
    checked = {c.rule for case in CASES for c in case.checks} | {c.rule for c in EVERY}
    for module, rules in TRACES.items():
        assert rules, module
        assert set(rules) <= checked, module


def test_the_prompt_says_what_to_do_and_shows_it():
    """Worked examples and plain instructions, not a list of things never to do."""
    assert len(re.findall(r"\bnever\b", SYSTEM, re.IGNORECASE)) <= 1
    for name in ("talk", "buttons", "class"):
        assert 'Teacher: "' in MODULES[name] and 'Your reply: "' in MODULES[name], name
    # A guard against creep, not a target: raised from 7,000 on 22 Nov 2026 for the plain-words,
    # stated-difficulty and colleague-voice changes (bench cases draft-in-plain-words,
    # difficulty-is-the-goal, the "human" rule).
    assert len(SYSTEM) < 8500


def test_each_rule_on_what_is_worked_out_and_what_is_asked_is_said_once():
    text = said()
    for rule in (
        "What age are your Year 8 students?",
        "Ask only for what is missing",
        "Everything else you fill in and mark to check",
        "the help rules stay at their defaults unless the teacher stated their own",
        "Everyone else is a count with no name",
        "point to the button in one line",
        "under 600 characters",
    ):
        assert text.count(rule) == 1, rule
    # The long list of things never to do is gone with the sections that held it.
    assert "never turn a year group or a grade into an age" not in text
    assert "Never ask a question they have answered" not in text
    # "Age and length" came out: with only that module left out, all 20 cases on the length
    # and the age passed twice, on the Year 8 example in "How to talk" alone.
    assert "A year group or a grade is a different age in different countries" not in text


def test_a_lesson_is_built_by_how_much_the_teacher_gave():
    """Which of topic, part and whole it is rides on the reply itself: no reply on the live
    set lost a teacher's own words with only the field's note to go on. Two questions and
    "build the rest around them" was called whole until the note said what is left to build."""
    note = TeacherTurnOut.model_fields["gave"].description
    assert "part (some of what the students will do, with the rest left for you to build)" in note
    assert "whole (every step or question of the lesson, with nothing left to add)" in note


def test_the_reply_has_room_for_the_title_and_the_guess():
    text = said()
    assert "what you did, with the title; your guess at the kind in one sentence" in text
    # A drafted lesson needs nothing more: every teacher is asked first, so the reply that
    # drafts it has the objective, the age and the length already.
    assert (
        "That reply ends with what they can do next, which is to say approve or ask for a change"
        in text
    )
    assert "'A storm at sea' is on the card. I'm guessing" in text
    # Reading every rule back made seven replies on the live set too long to read.
    assert "reading the rules back" not in text


def test_no_field_note_says_what_the_prose_no_longer_says():
    notes = {n: f.description or "" for n, f in LessonBrief.model_fields.items()}
    assert "Never ask the teacher" not in notes["activity"]
    assert "filled in when their material makes it obvious" not in notes["subject"]
    # Which heading wins when the box and the words differ is said once, in the prose.
    assert "the one their words describe" not in notes["heading"]
    assert "open-ended writing" not in (Step.model_fields["activity"].description or "")
    # A note that points at a section has to point at one that is there.
    assert "Building the lesson" not in notes["activity"]
    assert "as the goal says" not in (Step.model_fields["success_criteria"].description or "")


def test_the_reply_offers_only_the_actions_words_can_ask_for():
    """Starting and ending are buttons. Offered "run" and "end" in the field's own note, the
    model put them in "do" when a teacher asked in words (seen on the live set)."""
    note = TeacherTurnOut.model_fields["do"].description
    assert all(action in note for action in WORD_ACTIONS)
    assert not re.search(r"\b(run|end)\b", note)
    assert "buttons" in note
    assert "run" not in TeacherTurnOut.model_fields["class_ref"].description
