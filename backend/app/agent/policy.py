"""The teacher's rules for the class agent, in a form the server can enforce.

A teacher says what they want in their own words ("hints are fine, but no
final answer until they've tried twice; flag anyone who keeps trying to get
it to do the work"). The agent compiles that into `PolicyRules`, the teacher
sees it read back in plain language, and only then does it apply.

The words go to the agent too, so the spirit of a rule guides how it teaches.
The compiled fields are what `supervisor` and `triage` check, so the letter of
a rule doesn't depend on the model remembering it.
"""

from pydantic import BaseModel, Field

from app.enums import DISCLOSURE_ORDER, Disclosure, SignalKind, TriageAction


class Escalation(BaseModel):
    """What happens once a signal has been seen `after` times in a lesson."""

    signal: SignalKind
    after: int = Field(default=1, ge=1, le=20)
    action: TriageAction


class PolicyRules(BaseModel):
    # Hints towards the answer to the current step.
    hints_allowed: bool = True
    # Partial solutions and worked steps, after this many answers on a step.
    partial_after_attempts: int = Field(default=1, ge=0, le=20)
    # The final answer, after this many answers on a step. None: never.
    full_answer_after_attempts: int | None = Field(default=None, ge=0, le=20)
    # Whether the agent may produce the student's work for them (an essay,
    # a paragraph, a finished solution) rather than help them make it.
    may_write_for_student: bool = False
    escalations: list[Escalation] = Field(default_factory=list, max_length=20)
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
        if not self.may_write_for_student:
            lines.append("The agent never writes a student's work for them.")
        for e in self.escalations:
            lines.append(
                f"{SIGNAL_WORDS[e.signal]}: {ACTION_WORDS[e.action]}"
                + (f" after {e.after} times." if e.after > 1 else ".")
            )
        lines.extend(self.notes)
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
