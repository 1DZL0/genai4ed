"""Deterministic checks on what the class agent says, run before a student sees it.

Student messages are screened too, for attempts to make the agent break its rules
and for signs of distress; both produce signals for triage, not accusations.
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
    """Whether `message` states the reference answer (short: as "x = 5"; long: in full)."""
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


# Things only a teacher can do; a reply claiming to have done one is false.
_TEACHER_ONLY = re.compile(
    r"\bI(?:'ve|'ll|'m| have| will| can| could| am able to| already)?\s*(?:now|just|then)?\s*"
    r"\b(approv\w*|start\w*|launch\w*|end\w*|clos\w*|paus\w*|resum\w*|schedul\w*|"
    r"sen[dt]\w*|messag\w*|email\w*|notifi\w*|told|mark\w*|grad\w*|scor\w*|"
    r"confirm\w*|award\w*|assign\w*)\b[^.?!\n]{0,70}?"
    r"\b(lesson|class|session|student|pupil|grade|mark|outcome|score|work|answers?|"
    r"homework|books?|year\s*\d|\d+[a-z])\b",
    re.IGNORECASE,
)

# Marks are the teacher's decision, so an ordinary verb aimed at one is a claim too.
_MARKS_ONLY = re.compile(
    r"\bI(?:'ve|'ll|'m| have| will| can| could| already)?\s*(?:now|just)?\s*"
    r"\b(chang\w*|set|updat\w*|giv\w*|award\w*|enter\w*|record\w*|adjust\w*|"
    r"rais\w*|lower\w*|provid\w*|releas\w*|publish\w*)\b[^.?!\n]{0,40}?"
    r"\b(grades?|marks?|scores?|results?|reports?)\b",
    re.IGNORECASE,
)


def claims_teacher_action(reply: str) -> list[str]:
    """The sentences in `reply` that claim a teacher's action as the agent's own."""
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", reply)
        if _TEACHER_ONLY.search(sentence) or _MARKS_ONLY.search(sentence)
    ]


def without_claims(reply: str, claimed: list[str], next_button: str = "") -> str:
    """The reply with those sentences replaced by the truth, and what to press."""
    truth = (
        "I can't do that myself - approving a lesson, starting it, ending it and "
        "confirming outcomes are buttons on the card on the right."
    )
    kept = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", reply)
        if sentence.strip() and sentence.strip() not in (*claimed, truth, next_button)
    ]
    kept.append(truth)
    if next_button:
        kept.append(next_button)
    return " ".join(kept)


def names_without_evidence(reply: str, silent: set[str]) -> list[str]:
    """Sentences naming a student who has not said anything yet."""
    lowered = {name.lower() for name in silent}
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", reply)
        if set(re.findall(r"[\w-]+", sentence.lower())) & lowered
    ]


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
    task: str = "",
    later_references: tuple[str, ...] = (),
    rung: str | None = None,
    permitted_rung: str | None = None,
    student_said: str = "",
    worked_example: bool = False,
) -> Verdict:
    """Check one reply (and the `task` it sets, which reaches the student too)."""
    allowed = rules.allowed_disclosure(attempts_on_step)
    # A worked example of a different problem is what the button promises, not the answer.
    if worked_example and disclosure_rank(allowed) < disclosure_rank(Disclosure.PARTIAL):
        allowed = Disclosure.PARTIAL
    conflicts: list[ConflictCode] = []
    reasons: list[str] = []

    if disclosure_rank(disclosure) > disclosure_rank(allowed):
        conflicts.append(ConflictCode.OVER_DISCLOSURE)
        reasons.append(
            f"gave a {disclosure.value} answer where only {allowed.value} is allowed "
            f"after {attempts_on_step} attempts"
        )

    # Later steps' answers count too; one the student already stated does not.
    references = [
        ref
        for ref in (step.reference_answer if step else None, *later_references)
        if ref and not leaks(ref, student_said)
    ]
    if allowed is not Disclosure.FULL and any(
        leaks(ref, f"{message}\n{task}") for ref in references
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

    # On the ladder only the permitted rung is allowed; a met answer needs no help.
    if permitted_rung is not None and judgment is not Judgment.MET and rung != permitted_rung:
        conflicts.append(ConflictCode.OFF_LADDER)
        reasons.append(
            f"gave {rung or 'help it did not name'} where the ladder allows {permitted_rung}"
        )

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
_MANIPULATION = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bignore (all |your |the )?(previous |prior |earlier )?(instructions|rules|prompt)",
        r"\b(forget|disregard) (your|the|all) (rules|instructions)",
        r"\byou are now\b",
        r"\b(pretend|act as if) (you are|you're) (not|my|a) ",
        r"\bsystem prompt\b",
        r"\bjust (tell|give) me the (answer|solution)",
        r"\b(write|do) (it|this|the (essay|paragraph|homework|work|answer)) for me\b",
        r"\bmy teacher (said|says) (you can|it'?s ok|you're allowed)",
        r"\bdeveloper mode\b",
    )
]


def screen_student_message(text: str) -> list[str]:
    """The manipulation patterns a student message matches, if any."""
    return [p.pattern for p in _MANIPULATION if p.search(text or "")]


# Words a distressed student uses: a floor under the model's noticing, not a diagnosis.
_DISTRESS_HIGH = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(kill|hurt|harm)(ing)? myself\b",
        r"\bwant to die\b",
        r"\bself[- ]harm",
        r"\bsuicid",
    )
]
_DISTRESS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(want to |wanna |gonna |going to |i )?give up\b",
        r"\bi(?:'m| am|m) (so |really |just |too )?"
        r"(stupid|dumb|useless|worthless|thick|hopeless|a failure)\b",
        r"\bi feel (so |really |like i'?m )?(stupid|dumb|useless|worthless|hopeless)\b",
        r"\bhate (myself|my life)\b",
        r"\bnobody (cares|likes me)\b",
        r"\bi can'?t do anything\b",
    )
]


def screen_wellbeing(text: str) -> str | None:
    """Whether a student message reads as distress: "high", "medium" or None."""
    if any(p.search(text or "") for p in _DISTRESS_HIGH):
        return "high"
    if any(p.search(text or "") for p in _DISTRESS):
        return "medium"
    return None
