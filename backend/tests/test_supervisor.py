"""Server-side enforcement of the ladder.

The leakage cases matter most: TASD found that instructing a model not to give
direct answers reduced but did not eliminate them, which is the reason this
check exists in output rather than in a prompt.
"""

import pytest

from app.enums import ConflictCode, Rung
from app.schemas import TutorResponse
from app.tutor.supervisor import PolicySupervisor, SupervisorAction

supervisor = PolicySupervisor()
VOCABULARY = ("sign_error_on_transfer", "combines_unlike_terms", "arithmetic_slip")


def review(message, rung_used, permitted, *, expected="5", code=None, is_retry=False):
    response = TutorResponse(
        message=message,
        rung_used=rung_used,
        misconception_code=code,
        confidence=0.8,
    )
    return supervisor.review(
        response,
        permitted=permitted,
        expected_answer=expected,
        vocabulary=VOCABULARY,
        is_retry=is_retry,
    )


def test_a_compliant_response_is_accepted():
    verdict = review(
        "When 2x crosses the equals sign it changes sign.",
        Rung.TARGETED_HINT,
        Rung.TARGETED_HINT,
        code="sign_error_on_transfer",
    )
    assert verdict.accepted
    assert verdict.conflicts == ()


def test_climbing_past_the_permitted_rung_is_a_conflict():
    verdict = review("Here is the full method.", Rung.FULL_SOLUTION, Rung.CONCEPTUAL_CUE)
    assert ConflictCode.RUNG_EXCEEDED in verdict.conflicts
    assert not verdict.accepted


def test_stating_the_answer_early_is_a_conflict():
    verdict = review("Think about it this way: x = 5.", Rung.TARGETED_HINT, Rung.TARGETED_HINT)
    assert ConflictCode.ANSWER_LEAKAGE in verdict.conflicts


@pytest.mark.parametrize(
    "message",
    ["The answer is 5.", "so x equals 5", "x=5", "the solution is +5"],
    ids=["prose", "equals-word", "compact", "signed"],
)
def test_leakage_is_caught_across_phrasings(message):
    verdict = review(message, Rung.CONCEPTUAL_CUE, Rung.CONCEPTUAL_CUE)
    assert ConflictCode.ANSWER_LEAKAGE in verdict.conflicts


def test_quoting_the_question_is_not_leakage():
    """A good hint restates the equation, and the equation contains a 5. A
    substring search would fire here; stating the answer is what matters."""
    verdict = review(
        "Look again at 5x - 7 = 2x + 8. Which side will you collect x on?",
        Rung.DIAGNOSTIC_QUESTION,
        Rung.DIAGNOSTIC_QUESTION,
    )
    assert verdict.accepted


def test_a_teacher_sanctioned_full_solution_may_state_the_answer():
    verdict = review("Dividing gives x = 5.", Rung.FULL_SOLUTION, Rung.FULL_SOLUTION)
    assert verdict.accepted


def test_a_diagnosis_outside_the_vocabulary_is_a_conflict():
    verdict = review(
        "Check your signs.", Rung.TARGETED_HINT, Rung.TARGETED_HINT, code="careless_student"
    )
    assert ConflictCode.INVALID_DIAGNOSIS in verdict.conflicts


def test_first_failure_regenerates_and_a_repeat_withholds():
    assert review("x = 5", Rung.TARGETED_HINT, Rung.TARGETED_HINT).action is (
        SupervisorAction.REGENERATE
    )
    assert review(
        "x = 5", Rung.TARGETED_HINT, Rung.TARGETED_HINT, is_retry=True
    ).action is SupervisorAction.WITHHOLD


def test_conflicts_are_reported_as_observations_not_accusations():
    """The wording is load-bearing: the note allows reporting what the platform
    observed in its own output, and forbids inferring intent."""
    verdict = review("The answer is 5.", Rung.FULL_SOLUTION, Rung.CONCEPTUAL_CUE)
    assert "stated the answer" in verdict.reason
    assert not any(word in verdict.reason.lower() for word in ("cheat", "intent", "dishonest"))
