"""The list of activities: the headings a teacher picks from and the kinds under each.

One file on the server holds it. The screen, the prompts and the researchers' coding guide
read from that file, so the list is the same everywhere.
"""

from app.agent import activities
from app.enums import ActivityKind

LABELS = [
    "Writing tasks",
    "Mathematics tasks",
    "Open-ended question answering",
    "Multiple-choice / Cloze tasks",
    "Reading comprehension",
    "Critical thinking and evaluation",
    "Scientific inquiry / Investigation",
]


def test_the_seven_headings_come_in_the_lists_order():
    assert [h.label for h in activities.HEADINGS] == LABELS


def test_a_teacher_can_also_pick_something_else():
    assert [h.label for h in activities.PICKS] == [*LABELS, "Something else"]
    # Nothing is listed under it: the agent names such a kind in its own words.
    assert activities.OTHER.kinds == ()


def test_every_kind_says_whether_it_has_right_answers_or_is_judged_against_criteria():
    for heading in activities.HEADINGS:
        assert heading.kinds, heading.label
        for kind in heading.kinds:
            assert kind.name.strip(), heading.label
            assert isinstance(kind.shape, ActivityKind), kind.name


def test_the_shape_follows_the_kind_not_the_heading():
    maths = activities.heading("maths")
    shapes = {k.name: k.shape for k in maths.kinds}
    assert shapes["multi-step problems"] is ActivityKind.ANSWERS
    assert shapes["mathematical modelling"] is ActivityKind.OPEN
    assert {k.shape for k in activities.heading("writing").kinds} == {ActivityKind.OPEN}
    assert {k.shape for k in activities.heading("choice").kinds} == {ActivityKind.ANSWERS}


def test_no_two_kinds_share_a_name_and_no_two_headings_a_key():
    names = [k.name.lower() for h in activities.HEADINGS for k in h.kinds]
    assert len(names) == len(set(names))
    keys = [h.key for h in activities.PICKS]
    assert len(keys) == len(set(keys))


def test_each_heading_says_what_such_a_lesson_looks_like_and_how_to_teach_it():
    for heading in activities.HEADINGS:
        for line in (heading.shape, heading.teaching):
            assert line.strip(), heading.label
            assert "\n" not in line, heading.label


def test_a_heading_is_found_by_its_key_and_an_unknown_key_finds_none():
    assert activities.heading("reading").label == "Reading comprehension"
    assert activities.heading("other") is activities.OTHER
    assert activities.heading("essays") is None
    assert activities.heading("") is None


def test_a_kind_is_found_by_its_name_however_it_is_capitalised():
    found = activities.find_kind("  Multi-step Problems ")
    assert found is not None
    heading, kind = found
    assert (heading.key, kind.name) == ("maths", "multi-step problems")
    assert activities.find_kind("a debate in pairs") is None
    assert activities.find_kind("") is None


def test_the_screen_is_sent_the_picks_and_no_kinds():
    assert activities.for_screen() == [{"key": h.key, "label": h.label} for h in activities.PICKS]


def test_a_kind_added_to_a_heading_is_on_the_list_with_no_other_change():
    """Adding a kind is one line in the file: nothing else names the kinds one by one."""
    from dataclasses import replace

    extra = activities.Kind("proof writing", ActivityKind.OPEN)
    maths = activities.heading("maths")
    wider = replace(maths, kinds=(*maths.kinds, extra))
    assert activities.find_kind("Proof writing", [wider]) == (wider, extra)
    assert activities.find_kind("Proof writing") is None
