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
WROTE_THE_WORK_WORDS = 200


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


# A list item's number or bullet on its own: never a sentence, always part of the next one.
_MARKER = re.compile(r"^(?:\d+[.)]|[-*•])$")


def _in_line(line: str) -> list[str]:
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
    # "1. I've approved it." is one sentence: struck, it goes with its number, not leaving "1.".
    if len(parts) > 1 and _MARKER.match(parts[0]):
        parts = [f"{parts[0]} {parts[1]}", *parts[2:]]
    return parts


def sentences(reply: str) -> list[str]:
    """Each sentence, line by line: a line with no full stop ("Here is the class:", a list
    item) is a sentence of its own, never joined to the next line. The checks that find a
    sentence and `strike`, which removes it, must cut the reply the same way."""
    return [s for line in reply.split("\n") for s in _in_line(line)]


def claims_teacher_action(reply: str) -> list[str]:
    """The sentences in `reply` that claim a teacher's action as the agent's own."""
    return [s for s in sentences(reply) if _TEACHER_ONLY.search(s) or _MARKS_ONLY.search(s)]


def strike(reply: str, remove: list[str]) -> str:
    """The reply without those sentences, keeping its lines: a numbered choice stays on its
    own line instead of being run into the paragraph before it."""
    gone = {s.strip() for s in remove}
    lines = []
    for line in reply.split("\n"):
        kept = [s for s in _in_line(line) if s not in gone]
        if kept and not (len(kept) == 1 and _MARKER.match(kept[0])):
            lines.append(" ".join(kept))
        elif not line.strip():
            lines.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def without_claims(reply: str, claimed: list[str], next_button: str = "") -> str:
    """The reply with those sentences replaced by the truth, and what to press."""
    truth = (
        "I haven't done that. Tell me to approve, start, pause or end a lesson and I "
        "will, or use the buttons on the card on the right. Confirming outcomes is yours."
    )
    # Sentence by sentence, so a reply that already says the truth does not say it twice.
    kept = strike(reply, [*claimed, *sentences(truth), *sentences(next_button)])
    return "\n".join(x for x in (kept, truth, next_button) if x)


_NOT_STARTED = re.compile(
    r"\b(?:has|have|had)n'?t\b[^.]*\bstart|\bnot (?:yet )?started\b|\byet to start\b", re.I
)


def _naming(name: str) -> re.Pattern:
    """The whole name as written, so "Ava Smith" and "O'Neil" are found and the student
    "Will" is not found in "the class will start". A name with capitals must match its case;
    an all-lowercase one ("student-4821") matches in any case."""
    flags = 0 if any(c.isupper() for c in name) else re.IGNORECASE
    return re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])", flags)


def names_without_evidence(reply: str, silent: set[str]) -> list[str]:
    """Sentences naming a student who has not said anything yet, other than to say so."""
    found = [_naming(name) for name in silent if name.strip()]
    return [
        s
        for s in sentences(reply)
        if any(p.search(s) for p in found) and not _NOT_STARTED.search(s)
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
    teacher_moved: bool = False,
) -> Verdict:
    """Check one reply (and the `task` it sets, which reaches the student too)."""
    allowed = rules.allowed_disclosure(attempts_on_step)
    # A worked example of a different problem is what the button promises, not the answer.
    if (
        worked_example
        and rules.hints_allowed
        and disclosure_rank(allowed) < disclosure_rank(Disclosure.PARTIAL)
    ):
        allowed = Disclosure.PARTIAL
    conflicts: list[ConflictCode] = []
    reasons: list[str] = []

    # On an explain step with no answer of its own, the explanation the teacher planned is
    # the point of the step, not a disclosure; the leak check below still guards later steps.
    explaining = step is not None and step.kind is StepKind.EXPLAIN and not step.reference_answer
    if not explaining and disclosure_rank(disclosure) > disclosure_rank(allowed):
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

    # Moving on needs a met judgment, or the teacher saying so: the server would refuse the
    # move anyway, and a reply that says "let's move on" to a student who then stays put
    # misleads them.
    if (
        move in (AgentMove.ADVANCE, AgentMove.COMPLETE)
        and judgment is not Judgment.MET
        and not teacher_moved
    ):
        conflicts.append(ConflictCode.SKIPPED_ASSESSMENT)
        reasons.append(
            "moved the student on without judging their answer"
            if judgment is None
            else f"moved the student on with a {judgment.value} answer, not a met one"
        )

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


# ---------- measured on every reply, never a gate ----------

_MARKUP = re.compile(r"[*#`]|\\\(|\\\[|\$\$")
# A reply that talks as if it had a life of its own.
_HUMAN_CLAIM = re.compile(
    r"\b(?:as a (?:human|person|teacher)|when i was (?:at school|your age|a student|younger)|"
    r"i(?:'m| am) (?:a (?:human|person|real teacher))|my own (?:school|childhood|kids|children)|"
    r"i remember (?:learning|doing|being))\b",
    re.IGNORECASE,
)
# Marks or grades stated to the student. A fraction like 3/4, or "50 out of 100" in a
# percentages lesson, is maths, not a mark: only words about marking count.
_MARKS = re.compile(
    r"\b(?:\d+ out of \d+ (?:marks?|points?)|(?:your|the) (?:marks?|grade|score)\b|"
    r"(?:you (?:get|got|scored?|earned?) )\d+ ?(?:marks?|points?)\b|grade [a-f]\b|"
    r"full marks\b)",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def measures(
    *,
    message: str,
    task: str | None,
    previous: str = "",
    classmates: list[str] | tuple[str, ...] = (),
    finished: bool = False,
    target_dok: int | None = None,
    depth_shown: int | None = None,
    uncertain: bool = False,
) -> dict:
    """Cheap counts on one reply, stored with the turn: style, a next action, a repeated
    reassurance, another student's name, a claim to be human, marks, and depth against the
    step's target. None of these holds a reply back."""
    sentences = _sentences(message)
    words = len(message.split())
    said_before = {normalise(s) for s in _sentences(previous) if len(s.split()) >= 4}
    repeated = any(len(s.split()) >= 4 and normalise(s) in said_before for s in sentences)
    text = f"{message}\n{task or ''}"
    named = [
        name
        for name in classmates
        if name and re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.IGNORECASE)
    ]
    out = {
        "words": words,
        "sentences": len(sentences),
        "words_per_sentence": round(words / len(sentences), 1) if sentences else 0,
        "question_marks": message.count("?"),
        "markup_chars": len(_MARKUP.findall(message)),
        "no_next_action": not finished and not (task or "").strip(),
        "repeated_reassurance": repeated,
        "classmate_mention": bool(named),
        "human_claim": bool(_HUMAN_CLAIM.search(message)),
        "marks_in_message": bool(_MARKS.search(message)),
    }
    if target_dok is not None and depth_shown is not None:
        out["depth"] = {
            "target": target_dok,
            "shown": depth_shown,
            "relation": (
                "under"
                if depth_shown < target_dok
                else "over"
                if depth_shown > target_dok
                else "aligned"
            ),
            "uncertain": uncertain,
        }
    return out


# Words a distressed student uses: a floor under the model's noticing, not a diagnosis.
_DISTRESS_HIGH = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(kill|hurt|harm)(ing)? myself\b",
        r"\bwant to die\b",
        r"\bself[- ]harm",
        r"\bsuicid",
        r"\b(?:every ?(?:one|body)|they all|people|they) (?:hates?|hate) me\b",
        r"\b(?:being |getting )?bullied\b|\bbull(?:y|ies|ying) me\b",
        r"\bnobody would (?:care|miss me|notice)\b",
        r"\b(?:can'?t|cannot) cope\b",
        r"\b(?:want|wanna|going) to cry\b|\bi'?m crying\b",
        r"\bi (?:have|got) no (?:friends|one)\b",
        r"\bnot safe at home\b|\bscared to go home\b",
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
        r"\bi feel (?:awful|terrible|so bad|sick of everything)\b",
        r"\b(?:so|really) (?:stressed|anxious|upset)\b",
    )
]


def screen_wellbeing(text: str) -> str | None:
    """Whether a student message reads as distress: "high", "medium" or None."""
    if any(p.search(text or "") for p in _DISTRESS_HIGH):
        return "high"
    if any(p.search(text or "") for p in _DISTRESS):
        return "medium"
    return None
