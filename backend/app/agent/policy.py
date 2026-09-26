"""The teacher's rules for the class agent, compiled so the server can enforce them.

The teacher's own words go to the agent too; the compiled fields are what
`supervisor` and `triage` check.
"""

import re

from pydantic import BaseModel, Field

from app.enums import DISCLOSURE_ORDER, Disclosure, SignalKind, TriageAction


class Escalation(BaseModel):
    """What happens once a signal has been seen `after` times in a lesson."""

    signal: SignalKind
    after: int = Field(default=1, ge=1, le=20)
    action: TriageAction


class PolicyRules(BaseModel):
    hints_allowed: bool = True
    # Partial solutions and worked steps, after this many answers on a step.
    partial_after_attempts: int = Field(default=1, ge=0, le=20)
    # The final answer, after this many answers on a step. None: never.
    full_answer_after_attempts: int | None = Field(default=None, ge=0, le=20)
    # Whether the agent may produce the student's work (an essay, a finished solution).
    may_write_for_student: bool = False
    escalations: list[Escalation] = Field(default_factory=list, max_length=20)
    # Help in a fixed order, one rung per attempt.
    ladder: bool = False
    # Rules that aren't a setting, kept in the teacher's words.
    notes: list[str] = Field(default_factory=list, max_length=20)

    def allowed_disclosure(self, attempts_on_step: int) -> Disclosure:
        """The most of the answer a reply may give away at this point."""
        if self.full_answer_after_attempts is not None and (
            attempts_on_step >= self.full_answer_after_attempts
        ):
            return Disclosure.FULL
        if not self.hints_allowed:
            return Disclosure.NONE
        if attempts_on_step >= self.partial_after_attempts:
            return Disclosure.PARTIAL
        return Disclosure.HINT

    def escalation_for(self, signal: SignalKind) -> Escalation | None:
        return next((e for e in self.escalations if e.signal is signal), None)

    def describe(self) -> list[str]:
        """The rules read back to the teacher, one plain sentence each."""
        lines: list[str] = []
        if not self.hints_allowed:
            lines.append("No hints towards answers; the agent can still explain ideas.")
        else:
            lines.append("Hints are allowed at any time.")
            if self.partial_after_attempts == 0:
                lines.append("Worked steps are allowed straight away.")
            else:
                lines.append(
                    f"Worked steps only after {_times(self.partial_after_attempts)} "
                    "on the question."
                )
        if self.full_answer_after_attempts is None:
            lines.append("The final answer is never given.")
        elif self.full_answer_after_attempts == 0:
            lines.append("The final answer may be given when asked.")
        else:
            lines.append(f"The final answer only after {_times(self.full_answer_after_attempts)}.")
        if self.ladder:
            lines.append(
                "Help comes in a fixed order, one step each time they try: a question about "
                "their thinking, a cue, a hint, a similar example, then one step done together."
            )
        if not self.may_write_for_student:
            lines.append("The agent never writes a student's work for them.")
        told = sorted({SIGNAL_WORDS[e.signal].lower() for e in self.escalations})
        if told:
            lines.append(
                "The agent tells you when it thinks you should know about: " + ", ".join(told) + "."
            )
        lines.extend(
            f"{note.rstrip('.')} - kept in your words, not enforced automatically."
            for note in self.notes
        )
        return lines


def disclosure_rank(level: Disclosure) -> int:
    return DISCLOSURE_ORDER.index(level)


def _times(n: int) -> str:
    return "one attempt" if n == 1 else f"{n} attempts"


SIGNAL_WORDS: dict[SignalKind, str] = {
    SignalKind.STRUGGLING: "A student struggling",
    SignalKind.MISCONCEPTION: "A misconception",
    SignalKind.MANIPULATION_ATTEMPT: "Trying to get the agent to do the work or break the rules",
    SignalKind.OFF_TASK: "Going off task",
    SignalKind.FAST_PROGRESS: "Moving through unusually fast",
    SignalKind.UNRESOLVED_QUESTION: "A question the agent couldn't settle",
    SignalKind.WELLBEING: "A wellbeing concern",
    SignalKind.ASKED_FOR_TEACHER: "Asking for the teacher",
}

ACTION_WORDS: dict[TriageAction, str] = {
    TriageAction.LOG: "kept in the record",
    TriageAction.SUMMARISE: "included in your summary",
    TriageAction.ALERT: "shown to you straight away",
}


# The plainest rule sentences a teacher writes, taken literally over the model's reading.
_NUMBER = {"one": 1, "once": 1, "a": 1, "two": 2, "twice": 2, "three": 3, "four": 4, "five": 5}
_TRIES = r"(?:tries|attempts|goes|tr(?:y|ies)|answers|times)"
_ANSWER_NEVER = re.compile(
    r"\bnever\b[^.]{0,40}?\b(?:final )?(?:answers?|solutions?|values?)\b", re.IGNORECASE
)
_WORKED_AFTER = re.compile(
    r"\bworked (?:steps?|examples?|solutions?)\b[^.]{0,40}?\bafter (\w+) " + _TRIES,
    re.IGNORECASE,
)
_ANSWER_AFTER = re.compile(
    r"\b(?:final )?answers?\b[^.]{0,40}?\bafter (\w+) " + _TRIES, re.IGNORECASE
)
_NO_HINTS = re.compile(
    r"\bno hints\b|\bhints (?:are )?not allowed\b|\bwithout hints\b", re.IGNORECASE
)


def _count(word: str) -> int | None:
    return int(word) if word.isdigit() else _NUMBER.get(word.lower())


def from_teachers_words(rules: PolicyRules, text: str) -> PolicyRules:
    """`rules` with the teacher's plainest sentences in `text` taken literally."""
    updates: dict = {}
    m = _WORKED_AFTER.search(text)
    if m and (n := _count(m.group(1))) is not None:
        updates["partial_after_attempts"] = n
    if _ANSWER_NEVER.search(text):
        updates["full_answer_after_attempts"] = None
    else:
        m = _ANSWER_AFTER.search(text)
        if m and (n := _count(m.group(1))) is not None:
            updates["full_answer_after_attempts"] = n
    if _NO_HINTS.search(text):
        updates["hints_allowed"] = False
    return rules.model_copy(update=updates) if updates else rules
