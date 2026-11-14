"""The teacher test set is sound as data: enough cases, each one runnable, each check about a
named rule. The replies come from a real model, so they are run by hand (bench.teacher_set),
never here."""

from collections import Counter

from app.agent import activities
from app.agent.brief import LessonBrief
from bench.teacher_cases import CASES, EVERY, RULES, STATES

GROUPS = {"new", "pressed", "focus", "class"}


def test_the_set_is_thirty_to_fifty_messages_each_with_its_own_name():
    assert 30 <= len(CASES) <= 50
    assert not [name for name, n in Counter(c.id for c in CASES).items() if n > 1]
    assert not [text for text, n in Counter((c.state, c.text) for c in CASES).items() if n > 1]


def test_every_message_is_sent_in_a_state_the_set_knows_and_checked_for_something():
    for c in CASES:
        assert c.group in GROUPS, c.id
        assert c.state in STATES, c.id
        # A press with no words is a message too.
        assert (c.text.strip() or c.picks) and c.checks, c.id
        assert set(c.picks) <= {h.key for h in activities.PICKS}, c.id


def test_every_rule_is_checked_by_some_message():
    """A rule nothing checks cannot fail, so it would say nothing about the prompt."""
    checked = {c.rule for case in CASES for c in case.checks} | {c.rule for c in EVERY}
    assert checked == set(RULES)


def test_the_lessons_a_state_starts_with_are_ones_the_app_would_keep():
    for name, state in STATES.items():
        for lesson in state.lessons:
            assert LessonBrief.model_validate(lesson.brief).steps, name
        assert len(state.pupils) <= 5, name
