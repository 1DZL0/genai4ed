"""Server-side enforcement of the assistance ladder (concept note S2).

The policy says what help is permitted. This says whether what came back
actually obeyed it. That separation is the whole point: TASD showed that
instructing a model not to give direct answers reduced leakage without
eliminating it, so the ladder cannot live in a prompt.

What is reported is what was observed in the platform's own output - a rung it
was not permitted, the answer appearing early, a diagnosis outside the
teacher's vocabulary. These are 'assistance-policy conflicts'. They are never a
claim about the student's intent, and nothing here infers cheating.

This is not one model approving another. It is a handful of deterministic
checks, so it cannot itself hallucinate.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.enums import ConflictCode, Rung, rung_index
from app.grading import normalise
from app.schemas import TutorResponse


class SupervisorAction(StrEnum):
    ACCEPT = "accept"
    REGENERATE = "regenerate"
    WITHHOLD = "withhold"


@dataclass(frozen=True)
class SupervisorVerdict:
    action: SupervisorAction
    conflicts: tuple[ConflictCode, ...] = ()
    reason: str = ""

    @property
    def accepted(self) -> bool:
        return self.action is SupervisorAction.ACCEPT


def _leak_pattern(expected: str) -> re.Pattern[str]:
    """Match the answer being *stated*, not merely appearing.

    The item prompt itself contains numbers, and a good hint quotes the
    equation, so a bare substring search would fire on "5x - 7 = 2x + 8". This
    looks for the answer in an assignment position instead.

    It does not catch a spelled-out number, and it is not meant to be the only
    defence: the contract's rung ceiling is what stops the tutor reaching for
    the answer in the first place.
    """
    value = re.escape(normalise(expected))
    return re.compile(
        rf"(?:\bx\b|\banswer\b|\bsolution\b|\bresult\b)\s*(?:is|=|:|equals)\s*[+-]?{value}\b",
        re.IGNORECASE,
    )


class Supervisor(Protocol):
    def review(
        self,
        response: TutorResponse,
        *,
        permitted: Rung,
        expected_answer: str,
        vocabulary: tuple[str, ...],
        is_retry: bool,
    ) -> SupervisorVerdict: ...


class PolicySupervisor:
    def review(
        self,
        response: TutorResponse,
        *,
        permitted: Rung,
        expected_answer: str,
        vocabulary: tuple[str, ...],
        is_retry: bool,
    ) -> SupervisorVerdict:
        conflicts: list[ConflictCode] = []
        reasons: list[str] = []

        if rung_index(response.rung_used) > rung_index(permitted):
            conflicts.append(ConflictCode.RUNG_EXCEEDED)
            reasons.append(
                f"used {response.rung_used.value} where {permitted.value} was permitted"
            )

        if permitted is not Rung.FULL_SOLUTION and _leak_pattern(expected_answer).search(
            response.message
        ):
            conflicts.append(ConflictCode.ANSWER_LEAKAGE)
            reasons.append(f"stated the answer at rung {permitted.value}")

        if response.misconception_code and response.misconception_code not in vocabulary:
            conflicts.append(ConflictCode.INVALID_DIAGNOSIS)
            reasons.append(f"diagnosed {response.misconception_code!r}, which is not in the item")

        if not conflicts:
            return SupervisorVerdict(action=SupervisorAction.ACCEPT)

        return SupervisorVerdict(
            action=SupervisorAction.WITHHOLD if is_retry else SupervisorAction.REGENERATE,
            conflicts=tuple(conflicts),
            reason="; ".join(reasons),
        )
