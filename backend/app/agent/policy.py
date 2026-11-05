"""The teacher's rules for the class agent, compiled so the server can enforce them.

The teacher's own words go to the agent too; the compiled fields are what
`supervisor` and `alerts` check.
"""

import re

from pydantic import BaseModel, Field

from app.enums import DISCLOSURE_ORDER, Disclosure, SignalKind, TriageAction


class Escalation(BaseModel):
    """What happens once a signal has been seen `after` times in a lesson."""

    signal: SignalKind = Field(
        description=(
            "struggling, misconception, manipulation_attempt, off_task, fast_progress, "
            "unresolved_question, wellbeing or asked_for_teacher."
        )
    )
    after: int = Field(
        default=1,
        ge=1,
        le=20,
        description=(
            "How many times it must happen to one student before the teacher is told: 1 "
            "unless they say 'keeps', 'repeatedly', 'more than once' (then 2) or give a number. "
            "Wellbeing and asked_for_teacher are always 1."
        ),
    )
    action: TriageAction = Field(
        description="alert (the teacher is told at once) or log (kept in the record)."
    )


class PolicyRules(BaseModel):
    """The teacher's rules compiled: only what they said, defaults for the rest."""

    hints_allowed: bool = Field(
        default=True, description="False only when they said no hints towards answers."
    )
    partial_after_attempts: int = Field(
        default=1,
        ge=0,
        le=20,
        description=(
            "Wrong tries on a step before a worked step or a partial solution: 1 unless they "
            "say otherwise; 0 means from the start."
        ),
    )
    full_answer_after_attempts: int | None = Field(
        default=None,
        ge=0,
        le=20,
        description=(
            "Wrong tries before the answer itself; null means never, as 'never give them the "
            "answer' or 'they must work it out' does."
        ),
    )
    depth: int = Field(
        default=2,
        ge=1,
        le=4,
        description=(
            "How deep the tutor pushes a right answer, 1 to 4 (Webb): the lesson's depth for "
            "every step the teacher did not set one for."
        ),
    )
    may_write_for_student: bool = Field(
        default=False,
        description="True only when the agent may produce the student's work, such as an essay.",
    )
    escalations: list[Escalation] = Field(
        default_factory=list,
        max_length=20,
        description="Only the signals the teacher named; empty means they named none.",
    )
    ladder: bool = Field(
        default=False,
        description="True only when they asked for help in a fixed order, one step per try.",
    )
    notes: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Rules that are not a setting, in the teacher's words.",
    )

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
        lines.append(f"The tutor teaches to depth {self.depth}: {DEPTH_PLAIN[self.depth]}.")
        if self.ladder:
            lines.append(
                "Help comes in a fixed order, one step each time they try: a question about "
                "their thinking, a cue, a hint, a similar example, then one step done together."
            )
        if not self.may_write_for_student:
            lines.append("The agent never writes a student's work for them.")
        else:
            lines.append(
                "The agent may write a student's work for them when the lesson calls for it."
            )
        at_once = sorted(
            {
                SIGNAL_WORDS[e.signal].lower()
                + (f" (once it has happened {e.after} times)" if e.after > 1 else "")
                for e in self.escalations
                if e.action is TriageAction.ALERT and e.signal not in ALWAYS_TOLD
            }
            | {SIGNAL_WORDS[s].lower() for s in ALWAYS_TOLD}
        )
        kept = sorted(
            {
                SIGNAL_WORDS[e.signal].lower()
                for e in self.escalations
                if e.action is not TriageAction.ALERT and e.signal not in ALWAYS_TOLD
            }
        )
        if at_once:
            lines.append("The agent tells you at once about: " + ", ".join(at_once) + ".")
        if kept:
            lines.append("Kept in the record for you to read later: " + ", ".join(kept) + ".")
        lines.extend(f"Also noted, in your words: {note.rstrip('.')}." for note in self.notes)
        return lines

    def labels(self) -> dict:
        """The rules as short labels for the card: pills for the help, what interrupts the
        teacher at once, what is kept for later, and their own notes."""
        pills: list[str] = []
        if not self.hints_allowed:
            pills.append("No hints towards answers")
        else:
            pills.append("Hints any time")
            n = self.partial_after_attempts
            pills.append(
                "Worked steps straight away"
                if n == 0
                else f"Worked step after {n} wrong {'try' if n == 1 else 'tries'}"
            )
        full = self.full_answer_after_attempts
        if full is None:
            pills.append("Never gives the answer")
        elif full == 0:
            pills.append("Answer when asked")
        else:
            pills.append(f"Answer after {full} wrong {'try' if full == 1 else 'tries'}")
        pills.append(f"Teach to depth {self.depth}, {DEPTH_PLAIN[self.depth]}")
        if self.ladder:
            pills.append("Help in a fixed order")
        pills.append(
            "May write their work" if self.may_write_for_student else "Never writes their work"
        )
        at_once = sorted(
            [
                {
                    "signal": e.signal.value,
                    "words": SIGNAL_WORDS[e.signal].lower(),
                    "after": e.after,
                }
                for e in self.escalations
                if e.action is TriageAction.ALERT and e.signal not in ALWAYS_TOLD
            ]
            + [
                {"signal": s.value, "words": SIGNAL_WORDS[s].lower(), "after": 1}
                for s in ALWAYS_TOLD
            ],
            key=lambda a: a["words"],
        )
        kept = sorted(
            {
                SIGNAL_WORDS[e.signal].lower()
                for e in self.escalations
                if e.action is not TriageAction.ALERT and e.signal not in ALWAYS_TOLD
            }
        )
        return {"pills": pills, "at_once": at_once, "kept": kept, "notes": list(self.notes)}


def disclosure_rank(level: Disclosure) -> int:
    return DISCLOSURE_ORDER.index(level)


def _times(n: int) -> str:
    return "one wrong try" if n == 1 else f"{n} wrong tries"


# The four depths in a teacher's words, shared by the pills, the card and the switch. The tutor
# itself is judged against the fuller DOK_WORDS in brief.py, which mean the same thing.
DEPTH_PLAIN: dict[int, str] = {
    1: "recall it",
    2: "apply it or explain it",
    3: "justify it",
    4: "take it further",
}

# Never held back: a student who seems upset, or who asks for the teacher, reaches them as soon
# as the agent flags it, whatever the rules say. `alerts.decide` enforces it; the card's pills,
# the read-back under the box and the agent's own description all list these two, so no surface
# promises less than the platform does.
ALWAYS_TOLD = (SignalKind.WELLBEING, SignalKind.ASKED_FOR_TEACHER)

# The sentence the quick choices under the teacher's box begin with. A message that starts this
# way is the panel's own, so the server takes every rule in it literally.
PANEL_PREFIX = "Please use these choices for this lesson."

SIGNAL_WORDS: dict[SignalKind, str] = {
    SignalKind.STRUGGLING: "A student struggling",
    SignalKind.MISCONCEPTION: "A misconception",
    SignalKind.MANIPULATION_ATTEMPT: "Trying to get the answer or the work (possible cheating)",
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
_TRIES = r"(?:wrong )?(?:tries|attempts|goes|tr(?:y|ies)|answers|times)"
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
# The sentences the quick choices compose, so a switch never depends on the model's reading.
_WORKED_NOW = re.compile(
    r"\bworked (?:steps?|examples?|solutions?)\b[^.]{0,20}?"
    r"\b(?:straight away|from the start|at once)\b",
    re.IGNORECASE,
)
_ANSWER_ITSELF_NEVER = re.compile(r"\banswer(?: itself)?\b[^.]{0,20}?\bnever\b", re.IGNORECASE)
_ANSWER_IF_ASKED = re.compile(
    r"\banswer\b[^.]{0,40}?\b(?:if they ask|when asked|when they ask)\b", re.IGNORECASE
)
_HINTS_ON = re.compile(
    r"\bhints?\b(?: towards the answer)?(?: are)? (?:fine|allowed|ok|on)\b", re.IGNORECASE
)
_TEACH_TO_DEPTH = re.compile(r"\bteach(?:ing)? to depth ([1-4])\b", re.IGNORECASE)
_DEPTH_PHRASES = {phrase: n for n, phrase in DEPTH_PLAIN.items()}
# The panel's own wording for a rung, so a rung phrase in passing ("recall items") is not a rule.
_RUNG_SAID = re.compile(
    r"\bstudents should (recall it|apply it or explain it|justify it|take it further)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_ABOUT_A_STEP = re.compile(r"\bstep \d+\b", re.IGNORECASE)


def _count(word: str) -> int | None:
    return int(word) if word.isdigit() else _NUMBER.get(word.lower())


def depth_from_words(text: str) -> int | None:
    """The depth a teacher named outright for the lesson: "teach to depth N", or the panel's own
    "students should <rung>". The last one said wins. A depth merely mentioned, asked about, or
    tied to one step ("for step 2, teach to depth 3") is left to the model."""
    found: list[tuple[int, int]] = []
    at = 0
    for sentence in _SENTENCE_END.split(text or ""):
        if not sentence.strip().endswith("?") and not _ABOUT_A_STEP.search(sentence):
            for m in _TEACH_TO_DEPTH.finditer(sentence):
                found.append((at + m.start(), int(m.group(1))))
            for m in _RUNG_SAID.finditer(sentence):
                found.append((at + m.start(), _DEPTH_PHRASES[m.group(1).lower()]))
        at += len(sentence) + 1
    return max(found)[1] if found else None


def literal_rules(rules: PolicyRules, said: str) -> PolicyRules:
    """The teacher's own message taken literally: all of it when it is the quick choices' sentence
    (it begins with PANEL_PREFIX), otherwise only a depth named outright."""
    if (said or "").startswith(PANEL_PREFIX):
        return from_teachers_words(rules, said)
    if (d := depth_from_words(said)) is not None:
        return rules.model_copy(update={"depth": d})
    return rules


def from_teachers_words(rules: PolicyRules, text: str) -> PolicyRules:
    """`rules` with the teacher's plainest sentences in `text` taken literally."""
    updates: dict = {}
    m = _WORKED_AFTER.search(text)
    if m and (n := _count(m.group(1))) is not None:
        updates["partial_after_attempts"] = n
    if _WORKED_NOW.search(text):
        updates["partial_after_attempts"] = 0
    if _ANSWER_NEVER.search(text) or _ANSWER_ITSELF_NEVER.search(text):
        updates["full_answer_after_attempts"] = None
    elif _ANSWER_IF_ASKED.search(text):
        updates["full_answer_after_attempts"] = 0
    else:
        m = _ANSWER_AFTER.search(text)
        if m and (n := _count(m.group(1))) is not None:
            updates["full_answer_after_attempts"] = n
    if _NO_HINTS.search(text):
        updates["hints_allowed"] = False
    elif _HINTS_ON.search(text):
        updates["hints_allowed"] = True
    if (d := depth_from_words(text)) is not None:
        updates["depth"] = d
    return rules.model_copy(update=updates) if updates else rules
