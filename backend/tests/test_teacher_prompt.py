"""The teacher agent's prompt: each matter in one place, in one order."""

from app.agent import activities
from app.agent.brief import LessonBrief, Step
from app.agent.thread import PROMPT_VERSION, SYSTEM

# The order the sections come in. A section the agent reads first frames the ones after it:
# what a lesson is and how it is built come before how to talk about it.
ORDER = [
    "Who you are",
    "Reading what the teacher wants",
    "What you may fill in and what you must ask",
    "Building the lesson",
    "The brief and the rules",
    "How to talk",
    "What goes on the card",
    "Running a lesson",
    "What reaches you about students",
    "Looking at the class, and after it",
]


def headings(prompt: str) -> list[str]:
    """The section headings, in the order they come: a short line with no full stop that
    opens the prompt or follows a blank line."""
    lines = prompt.split("\n")
    return [
        line
        for i, line in enumerate(lines)
        if line and (i == 0 or not lines[i - 1]) and len(line) < 60 and not line.endswith(".")
    ]


def test_the_sections_come_in_one_order():
    assert headings(SYSTEM) == ORDER


def test_the_version_names_this_wording():
    assert PROMPT_VERSION.startswith("teacher-v21-")


def said() -> str:
    return " ".join(SYSTEM.split())


def test_the_prompt_carries_every_heading_and_kind_from_the_one_list():
    for heading in activities.PICKS:
        assert heading.label in SYSTEM and heading.shape in said()
        for kind in heading.kinds:
            assert kind.name in SYSTEM


def test_each_rule_on_what_is_worked_out_and_what_is_asked_is_said_once():
    text = said()
    for rule in (
        "never turn a year group or a grade into an age",
        "Never guessed or filled in, not even in a sketch",
        "never a list to pick from",
        "A title of their own is kept word for word",
        "never changed and never dropped",
        "the defaults stand",
        "Never ask a question they have answered or their material answers",
    ):
        assert text.count(rule) == 1, rule
    # The copies that were scattered across three sections are gone.
    assert "Two things every lesson carries" not in text
    assert "never a question they have answered" not in text


def test_a_lesson_is_built_by_how_much_the_teacher_gave():
    text = said()
    assert 'The whole lesson ("whole"): exactly that, every step and question unchanged' in text
    assert 'Part of a lesson ("part"): every word they gave is kept' in text


def test_the_reply_has_room_for_the_title_and_the_guess():
    text = said()
    assert "I've called it 'Solving linear equations'. Change it if you like." in text
    assert "A lesson that needs nothing more gets the title, the guess and no other ask." in text
    assert "a short clause reading the rules back" in text
    assert "read the rules back in one plain sentence" not in text


def test_no_field_note_says_what_the_prose_no_longer_says():
    notes = {n: f.description or "" for n, f in LessonBrief.model_fields.items()}
    assert "Never ask the teacher" not in notes["activity"]
    assert "filled in when their material makes it obvious" not in notes["subject"]
    # Which heading wins when the box and the words differ is said once, in the prose.
    assert "the one their words describe" not in notes["heading"]
    assert "open-ended writing" not in (Step.model_fields["activity"].description or "")
