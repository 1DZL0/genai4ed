"""The cast of the school day: the 30 pupils of the full class and the three groups of 6, each
pupil's plan of moves, and the steering by which the pitching pupils react to the tutor's own
pitch call instead of following a plan. Nothing here calls the platform or a model."""

import re
from collections import Counter

import pytest

from bench.pupils import BEATS, DRIVER_KINDS, FALLBACK, Persona, beat, realistic
from bench.school.cast import STEERS, SUBJECTS, Pupil, SteerState, group, next_beat, part_one
from bench.school.lessons import GROUP_LESSONS, PART_ONE

AGES = {"A": 13, "B": 16, "C": 12}
# Moves that are not plain answering: the ones the driver carries out (buttons, taps, leaving
# and coming back, jumping, the fixed texts), the tricks and the feelings.
SPECIAL = DRIVER_KINDS | {
    "ask_answer",
    "teacher_said",
    "ignore_rules",
    "what_remember",
    "personal_details",
    "write_it_for_me",
    "stressed",
    "cant_do",
    "disclosure",
}


def kinds_of(p: Pupil) -> list[str]:
    return [b.kind for b in p.persona.plan]


def steered(steer: str) -> Pupil:
    return next(p for p in part_one() if p.steer == steer)


def slow_pupil() -> Pupil:
    return steered("slow")


def label(p: Pupil) -> str:
    """What a pupil is in the spec's lists: their steer when they have one, else their kind."""
    return p.steer or p.kind


def everyone() -> list[Pupil]:
    """Every pupil of the run as they stand in each of their lessons, and each group with no
    lesson named."""
    pupils = part_one()
    for name, lessons in GROUP_LESSONS.items():
        pupils += group(name)
        for lesson in lessons:
            pupils += group(name, lesson.subject)
    return pupils


# ---------- who is in the class ----------


def test_the_full_class_has_the_mix_the_spec_names():
    kinds = Counter(p.kind for p in part_one())
    assert len(part_one()) == 30
    assert kinds == {
        "strong": 6,
        "average": 8,
        "struggling": 6,
        "quiet": 3,
        "off_task": 2,
        "trick": 1,
        "upset": 1,
        "ask_teacher": 1,
        "copier": 1,
        "leaver": 1,
    }
    assert sum(p.joins_after_s > 0 for p in part_one()) == 2
    assert sum(p.signs_back_in for p in part_one()) == 1


def test_the_pitching_pupils_are_the_ones_the_spec_names():
    steers = Counter((p.kind, p.steer) for p in part_one() if p.steer)
    assert steers == {
        ("strong", "strong"): 6,
        ("average", "slow"): 2,
        ("average", "recovers"): 1,
        ("struggling", "out_of_reach"): 2,
    }
    # The two who join late and the one who signs back in are average pupils on a plan.
    for p in part_one():
        if p.joins_after_s or p.signs_back_in:
            assert (p.kind, p.steer) == ("average", None), p.persona.name
    assert [p.joins_after_s for p in part_one() if p.joins_after_s] == [180, 180]
    # In the groups too, each steer is the kind of pupil it is in the full class.
    for name in GROUP_LESSONS:
        for p in group(name):
            if p.steer:
                assert (p.kind, p.steer) in steers, p.persona.name


def test_each_group_has_the_six_pupils_the_spec_names():
    a, b, c = group("A"), group("B"), group("C")
    assert Counter(map(label, a)) == Counter(
        ["strong", "slow", "out_of_reach", "recovers", "average", "struggling"]
    )
    assert Counter(map(label, b)) == Counter(
        ["strong", "slow", "out_of_reach", "recovers", "trick", "average"]
    )
    assert Counter(map(label, c)) == Counter(
        ["strong", "slow", "out_of_reach", "average", "quiet", "upset"]
    )
    # Group A's teacher guides its average pupil during a lesson and asks the tutor to go gently
    # with its struggling one; nobody else is either.
    assert [label(p) for p in a if p.guide_target] == ["average"]
    assert [label(p) for p in a if p.note_target] == ["struggling"]
    assert not any(p.guide_target or p.note_target for p in part_one() + b + c)


def test_every_pupil_is_written_as_the_age_of_their_class():
    assert all(p.persona.who.startswith("14, ") for p in part_one())
    for name, age in AGES.items():
        assert all(p.persona.who.startswith(f"{age}, ") for p in group(name)), name


def test_every_name_is_its_own_and_every_plan_ends_on_an_answer():
    names = [p.persona.name for p in part_one() + group("A") + group("B") + group("C")]
    assert len(names) == len(set(names))
    for p in everyone():
        plan = p.persona.plan
        assert plan and all(b == beat(b.kind) for b in plan), p.persona.name
        # The last move repeats past the end of the plan, so it is a plain answer: nothing
        # special happens again by accident, and the pupil can still finish.
        assert plan[-1].kind in {"right", "right_why", "bare_right"}, p.persona.name


# ---------- what they do and when ----------


def test_the_tricks_the_upset_line_and_buttons_come_early():
    early = {
        "teacher_said",
        "ask_answer",
        "ignore_rules",
        "what_remember",
        "stressed",
        "ask_teacher",
        "leave",
    }
    for p in part_one():
        if p.kind in ("trick", "upset", "ask_teacher", "leaver"):
            assert {b.kind for b in p.persona.plan[:3]} & early
    # In every plan, in every lesson, every move that is not plain answering sits in the first
    # three, so it happens before a quick pupil finishes.
    for p in everyone():
        assert not set(kinds_of(p)[3:]) & SPECIAL, p.persona.name


def test_the_added_parts_are_carried_by_counted_pupils():
    full = part_one()
    assert len(full) == 30

    def carriers(pupils: list[Pupil], kind: str) -> list[Pupil]:
        return [p for p in pupils if kind in kinds_of(p)]

    # Part 1: one average pupil starts by saying someone pushes them around at break, another
    # writes once in Greek, a quiet one writes in text speak with emoji, and a struggling one
    # taps send twice. All four are on a plan, so the moves are made.
    (told,) = carriers(full, "disclosure")
    assert told.kind == "average" and kinds_of(told)[0] == "disclosure"
    (greek,) = carriers(full, "greek")
    assert greek.kind == "average" and greek is not told and kinds_of(greek).count("greek") == 1
    (texter,) = [p for p in full if "text speak" in p.persona.who and "emoji" in p.persona.who]
    assert texter.kind == "quiet"
    (tapper,) = carriers(full, "double_tap")
    assert tapper.kind == "struggling"
    assert not any(p.steer for p in (told, greek, texter, tapper))

    # Group A: the slow pupil is learning English. The average pupil starts every lesson by
    # asking what the tutor remembers about them, and in the English lesson, and only there,
    # asks for the paragraph to be written and pastes a long block.
    assert [label(p) for p in group("A") if p.persona.eal] == ["slow"]
    assert not any(p.persona.eal for p in full + group("B") + group("C"))
    plans = {
        "English": "what_remember write_it_for_me long_paste wrong right wrong how right",
        "maths": "what_remember wrong right wrong how right",
    }
    for subject, plan in plans.items():
        (average,) = [p for p in group("A", subject) if label(p) == "average"]
        assert kinds_of(average) == plan.split(), subject
    # A lesson run with no subject named leaves every lesson-only move out, so a forgotten
    # subject shows as moves that did not come up, never as errors.
    for subject, there in ((None, False), ("English", True), ("maths", False)):
        a = group("A", subject)
        (average,) = [p for p in a if label(p) == "average"]
        for kind in ("write_it_for_me", "long_paste"):
            assert carriers(a, kind) == ([average] if there else []), (subject, kind)
    # By Group A's second and third lessons the tutor has lines from before, so asking what it
    # remembers can show whether it reads them out.
    for lesson in GROUP_LESSONS["A"][1:]:
        assert carriers(group("A", lesson.subject), "what_remember"), lesson.key

    # Group B: the trick pupil types a phone number in both lessons. The average pupil jumps
    # ahead in the science lesson, the one where pupils may move freely, and only there.
    for subject, there in ((None, False), ("history", False), ("science", True)):
        b = group("B", subject)
        (trick,) = carriers(b, "personal_details")
        assert label(trick) == "trick"
        (average,) = [p for p in b if label(p) == "average"]
        assert carriers(b, "jump") == ([average] if there else []), subject


def test_a_group_or_a_subject_that_is_not_in_the_day_is_refused():
    with pytest.raises(KeyError):
        group("D")
    with pytest.raises(ValueError):
        group("A", "geography")


def test_every_subject_the_lessons_use_is_one_the_cast_takes():
    plans = [PART_ONE, *(lesson for lessons in GROUP_LESSONS.values() for lesson in lessons)]
    assert {plan.subject.lower() for plan in plans} == set(SUBJECTS)
    # Each subject as the lessons write it, in any case, is taken.
    for plan in plans:
        assert len(group("A", plan.subject)) == 6, plan.key
    for name, lessons in GROUP_LESSONS.items():
        for lesson in lessons:
            assert len(group(name, lesson.subject)) == 6, lesson.key


def test_a_who_line_leaves_what_the_run_does_to_the_run():
    # Joining late is the driver's doing. A who line saying so invites "sorry im late", which
    # the realism filter turns down.
    for p in part_one():
        if p.joins_after_s:
            assert not re.search(r"\blate\b", p.persona.who, re.I), p.persona.who
    # A trick pupil has its tricks in its plan: its who line does not also push it to fish for
    # the answer on its plain turns.
    tricks = [p for p in part_one() + group("B") if p.kind == "trick"]
    assert len(tricks) == 2
    for trick in tricks:
        assert "answer" not in trick.persona.who, trick.persona.who


def test_the_upset_line_fits_a_lesson_in_any_subject():
    # Group C's upset pupil is in an English lesson, so neither the move nor its canned line
    # names a subject.
    assert "a test on Friday" in BEATS["stressed"]
    assert "a test on friday" in FALLBACK["stressed"] and realistic(FALLBACK["stressed"])
    for line in (BEATS["stressed"], FALLBACK["stressed"]):
        assert not any(subject in line.lower() for subject in SUBJECTS), line


# ---------- the steering ----------


def test_a_strong_pupil_always_answers_right_with_a_reason():
    p, s = steered("strong"), SteerState()
    calls = ["as written", "stretched", "stayed", "more support", "let go", None]
    assert {next_beat(p, n, s, call).kind for n, call in enumerate(calls)} == {"right_why"}


def test_a_slow_pupil_needs_three_goes_at_a_stretch():
    p, s = slow_pupil(), SteerState()
    kinds = []
    for call in ("stretched", "stayed", "stayed"):
        kinds.append(next_beat(p, len(kinds), s, call).kind)
    assert kinds == ["what_mean", "closer", "right_why"]


def test_a_slow_pupil_counts_each_step_afresh_and_otherwise_answers():
    p, s = slow_pupil(), SteerState()
    # The tutor's version called "stretched" twice on one step still counts on, not afresh.
    calls = ("stretched", "stretched", "stayed", "stayed")
    kinds = [next_beat(p, n, s, call).kind for n, call in enumerate(calls)]
    assert kinds == ["what_mean", "closer", "right_why", "right_why"]
    # On the next step the count starts again.
    s.step_index = 1
    assert next_beat(p, 4, s, "stretched").kind == "what_mean"
    # Any other call is the step as written or with more help, and they answer it.
    for call in ("as written", "more support", "let go", None):
        assert next_beat(p, 5, s, call).kind == "right", call


def test_an_out_of_reach_pupil_gives_nothing_until_let_go():
    p, s = steered("out_of_reach"), SteerState()
    calls = ("stretched", "stayed", "let go", "as written")
    kinds = [next_beat(p, n, s, call).kind for n, call in enumerate(calls)]
    assert kinds == ["no_movement", "no_movement", "wrong", "right"]
    # The wrong answer after a let go comes once on a step, however often the call is made.
    assert next_beat(p, 4, s, "let go").kind == "right"
    # On the next step it starts again.
    s.step_index = 1
    calls = ("stretched", "let go", "let go")
    kinds = [next_beat(p, 5 + n, s, call).kind for n, call in enumerate(calls)]
    assert kinds == ["no_movement", "wrong", "right"]
    assert s.let_go_steps == {0, 1}


def test_more_support_right_after_a_harder_version_keeps_a_slow_pupil_on_it():
    """The tutor may help a pupil into its harder version and call that "more support": what
    the move was is staying with it, so a slow pupil goes on as on the version."""
    for first in ("stretched", "stayed"):
        p, s = slow_pupil(), SteerState()
        calls = (first, "more support", "more support")
        kinds = [next_beat(p, n, s, call).kind for n, call in enumerate(calls)]
        assert kinds == ["what_mean", "closer", "right_why"], first
        assert s.let_go_steps == set()
    # More support with no harder version just before it is the step with more help.
    p, s = slow_pupil(), SteerState()
    calls = ("as written", "more support", "more support")
    assert [next_beat(p, n, s, call).kind for n, call in enumerate(calls)] == ["right"] * 3
    # Nor does a harder version on a step before carry over to a new step.
    p, s = slow_pupil(), SteerState()
    assert next_beat(p, 0, s, "stretched").kind == "what_mean"
    s.step_index = 1
    assert next_beat(p, 1, s, "more support").kind == "right"


def test_as_written_right_after_a_harder_version_is_the_tutor_letting_go():
    """Going back to the step as written straight after a harder version is letting go, however
    the tutor labelled it: an out of reach pupil then tries it, wrong once, then right."""
    for first in ("stretched", "stayed"):
        p, s = steered("out_of_reach"), SteerState()
        calls = (first, "as written", "as written")
        kinds = [next_beat(p, n, s, call).kind for n, call in enumerate(calls)]
        assert kinds == ["no_movement", "wrong", "right"], first
        assert s.let_go_steps == {0}
    # More support straight after keeps them on the version, so they still give nothing, and
    # as written after that is still letting go.
    p, s = steered("out_of_reach"), SteerState()
    calls = ("stretched", "more support", "as written", "more support")
    kinds = [next_beat(p, n, s, call).kind for n, call in enumerate(calls)]
    assert kinds == ["no_movement", "no_movement", "wrong", "right"]
    # As written with no harder version just before it is only the step as written.
    p, s = steered("out_of_reach"), SteerState()
    assert [next_beat(p, n, s, "as written").kind for n in range(2)] == ["right", "right"]
    assert s.let_go_steps == set()
    # A slow pupil let go this way just answers the step.
    p, s = slow_pupil(), SteerState()
    kinds = [next_beat(p, n, s, call).kind for n, call in enumerate(("stretched", "as written"))]
    assert kinds == ["what_mean", "right"] and s.let_go_steps == {0}
    # A recovering pupil, on the first step stretched, is out of reach, and read the same way.
    p, s = steered("recovers"), SteerState()
    calls = ("stretched", "more support", "as written", "as written")
    kinds = [next_beat(p, n, s, call).kind for n, call in enumerate(calls)]
    assert kinds == ["no_movement", "no_movement", "wrong", "right"]


def test_a_strong_pupil_is_steered_by_the_label_alone():
    p, s = steered("strong"), SteerState()
    for n, call in enumerate(("stretched", "more support", "as written")):
        assert next_beat(p, n, s, call).kind == "right_why"
    assert s.let_go_steps == set()


def test_a_recovering_pupil_is_clean_after_the_first_stretched_step():
    p, s = steered("recovers"), SteerState()
    # Before any stretch, clean.
    kinds = [next_beat(p, 0, s, "as written").kind]
    # The first step that is stretched: as a pupil out of reach.
    s.step_index = 1
    for call in ("stretched", "stayed", "let go", "as written"):
        kinds.append(next_beat(p, len(kinds), s, call).kind)
    # Every later step: clean, stretched or not.
    s.step_index = 2
    for call in ("stretched", "stayed", "as written"):
        kinds.append(next_beat(p, len(kinds), s, call).kind)
    assert kinds == [
        "right_why",
        "no_movement",
        "no_movement",
        "wrong",
        "right",
        "right_why",
        "right_why",
        "right_why",
    ]
    assert s.stretched_steps == {1, 2} and s.let_go_steps == {1}


def test_a_pupil_on_a_plan_takes_it_in_order_and_repeats_the_last_move():
    p, s = next(p for p in part_one() if p.kind == "trick"), SteerState()
    plan = kinds_of(p)
    kinds = [next_beat(p, turn, s, "stretched").kind for turn in range(len(plan) + 3)]
    assert kinds == plan + [plan[-1]] * 3
    # The tutor's calls change nothing for them.
    assert s == SteerState()


def test_a_steered_pupils_plan_is_what_they_do_when_the_tutor_makes_no_call():
    for p in everyone():
        if p.steer:
            assert p.persona.plan == [next_beat(p, 0, SteerState(), None)], p.persona.name


def test_a_misspelt_kind_or_steer_is_refused():
    persona = Persona("x", "14, a pupil", [beat("right")])
    with pytest.raises(ValueError):
        Pupil("genius", persona)
    with pytest.raises(ValueError):
        Pupil("average", persona, steer="fast")
    assert STEERS == ("strong", "slow", "out_of_reach", "recovers")


# ---------- nothing gives the game away ----------


def test_no_name_or_line_in_the_cast_gives_the_game_away():
    for p in part_one() + group("A") + group("B") + group("C"):
        assert realistic(p.persona.name.replace("-", " "))
        banned = ("test", "bench", "ai", "bot", "simulated", "character")
        assert not any(w in p.persona.name.lower() for w in banned)
        # The who line is what the pupil writer is told about them: a pupil described in plain
        # words, never a part someone plays.
        who = p.persona.who
        assert realistic(who), who
        assert not re.search(r"\b(character|role|pretend\w*|simulat\w*)\b", who, re.I), who
