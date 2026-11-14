"""The lesson brief: what the teacher and the class agent agree the lesson is.

The agent drafts it in conversation, the teacher approves it, and the agent
teaches from exactly that.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.agent import activities
from app.agent.llm import FRESH
from app.agent.policy import PolicyRules
from app.enums import ActivityKind, StepKind

# How the activity's shape changes the teaching: told to the tutor beside the lesson.
ACTIVITY_WORDS = {
    ActivityKind.ANSWERS: (
        "work with right answers: each step has an answer the student works out; judge "
        "against it, help one notch at a time, and move on when it is met"
    ),
    ActivityKind.OPEN: (
        "open-ended work: an essay, an argument, a design, a piece of writing with no single "
        "answer; judge the student's draft against the finish line's criteria, coach it (what "
        "to add, cut or sharpen) without writing it for them, and treat a submitted piece that "
        "meets the criteria as done"
    ),
}
ACTIVITY_PLAIN = {ActivityKind.ANSWERS: "right answers", ActivityKind.OPEN: "open-ended writing"}
# The clock a lesson runs to when its brief has no length, which only an old saved brief can
# lack: a brief without one cannot be approved.
DURATION_DEFAULT = 30

# The headings a lesson can carry, as the keys the agent writes; empty until one is known.
_HEADING_KEYS = [h.key for h in activities.PICKS]
_HEADING_ENUM = {"enum": ["", *_HEADING_KEYS]}
_HEADING_WORDS = "; ".join(f"{h.key} ({h.label})" for h in activities.PICKS)


def _heading_key(value) -> str:
    """A heading as its key, whether the agent wrote the key or the label. Anything else that
    is not empty is none of the seven, which is "Something else", never an eighth heading."""
    said = " ".join(str(value or "").lower().split())
    if not said:
        return ""
    for h in activities.PICKS:
        if said in (h.key, h.label.lower()):
            return h.key
    return activities.OTHER.key


def _listed(listed_kind: str, activity_kind: str) -> str:
    """The list's own name for a kind, or nothing when the kind is not on the list. Naming the
    kind by the list's name is enough to put it there."""
    found = activities.find_kind(listed_kind) or activities.find_kind(activity_kind)
    return found[1].name if found else ""


class ActivityRecord(BaseModel):
    """What the server knows about how a lesson came by its activity, kept for the research.

    The server writes it from what was pressed and what changed. The agent is never shown it
    and cannot write it: it is left out of the reply shape, and dropped from a reply that
    sends one."""

    # The headings the teacher pressed, by key. A press is a fact, whatever the agent then
    # read the teacher's words as.
    picked: list[str] = Field(default_factory=list, max_length=len(_HEADING_KEYS))
    # When they pressed: with the message that began the lesson, in the chat after the agent
    # asked, or later in place of a heading the lesson already had. Empty when never.
    picked_when: Literal["", "before", "asked", "later"] = ""
    # What the teacher did with the agent's guess at the kind: nothing yet, kept it by saying
    # so, kept it by carrying on without a word, or corrected it. Empty when there was no guess.
    guess: Literal["", "standing", "kept_said", "kept_silent", "corrected"] = ""
    # The teacher's own words when they corrected it.
    correction: str = Field(default="", max_length=600)
    # The sentence the agent said its guess in, when it said one.
    said: str = Field(default="", max_length=400)

    @field_validator("picked")
    @classmethod
    def _only_headings(cls, value: list[str]) -> list[str]:
        unknown = [key for key in value if key not in _HEADING_KEYS]
        if unknown:
            raise ValueError(f"not a heading: {', '.join(unknown)}")
        return value


class Step(BaseModel):
    """One part of the activity. The agent decides how to run it with each student."""

    name: str = Field(
        min_length=1, max_length=80, description="What the step is called, a few words."
    )
    kind: StepKind = Field(
        description="explain (the agent explains, then checks), question, practice or check."
    )
    goal: str = Field(min_length=1, max_length=600, description="What the step is for.")
    prompt_ideas: list[str] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "The actual questions, with the actual numbers or texts, never a description of "
            "one. The agent asks them in order."
        ),
    )
    success_criteria: list[str] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "The finish line: what a student has to show to have done this step, a sentence "
            "each. Every step needs at least one before the lesson can be approved. The "
            "teacher's own finish lines stay as they wrote them. One you write asks for what "
            "the step's questions ask and no more: 'Solve 2x + 3 = 11' is done at x = 4, "
            "'What is half of 24?' at 12. Never add a method, an explanation, a check or "
            "working the questions do not ask for: the tutor asks for the why after a right "
            "answer by itself, as the goal says, and a pupil with the asked-for answer must "
            "not be held on the step for more."
        ),
    )
    reference_answer: str | None = Field(
        default=None,
        max_length=2000,
        description=(
            "Only where the step has one definite answer (a value, a word, a fact), for "
            "judging; never a method, which could then not be taught. Students never see it."
        ),
    )
    activity: ActivityKind | None = Field(
        default=None,
        description=(
            "Only when this step's shape differs from the lesson's: answers or open. Otherwise "
            "empty."
        ),
    )
    heading: str = Field(
        default="",
        max_length=32,
        description=(
            "Only when this step is a different kind of activity from the lesson's: its "
            "activity heading, written as the lesson's is. Otherwise empty."
        ),
        json_schema_extra=_HEADING_ENUM,
    )
    activity_kind: str = Field(
        default="",
        max_length=160,
        description="Only with a heading of its own: the exact kind, as the lesson's is written.",
    )
    listed_kind: str = Field(
        default="",
        max_length=80,
        description="Only with a heading of its own: the list's name for it, as the lesson's.",
    )

    @field_validator("heading", mode="before")
    @classmethod
    def _heading_as_its_key(cls, value) -> str:
        return _heading_key(value)

    @model_validator(mode="after")
    def _kind_in_the_lists_words(self):
        self.listed_kind = _listed(self.listed_kind, self.activity_kind)
        return self


class Criterion(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="What is marked, in a word or two.")
    max: int = Field(ge=1, le=20, description="The points it is out of.")
    description: str = Field(default="", max_length=400, description="One line on what earns them.")


# The most the teacher's rules in their own words may hold; anything that rewrites them must
# stay within it, or the lesson can no longer be read.
RULES_TEXT_MAX = 3000


class LessonBrief(BaseModel):
    """The lesson as the teacher and the agent have it. Returned whole whenever it changes."""

    title: str = Field(
        default="",
        max_length=255,
        description=(
            "A few words that fit a timetable, never 'New lesson'. Theirs word for word when "
            "they gave one; stable once set."
        ),
    )
    subject: str = Field(
        default="",
        max_length=64,
        description=(
            "As the teacher said it, or worked out from their words or material and named in "
            "to_check; as stored unless they change it."
        ),
    )
    # The age of the students, not a year group: classes are named differently in every
    # country, an age means the same everywhere, and the tutor talks to that age.
    age: int | None = Field(
        default=None,
        ge=5,
        le=19,
        description=("The students' age in years, from the teacher's words. Empty until known."),
    )
    activity: ActivityKind | None = Field(
        default=None,
        description=(
            "The shape of the work: answers (a right answer to work out) or open (judged "
            "against criteria). Never asked: see Building the lesson."
        ),
    )
    heading: str = Field(
        default="",
        max_length=32,
        description=("The activity heading, as one of: " + _HEADING_WORDS + ". Empty until known."),
        json_schema_extra=_HEADING_ENUM,
    )
    activity_kind: str = Field(
        default="",
        max_length=160,
        description=(
            "The exact kind of activity in plain words, as you say it to the teacher. Empty "
            "until known."
        ),
    )
    listed_kind: str = Field(
        default="",
        max_length=80,
        description=(
            "The list's own name for that kind, word for word, when it is one of the kinds "
            "under the heading. Empty when none of them fits."
        ),
    )
    # The server's own record of what was pressed and what the teacher did with the guess.
    # Left out of the shape the agent is given, and never taken from the agent.
    record: SkipJsonSchema[ActivityRecord] = Field(default_factory=ActivityRecord)
    # How long the lesson runs, from the teacher's words: never guessed, since the clock it
    # sets closes every pupil's box when it runs out.
    duration_minutes: int | None = Field(
        default=None,
        ge=5,
        le=240,
        description=(
            "How long the lesson runs, in minutes, from the teacher's words. Empty until known."
        ),
    )
    prior_knowledge: str = Field(
        default="", max_length=1000, description="What the students already know, in a line."
    )
    objectives: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="What they should be able to do by the end, in plain words.",
    )
    strategy: str = Field(
        default="",
        max_length=2000,
        description=(
            "How the teacher wants it taught: level, tone, emphasis, use of prior knowledge, "
            "how much explaining before questions. Their words where they gave them."
        ),
    )
    steps: list[Step] = Field(
        default_factory=list,
        max_length=12,
        description="The teacher's steps, in their order, never restructured unless they ask.",
    )
    assessment: list[Criterion] = Field(
        default_factory=list,
        max_length=8,
        description="Only when the work is marked: the criteria the agent suggests points against.",
    )
    rules_text: str = Field(
        default="",
        max_length=RULES_TEXT_MAX,
        description=(
            "The teacher's own sentences about help and conduct, kept as they said them. They "
            "win over the compiled numbers, so make the two agree."
        ),
    )
    rules: PolicyRules = Field(
        default_factory=PolicyRules,
        description="The same rules compiled, which the platform enforces.",
    )
    topics: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="One to four short lowercase tags that connect the lesson to earlier work.",
    )
    key_terms: list[str] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "Words the teacher wants used and heard back, such as 'coefficient' or "
            "'subordinate clause'. Empty when they gave none."
        ),
    )
    support: str = Field(
        default="",
        max_length=600,
        description=(
            "How to adjust for this class: plain words, shorter lines, the key terms in another "
            "language as well. Blank when the teacher said nothing about it."
        ),
    )
    to_check: list[str] = Field(
        default_factory=list,
        max_length=24,
        description=(
            "The parts you filled in yourself rather than from the teacher's words, named so "
            "the card marks them for checking: 'objectives', 'step 2 criteria', 'rules'. Keep "
            "each until the teacher has confirmed it; approval clears them all."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _record_is_the_servers(cls, data, info: ValidationInfo):
        """A brief the model has just written carries no record: only the server writes one."""
        if isinstance(data, dict) and "record" in data and (info.context or {}).get(FRESH):
            return {k: v for k, v in data.items() if k != "record"}
        return data

    @field_validator("heading", mode="before")
    @classmethod
    def _heading_as_its_key(cls, value) -> str:
        return _heading_key(value)

    @model_validator(mode="after")
    def _kind_in_the_lists_words(self):
        self.listed_kind = _listed(self.listed_kind, self.activity_kind)
        return self

    @model_validator(mode="after")
    def _shape_from_the_kind(self):
        """A kind on the list has the shape the list gives it, whatever the agent read it as.
        This is what replaced asking the teacher "right answers, or open-ended writing"."""
        if found := activities.find_kind(self.listed_kind):
            self.activity = found[1].shape
        for step in self.steps:
            if step.heading and (found := activities.find_kind(step.listed_kind)):
                step.activity = found[1].shape
        return self

    @property
    def planned_minutes(self) -> int:
        """The length a running lesson is timed to."""
        return self.duration_minutes or DURATION_DEFAULT

    def activity_of(self, index: int) -> ActivityKind | None:
        """The shape of one step: its own override, else the lesson's."""
        if 0 <= index < len(self.steps) and self.steps[index].activity:
            return self.steps[index].activity
        return self.activity

    def _own(self, index: int) -> Step | None:
        """The step, when it is a different kind of activity from the lesson's."""
        if 0 <= index < len(self.steps) and self.steps[index].heading:
            return self.steps[index]
        return None

    def heading_of(self, index: int) -> str:
        """The heading of one step: its own, else the lesson's."""
        step = self._own(index)
        return step.heading if step else self.heading

    def kind_of(self, index: int) -> tuple[str, str]:
        """The exact kind of one step and the list's name for it: its own, else the lesson's."""
        step = self._own(index)
        if step:
            return step.activity_kind, step.listed_kind
        return self.activity_kind, self.listed_kind

    def headings(self) -> list[str]:
        """Every heading in the lesson, the lesson's own first, each once."""
        found = [self.heading, *(s.heading for s in self.steps)]
        return list(dict.fromkeys(h for h in found if h))

    @property
    def heading_from(self) -> str:
        """Where the lesson's heading came from: the teacher pressed it before typing, pressed
        it in the chat, or the agent worked it out. Empty when the lesson has none."""
        if not self.heading:
            return ""
        if self.heading not in self.record.picked:
            return "worked_out"
        return "picked_before" if self.record.picked_when == "before" else "picked_in_chat"

    def guessed(self) -> tuple[str, str]:
        """What of the lesson's activity is the agent's guess: a heading it worked out rather
        than one the teacher pressed, and the exact kind, which only the agent ever names."""
        heading = self.heading if self.heading_from == "worked_out" else ""
        kind = " ".join((self.activity_kind.strip() or self.listed_kind).lower().split())
        return heading, kind

    @property
    def guessing(self) -> bool:
        """Whether the activity is still the agent's guess: not yet kept, corrected or approved.
        A lesson from before the guess was recorded is a guess while it has one."""
        if self.record.guess:
            return self.record.guess == "standing"
        return any(self.guessed())

    @property
    def kind_from(self) -> str:
        """Where the exact kind came from: the teacher's correction, the list, or the agent's
        own words for a kind that is not on the list. Empty when the lesson has none."""
        if not (self.activity_kind or self.listed_kind):
            return ""
        if self.record.guess == "corrected":
            return "teacher"
        return "list" if self.listed_kind else "own_words"

    def for_agent(self) -> str:
        """The lesson as the agent is shown it: everything but the server's own record."""
        return self.model_dump_json(exclude={"record"})

    def as_text(self) -> str:
        """The lesson in plain words, as the teacher left it and with nothing added."""
        about = ", ".join(
            x
            for x in (
                self.subject,
                f"age {self.age}" if self.age else "",
                ACTIVITY_PLAIN[self.activity] if self.activity else "",
                f"{self.duration_minutes} minutes" if self.duration_minutes else "",
            )
            if x
        )
        lines = [self.title or "Lesson", about]
        if self.prior_knowledge:
            lines.append(f"What the students already know: {self.prior_knowledge}")
        if self.objectives:
            lines += ["Objectives:", *(f"- {o}" for o in self.objectives)]
        if self.strategy:
            lines.append(f"How to teach it: {self.strategy}")
        for number, step in enumerate(self.steps, 1):
            lines.append(f"Step {number}: {step.name} ({step.kind.value}). {step.goal}")
            lines += [f"- Question: {p}" for p in step.prompt_ideas]
            lines += [f"- Looking for: {c}" for c in step.success_criteria]
            if step.reference_answer:
                lines.append(f"- Answer: {step.reference_answer}")
        if self.assessment:
            lines += ["Assessed on:", *(f"- {c.name} (out of {c.max})" for c in self.assessment)]
        if self.rules_text.strip():
            lines.append(f"The teacher's rules: {self.rules_text.strip()}")
        return "\n".join(lines)

    def missing(self) -> list[str]:
        """What still has to be settled before the lesson can be approved."""
        gaps: list[str] = []
        if not self.title.strip():
            gaps.append("a title")
        if not self.subject.strip():
            gaps.append("the subject")
        if self.age is None:
            gaps.append("the students' age")
        if self.duration_minutes is None:
            gaps.append("how long the lesson is")
        if not self.objectives:
            gaps.append("at least one learning objective")
        if not self.steps:
            gaps.append("at least one activity step")
        # A finish line per step: the tutor judges against it, and a student knows when they
        # are done. Lessons with a clear finish line reach what the teacher wanted more often.
        without = [str(n) for n, s in enumerate(self.steps, 1) if not s.success_criteria]
        if without:
            steps = "step " + without[0] if len(without) == 1 else "steps " + ", ".join(without)
            gaps.append(f"what counts as done for {steps}")
        return gaps


# "13 year olds", "aged 13", "age 13", "13-year-old". Never a year group or a grade: those are
# named differently in every country, so they are left for the agent to ask about.
_AGE_SAID = re.compile(r"\b(\d{1,2})[ -]?year[ -]?olds?\b|\bage(?:d)?\s+(\d{1,2})\b", re.IGNORECASE)


def age_from_words(text: str) -> int | None:
    """The students' age a teacher said, as a number of years, or None when they did not."""
    for m in _AGE_SAID.finditer(text or ""):
        age = int(m.group(1) or m.group(2))
        if 5 <= age <= 19:
            return age
    return None


# Words that make the shape of the work plain enough to guess.
_OPEN_WORDS = (
    "essay",
    "paragraph",
    "write a",
    "writing",
    "story",
    "argue",
    "argument",
    "debate",
    "design",
    "poem",
    "letter",
    "speech",
    "report on",
    "reflect",
)
_ANSWER_WORDS = (
    "equation",
    "solve",
    "calculate",
    "answer",
    "quiz",
    "dates",
    "fractions",
    "percent",
    "formula",
    "spelling",
    "vocabulary",
    "times table",
    "recall",
)


def activity_guess(text: str) -> ActivityKind | None:
    """A guess at the shape of the work from plain words, or None when the words do not say.
    Whoever uses it says so to the teacher and marks it to check."""
    lowered = (text or "").lower()
    open_said = any(w in lowered for w in _OPEN_WORDS)
    answers_said = any(w in lowered for w in _ANSWER_WORDS)
    if open_said == answers_said:
        return None
    return ActivityKind.OPEN if open_said else ActivityKind.ANSWERS
