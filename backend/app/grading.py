"""Deterministic grading.

The model decides *how to help*, never *whether the student is right*. Keeping
correctness here means a tutor failure can never silently become a marking
failure, and it keeps every test deterministic.

`Grader` is the seam. A rubric-based grader for open responses would implement
the same protocol; nothing else would change.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

# Optional "x =" style prefix a student may type before the value itself.
_ANSWER_PREFIX = re.compile(r"^[a-z]\s*=\s*")
_UNICODE_MINUS = {"−": "-", "–": "-", "—": "-"}


def normalise(value: str) -> str:
    """Reduce a submission to the form that is compared and recorded."""
    text = unicodedata.normalize("NFKC", value or "").strip().lower()
    for dash, hyphen in _UNICODE_MINUS.items():
        text = text.replace(dash, hyphen)
    text = text.rstrip(".")
    text = _ANSWER_PREFIX.sub("", text).strip()
    # "- 3" and "-3" are the same answer.
    text = re.sub(r"^([+-])\s+", r"\1", text)
    return text


def _as_number(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _canonical(number: Decimal) -> str:
    """Shortest exact form, never scientific notation ("50", not "5E+1")."""
    return format(number.normalize(), "f")


@dataclass(frozen=True)
class GradeResult:
    correct: bool
    normalised: str
    expected_normalised: str


class Grader(Protocol):
    def grade(self, submission: str, expected: str) -> GradeResult: ...


class ExactMatchGrader:
    """Numeric where both sides are numeric, exact string match otherwise.

    Numeric comparison is what makes "5", "5.0" and "+5" one answer rather than
    three, without the grader ever guessing at intent.
    """

    def grade(self, submission: str, expected: str) -> GradeResult:
        got = normalise(submission)
        want = normalise(expected)
        if not got:
            return GradeResult(False, got, want)

        got_number, want_number = _as_number(got), _as_number(want)
        if got_number is not None and want_number is not None:
            # Canonical numeric form, so that "5", "5.0" and "+5" collapse to one
            # key. Later analysis groups repeated identical errors on this.
            return GradeResult(
                correct=got_number == want_number,
                normalised=_canonical(got_number),
                expected_normalised=_canonical(want_number),
            )
        return GradeResult(got == want, got, want)
