"""Deterministic grading.

Correctness is settled before any model is called, so the LLM is never the
judge of whether a student is right. That makes these rules load-bearing.
"""

import pytest

from app.grading import ExactMatchGrader, normalise

grader = ExactMatchGrader()


@pytest.mark.parametrize(
    "submission",
    ["5", " 5 ", "x = 5", "X=5", "x=5.", "5.0", "+5", "\t5\n"],
    ids=["plain", "padded", "with-x", "caps", "trailing-stop", "decimal", "signed", "whitespace"],
)
def test_accepts_equivalent_forms_of_a_correct_answer(submission):
    assert grader.grade(submission, "5").correct


@pytest.mark.parametrize(
    "submission",
    ["4", "", "   ", "five", "50", "-5", "x = 4"],
    ids=["wrong", "empty", "blank", "word", "digits-appended", "sign", "wrong-with-x"],
)
def test_rejects_wrong_answers(submission):
    assert not grader.grade(submission, "5").correct


def test_unicode_minus_is_treated_as_a_minus_sign():
    assert grader.grade("− 3", "-3").correct


def test_normalisation_is_reported_so_the_ledger_records_what_was_compared():
    result = grader.grade(" x = 5.0 ", "5")
    assert result.normalised == "5"
    assert result.expected_normalised == "5"


def test_normalise_is_stable_for_non_numeric_input():
    assert normalise(" Two Thirds ") == "two thirds"
