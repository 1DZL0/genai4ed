"""The assistance ladder (concept note S2).

    attempt -> diagnostic question -> conceptual cue -> targeted hint
            -> analogous example -> partial step -> full solution

The ladder, its ceiling, and whether the full solution is reachable at all are
read from the teacher's lesson contract. This module decides only what is
*permitted*; enforcing it against what the model actually produced is the
Supervisor's job, because a policy that lives only in a prompt is a suggestion.

Pure: no database, no clock, no model. `TutorPolicy` is the seam.
"""

from dataclasses import dataclass
from typing import Protocol

from app.enums import LADDER, Rung, rung_index

POLICY_VERSION = "ladder-v1"


@dataclass(frozen=True)
class AssistanceLadder:
    rungs: tuple[Rung, ...]
    max_rung: Rung
    allow_full_solution: bool

    @classmethod
    def from_contract(cls, data: dict) -> "AssistanceLadder":
        rungs = tuple(Rung(r) for r in data["rungs"])
        max_rung = Rung(data["max_rung"])
        allow_full_solution = bool(data.get("allow_full_solution", False))

        if max_rung not in rungs:
            raise ValueError(f"max_rung {max_rung.value!r} is not among the contract's rungs")
        if Rung.FULL_SOLUTION in rungs and not allow_full_solution:
            raise ValueError(
                "a ladder listing full_solution must also set allow_full_solution; "
                "the note requires that permission to be explicit"
            )
        # Ordering is canonical, not whatever order the contract happened to list.
        ordered = tuple(r for r in LADDER if r in rungs)
        return cls(rungs=ordered, max_rung=max_rung, allow_full_solution=allow_full_solution)

    def ceiling(self) -> Rung:
        """The highest rung this contract actually permits."""
        top = self.max_rung
        if top is Rung.FULL_SOLUTION and not self.allow_full_solution:
            top = Rung.PARTIAL_STEP
        return top


@dataclass(frozen=True)
class PolicyInput:
    ladder: AssistanceLadder
    incorrect_attempts: int
    correct: bool = False
    recurring_misconception: str | None = None


@dataclass(frozen=True)
class PolicyDecision:
    rung: Rung
    rationale: str
    policy_version: str
    target_misconception: str | None = None


class TutorPolicy(Protocol):
    def decide(self, data: PolicyInput) -> PolicyDecision: ...


class LadderPolicy:
    """One rung per incorrect attempt, capped by the contract.

    A recurring misconception changes *what* the help is about, never how fast
    the ladder is climbed. Escalating faster for a stuck student would pull the
    answer closer exactly when productive effort matters most, and the note's
    policy-fidelity question is about preserving that effort.
    """

    def decide(self, data: PolicyInput) -> PolicyDecision:
        if data.correct:
            return PolicyDecision(
                rung=Rung.ATTEMPT,
                rationale="Answer is correct; no assistance required.",
                policy_version=POLICY_VERSION,
            )

        ceiling = data.ladder.ceiling()
        wanted = min(max(data.incorrect_attempts, 0), rung_index(ceiling))
        rung = LADDER[wanted]

        if rung is ceiling and data.incorrect_attempts > rung_index(ceiling):
            rationale = f"Held at {ceiling.value}: the contract permits no further assistance."
        else:
            rationale = (
                f"Attempt {data.incorrect_attempts} incorrect; advanced one rung to {rung.value}."
            )

        target = data.recurring_misconception if rung is not Rung.ATTEMPT else None
        if target:
            rationale += f" Targeting recurring misconception {target!r}."

        return PolicyDecision(
            rung=rung,
            rationale=rationale,
            policy_version=POLICY_VERSION,
            target_misconception=target,
        )
