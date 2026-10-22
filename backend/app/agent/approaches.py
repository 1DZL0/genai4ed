"""Two ways of teaching the same lesson, for a side-by-side comparison: what the agent is told
for each while it drafts with the teacher and on every turn with a student.

Built for measurement. Both approaches are written to the same template, phase by phase, so
they differ only where the approach differs; everything else about a lesson (its steps,
questions, answers, marks, time, the teacher's escalations, the main prompts, the answer rule)
is held constant, and "Make the other version" copies a lesson so the content is identical.
The version is a hash of this text: any edit to either approach is a new version, recorded in
the manifest of every turn it shaped."""

import hashlib
import json
import re

from app.agent.brief import RULES_TEXT_MAX
from app.agent.policy import _WORKED_AFTER as WORKED_AFTER

NAMES = {"direct": "direct instruction", "inquiry": "guided inquiry"}

# The one setting the approach fixes in the lesson's rules: how many wrong tries before a worked
# step. Hints stay allowed and the final answer stays never, in both.
RULES = {
    "direct": {
        "hints_allowed": True,
        "partial_after_attempts": 0,
        "full_answer_after_attempts": None,
    },
    "inquiry": {
        "hints_allowed": True,
        "partial_after_attempts": 2,
        "full_answer_after_attempts": None,
    },
}

# The same rule in the teacher's words, as it goes into rules_text. The teacher's sentences
# outrank the model's numbers (policy.from_teachers_words), so they must say the same thing.
RULE_WORDS = {
    "direct": "Worked steps from the start, before any try.",
    "inquiry": "Worked steps only after two tries.",
}

# What is the same in both, said to the agent in both, so neither drifts from the lesson.
_SHARED = (
    "The steps, questions, answers and marks are the teacher's and are the same whichever "
    "approach is used: do not add, drop or reorder steps. The main rules still hold: never the "
    "final answer, never the student's work, the same signals to the teacher. Where the lesson's "
    "strategy says how to teach (what comes first, when to explain or show a step), this "
    "approach decides; keep the strategy's level, tone and emphasis."
)

# One entry per phase of a step, in the same order for both, so the two differ only in what the
# approach says to do, not in how much is said.
_PHASES = (
    "Opening a step",
    "While they work",
    "When they are stuck",
    "When they are wrong",
    "When they are right",
    "Closing a step",
)

_TEACHING = {
    "direct": {
        "Opening a step": (
            "Explain the idea first, in a few plain sentences, and model it with one worked "
            "example that is not the student's question. Then ask the step's question."
        ),
        "While they work": (
            "Ask one short question at a time with a definite answer. Keep the pace up and the "
            "path narrow: one method, the one you modelled."
        ),
        "When they are stuck": (
            "Show the next step of the method as soon as the rules above allow it, and ask them "
            "to do the one after."
        ),
        "When they are wrong": (
            "Say so at once, show the correct step and why, then give a near-identical question "
            "to try again."
        ),
        "When they are right": "Confirm it briefly, name what was right, and move on.",
        "Closing a step": (
            "Restate the idea in one sentence and check it with one quick question before the "
            "next step."
        ),
    },
    "inquiry": {
        "Opening a step": (
            "Put the step's question or problem first and explain nothing yet. Ask one open "
            "question: what they notice, or what they would try first. Their own question about "
            "it is welcome; take it up."
        ),
        "While they work": (
            "Follow their line of thought, not a fixed method. Any sound method counts. Ask why "
            "they think that, or what would happen if. Hold back your own judgment of right or "
            "wrong while they are still working it out."
        ),
        "When they are stuck": (
            "Offer a hint, a smaller case or a question that opens a way, not the step itself. A "
            "worked step only when the rules above allow it, and then of a different example."
        ),
        "When they are wrong": (
            "Treat the mistake as information: ask them to test their own answer against the "
            "problem, or to compare two of their attempts, so they find the flaw themselves."
        ),
        "When they are right": (
            "Ask them to explain their reasoning in their own words before you confirm anything; "
            "then confirm and name the idea they used."
        ),
        "Closing a step": (
            "Only now explain the idea properly, built from what they tried and said, and "
            "connect it to the general case before the next step."
        ),
    },
}

_DRAFTING = {
    "direct": (
        "The teacher chose DIRECT INSTRUCTION for this lesson. In the brief: keep their steps, "
        "questions and answers exactly as given; in the strategy write only the level, tone and "
        "emphasis, because this approach decides the order and the help; set the rules to hints "
        "allowed, worked steps from the start, before any try (partial_after_attempts 0), the "
        "final answer never, unless the teacher says otherwise. Do not list the rules in your "
        "reply; the card shows them."
    ),
    "inquiry": (
        "The teacher chose GUIDED INQUIRY for this lesson. In the brief: keep their steps, "
        "questions and answers exactly as given; in the strategy write only the level, tone and "
        "emphasis, because this approach decides the order and the help; set the rules to hints "
        "allowed, a worked step only after two wrong tries (partial_after_attempts 2), the final "
        "answer never, unless the teacher says otherwise. Do not list the rules in your reply; "
        "the card shows them."
    ),
}


def _digest() -> str:
    text = json.dumps({"shared": _SHARED, "teach": _TEACHING, "draft": _DRAFTING, "rules": RULES})
    return hashlib.sha256(text.encode()).hexdigest()[:8]


VERSION = f"approach-v3-{_digest()}"


def drafting(approach: str) -> str:
    """What the agent is told while building the lesson with the teacher."""
    return f"Teaching approach: {_DRAFTING[approach]} {_SHARED}"


def teaching(approach: str) -> str:
    """What the agent is told on every turn with a student in that lesson."""
    lines = [f"Teaching approach for this lesson: {NAMES[approach]}. {_SHARED}"]
    lines += [f"{phase}: {_TEACHING[approach][phase]}" for phase in _PHASES]
    return "\n".join(lines)


# Any mention of worked steps in the teacher's rules.
_WORKED_SENTENCE = re.compile(r"\bworked (?:steps?|examples?|solutions?)\b", re.IGNORECASE)
# The clause that sets them in the approach's words, which from_teachers_words reads back as
# the approach's own number (none for "from the start", 2 for "after two tries").
_WORKED_CLAUSE = {
    "direct": "worked steps from the start",
    "inquiry": "worked steps only after two tries",
}


# Words that turn a worked-step clause round or narrow it ("no worked steps until after two
# tries", "only after"): such a sentence is rebuilt, never edited, so the approach's rule is
# never said backwards.
_TURNED = re.compile(r"\b(?:no|not|never|don'?t|do not|without|avoid|only|until)\b", re.I)
_CLAUSE = re.compile(r"\s*[,;:]\s*")
_JOINER = re.compile(r"^(?:but|and|so|though|yet|then)\s+", re.I)
# A clause that only says when ("before any try", "only after two tries", "from the start"):
# part of the worked-step rule being replaced, so it goes with it.
_TIMING = re.compile(
    r"\b(?:before|after|until)\b[^,;:]*\b(?:try|tries|attempts?|goes)\b|\bfrom the start\b", re.I
)


def _other_clauses(sentence: str) -> str:
    """What else a sentence about worked steps says, as a sentence of its own, or nothing."""
    kept = [
        _JOINER.sub("", c).strip()
        for c in _CLAUSE.split(sentence.rstrip(".!? "))
        if c.strip() and not _WORKED_SENTENCE.search(c) and not _TIMING.search(c)
    ]
    kept = [c for c in kept if c]
    if not kept:
        return ""
    text = ", ".join(kept)
    return text[0].upper() + text[1:] + "."


def rules_text_for(rules_text: str, approach: str) -> str:
    """The teacher's rules in their words with the worked-step part made to say what the
    approach sets, so a later edit cannot quietly put the old number back. A plain clause
    ("show worked steps after one try") is reworded in place; a sentence that turns it round
    or says something else about worked steps is replaced by the approach's own words. The
    rest, such as "never just give the final value", is kept."""
    out, mentioned = [], False
    for sentence in (s.strip() for s in re.split(r"(?<=[.!?])\s+", rules_text or "")):
        if not sentence:
            continue
        found = WORKED_AFTER.search(sentence)
        if found and not _TURNED.search(sentence[: found.start()] + found.group(0)):
            out.append(WORKED_AFTER.sub(_WORKED_CLAUSE[approach], sentence, count=1))
            mentioned = True
        elif found or _WORKED_SENTENCE.search(sentence):
            if rest := _other_clauses(sentence):
                out.append(rest)
        else:
            out.append(sentence)
    if not mentioned:
        out.append(RULE_WORDS[approach])
    text = " ".join(out)
    if len(text) <= RULES_TEXT_MAX:
        return text
    # Too long to keep whole: the approach's rule stays, the teacher's other words are cut.
    clause = _WORKED_CLAUSE[approach]
    rule = next((s for s in out if clause in s.lower()), RULE_WORDS[approach])
    rest = " ".join(s for s in out if s is not rule)
    room = RULES_TEXT_MAX - len(rule) - 1
    return f"{rest[:room].rstrip()} {rule}".strip() if room > 0 else rule[:RULES_TEXT_MAX]


def for_research() -> dict:
    return {
        "version": VERSION,
        "held_constant": _SHARED,
        "items": {
            key: {
                "name": NAMES[key],
                "drafting": drafting(key),
                "teaching": teaching(key),
                "rules": RULES[key],
            }
            for key in NAMES
        },
    }
