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

# What is the same in both, said to the agent in both, so neither drifts from the lesson.
_SHARED = (
    "The steps, questions, answers and marks are the teacher's and are the same whichever "
    "approach is used: do not add, drop or reorder steps. The main rules still hold: never the "
    "final answer, never the student's work, the same signals to the teacher."
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
            "Show the next step of the method straight away and ask them to do the one after."
        ),
        "When they are wrong": (
            "Say so at once, show the correct step and why, then give a near-identical question "
            "to try again."
        ),
        "When they are right": ("Confirm it briefly, name what was right, and move on."),
        "Closing a step": (
            "Restate the idea in one sentence and check it with one quick question before the "
            "next step."
        ),
    },
    "inquiry": {
        "Opening a step": (
            "Put the step's question or problem first and explain nothing yet. Ask what they "
            "notice, what they already know that might help, and what they would try first. "
            "Their own question about it is welcome; take it up."
        ),
        "While they work": (
            "Follow their line of thought, not a fixed method. Any sound method counts. Ask why "
            "they think that, and what would happen if. Hold back your own judgment of right or "
            "wrong while they are still working it out."
        ),
        "When they are stuck": (
            "Offer a hint, a smaller case or a question that opens a way, not the step itself. "
            "A worked step only after two wrong tries, and then of a different example."
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
        "questions and answers exactly as given; write the strategy as explain, model, question, "
        "correct at once, practise; set the rules to hints allowed, a worked step from the first "
        "wrong try (partial_after_attempts 0), the final answer never, unless the teacher says "
        "otherwise. Read those rules back to them."
    ),
    "inquiry": (
        "The teacher chose GUIDED INQUIRY for this lesson. In the brief: keep their steps, "
        "questions and answers exactly as given; write the strategy as problem first, the "
        "student's own reasoning before any explanation, explanation after the work; set the "
        "rules to hints allowed, a worked step only after two wrong tries "
        "(partial_after_attempts 2), the final answer never, unless the teacher says otherwise. "
        "Read those rules back to them."
    ),
}


def _digest() -> str:
    text = json.dumps({"shared": _SHARED, "teach": _TEACHING, "draft": _DRAFTING, "rules": RULES})
    return hashlib.sha256(text.encode()).hexdigest()[:8]


VERSION = f"approach-v2-{_digest()}"


def drafting(approach: str) -> str:
    """What the agent is told while building the lesson with the teacher."""
    return f"Teaching approach: {_DRAFTING[approach]} {_SHARED}"


def teaching(approach: str) -> str:
    """What the agent is told on every turn with a student in that lesson."""
    lines = [f"Teaching approach for this lesson: {NAMES[approach]}. {_SHARED}"]
    lines += [f"{phase}: {_TEACHING[approach][phase]}" for phase in _PHASES]
    return "\n".join(lines)


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
