"""The assistance ladder.

The policy decides what help is *permitted*. It is a pure function of the
contract and the student's own history, so it can be reasoned about without a
database or a model.
"""

import pytest

from app.enums import Rung
from app.tutor.policy import AssistanceLadder, LadderPolicy, PolicyInput

FULL_LADDER = {
    "rungs": [r.value for r in Rung],
    "max_rung": Rung.FULL_SOLUTION.value,
    "allow_full_solution": True,
}
WITHHELD_LADDER = {
    "rungs": [r.value for r in Rung if r is not Rung.FULL_SOLUTION],
    "max_rung": Rung.PARTIAL_STEP.value,
    "allow_full_solution": False,
}

policy = LadderPolicy()


def decide(ladder: dict, incorrect: int, *, correct=False, recurring=None):
    return policy.decide(
        PolicyInput(
            ladder=AssistanceLadder.from_contract(ladder),
            incorrect_attempts=incorrect,
            correct=correct,
            recurring_misconception=recurring,
        )
    )


def test_a_correct_answer_earns_no_assistance():
    assert decide(WITHHELD_LADDER, 0, correct=True).rung is Rung.ATTEMPT


@pytest.mark.parametrize(
    ("incorrect", "expected"),
    [
        (1, Rung.DIAGNOSTIC_QUESTION),
        (2, Rung.CONCEPTUAL_CUE),
        (3, Rung.TARGETED_HINT),
        (4, Rung.ANALOGOUS_EXAMPLE),
        (5, Rung.PARTIAL_STEP),
    ],
)
def test_one_rung_per_incorrect_attempt(incorrect, expected):
    assert decide(WITHHELD_LADDER, incorrect).rung is expected


def test_the_ladder_stops_where_the_teacher_stopped_it():
    """The contract withholds the full solution, so no number of wrong answers
    reaches it. This is the guardrail Bastani et al. found mitigates harm."""
    for incorrect in (6, 7, 20):
        assert decide(WITHHELD_LADDER, incorrect).rung is Rung.PARTIAL_STEP


def test_full_solution_is_reachable_only_when_the_contract_permits_it():
    assert decide(FULL_LADDER, 6).rung is Rung.FULL_SOLUTION


def test_a_recurring_misconception_targets_the_help():
    decision = decide(WITHHELD_LADDER, 2, recurring="sign_error_on_transfer")
    assert decision.target_misconception == "sign_error_on_transfer"


def test_varied_errors_do_not_accelerate_escalation():
    """A student making different mistakes is exploring, not stuck. They reach
    the same rung as a student repeating one mistake - only the targeting
    differs - so varied errors never pull the answer closer."""
    stuck = decide(WITHHELD_LADDER, 2, recurring="sign_error_on_transfer")
    exploring = decide(WITHHELD_LADDER, 2, recurring=None)
    assert stuck.rung is exploring.rung
    assert exploring.target_misconception is None


def test_decisions_carry_a_policy_version_for_the_audit_trail():
    assert decide(WITHHELD_LADDER, 1).policy_version


def test_a_ladder_may_not_permit_a_rung_it_omits():
    with pytest.raises(ValueError, match="max_rung"):
        AssistanceLadder.from_contract(
            {
                "rungs": [Rung.ATTEMPT.value, Rung.DIAGNOSTIC_QUESTION.value],
                "max_rung": Rung.PARTIAL_STEP.value,
                "allow_full_solution": False,
            }
        )


def test_a_ladder_may_not_smuggle_in_the_full_solution():
    """`allow_full_solution` is the explicit permission the note requires; a
    ladder listing the rung without it is a contradiction, not a shortcut."""
    with pytest.raises(ValueError, match="allow_full_solution"):
        AssistanceLadder.from_contract(
            {
                "rungs": [r.value for r in Rung],
                "max_rung": Rung.FULL_SOLUTION.value,
                "allow_full_solution": False,
            }
        )
