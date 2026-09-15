"""Server-side checks on what the class agent says to a student.

The teacher's rules go to the agent as instructions, and a model told not to
give the answer still sometimes does (TASD). So every reply to a student is
checked here, after it is generated and before the student sees it. These are
deterministic checks - they can't themselves be talked round.

What is reported is what was observed in the platform's own output. It is
never a claim about the student's intent.

Student messages are screened too, for attempts to get the agent to break its
rules. That produces a signal for triage, not an accusation.
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from app.agent.brief import Step
from app.agent.policy import PolicyRules, disclosure_rank
from app.enums import AgentMove, ConflictCode, Disclosure, Judgment, StepKind

# A reply this long, on a step where the student produces the work, is the work.
WROTE_THE_WORK_WORDS = 120


class SupervisorAction(StrEnum):
    ACCEPT = "accept"
    REGENERATE = "regenerate"
    WITHHOLD = "withhold"


@dataclass(frozen=True)
class Verdict:
    action: SupervisorAction
    conflicts: tuple[ConflictCode, ...] = ()
    reason: str = ""

    @property
    def accepted(self) -> bool:
        return self.action is SupervisorAction.ACCEPT


def normalise(text: str) -> str:
    """Lower case, one space, no punctuation that doesn't change meaning."""
    folded = unicodedata.normalize("NFKC", text or "").lower()
    folded = re.sub(r"[−–—]", "-", folded)
    folded = re.sub(r"[^\w\s.=+\-/%]", " ", folded)
    return re.sub(r"\s+", " ", folded).strip().rstrip(".")


def leaks(reference: str, message: str) -> bool:
    """Whether `message` states the reference answer.

    A short answer ("5", "chlorophyll") counts when it appears as an answer is
    stated ("the answer is 5", "x = 5", "it's chlorophyll"); a longer one counts
    when the whole of it appears. A good hint can mention part of an answer, so
    this deliberately doesn't fire on shared words.
    """
    ref = normalise(reference)
    said = normalise(message)
    if not ref or not said:
        return False
    if len(ref.split()) >= 3:
        return ref in said
    value = re.escape(ref)
    stated = re.compile(
        rf"(?:\banswer\b|\bsolution\b|\bresult\b|\bit s\b|\bit is\b|\bis\b|=|:)\s*[+-]?{value}\b"
    )
    return bool(stated.search(said))


def review(
    *,
    message: str,
    move: AgentMove,
    disclosure: Disclosure,
    judgment: Judgment | None,
    step: Step | None,
    rules: PolicyRules,
    attempts_on_step: int,
    is_retry: bool,
) -> Verdict:
    allowed = rules.allowed_disclosure(attempts_on_step)
    conflicts: list[ConflictCode] = []
    reasons: list[str] = []

    if disclosure_rank(disclosure) > disclosure_rank(allowed):
        conflicts.append(ConflictCode.OVER_DISCLOSURE)
        reasons.append(
            f"gave a {disclosure.value} answer where only {allowed.value} is allowed "
            f"after {attempts_on_step} attempts"
        )

    if (
        step is not None
        and step.reference_answer
        and allowed is not Disclosure.FULL
        and leaks(step.reference_answer, message)
    ):
        conflicts.append(ConflictCode.ANSWER_LEAKAGE)
        reasons.append("stated the step's answer before the rules allow it")

    if (
        not rules.may_write_for_student
        and step is not None
        and step.kind in (StepKind.PRACTICE, StepKind.CHECK)
        and len(message.split()) > WROTE_THE_WORK_WORDS
    ):
        conflicts.append(ConflictCode.WROTE_THE_WORK)
        reasons.append(f"a reply of {len(message.split())} words on a step the student writes")

    if move in (AgentMove.ADVANCE, AgentMove.COMPLETE) and judgment is None:
        conflicts.append(ConflictCode.SKIPPED_ASSESSMENT)
        reasons.append("moved the student on without judging their answer")

    if not conflicts:
        return Verdict(SupervisorAction.ACCEPT)
    return Verdict(
        SupervisorAction.WITHHOLD if is_retry else SupervisorAction.REGENERATE,
        tuple(conflicts),
        "; ".join(reasons),
    )


# Plain attempts to get the agent to drop its rules or hand over the work.
# Deliberately narrow: "I don't get it, can you just explain" is not on this list.
_MANIPULATION = [
    r"\bignore (all |your |the )?(previous |prior |earlier )?(instructions|rules|prompt)",
    r"\b(forget|disregard) (your|the|all) (rules|instructions)",
    r"\byou are now\b",
    r"\b(pretend|act as if) (you are|you're) (not|my|a) ",
    r"\bsystem prompt\b",
    r"\bjust (tell|give) me the (answer|solution)",
    r"\b(write|do) (it|this|the (essay|paragraph|homework|work|answer)) for me\b",
    r"\bmy teacher (said|says) (you can|it'?s ok|you're allowed)",
    r"\bdeveloper mode\b",
]
_MANIPULATION_RE = [re.compile(p, re.IGNORECASE) for p in _MANIPULATION]


def screen_student_message(text: str) -> list[str]:
    """The manipulation patterns a student message matches, if any."""
    return [p.pattern for p in _MANIPULATION_RE if p.search(text or "")]
