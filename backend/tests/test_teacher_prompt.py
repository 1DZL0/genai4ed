"""The teacher agent's prompt: each matter in one place, in one order."""

from app.agent.thread import PROMPT_VERSION, SYSTEM

# The order the sections come in. A section the agent reads first frames the ones after it:
# what a lesson is and how it is built come before how to talk about it.
ORDER = [
    "Who you are",
    "Designing a lesson together",
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
    assert PROMPT_VERSION.startswith("teacher-v15-")
