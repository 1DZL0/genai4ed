"""The lesson brief: what the teacher and the class agent agree the lesson is.

The agent drafts it in conversation, the teacher approves it, and the agent
teaches from exactly that.
"""

import re

from pydantic import BaseModel, Field, ValidationInfo, model_validator

from app.agent.llm import FRESH
from app.agent.policy import PolicyRules
from app.enums import ActivityKind, StepKind

# The goal of a step, as Bloom's taxonomy, 1 to 6: the kind of thinking a student has to show,
# in any subject. Separate from the activity's shape (a right answer, or open-ended work).
BLOOM_WORDS = {
    1: "remember: recall a fact, a term, a bare answer",
    2: "understand: explain it in their own words, give an example, say what it means",
    3: "apply: use the method or the idea on a new case",
    4: "analyse: break it down, compare, find the pattern, use the evidence",
    5: "evaluate: judge it with reasons, weigh alternatives, defend a position",
    6: "create: make something new from it, an argument, a design, a piece of writing",
}
# The goal a step is held to when the teacher set none: understand.
BLOOM_DEFAULT = 2
# Kept for callers that still say depth; the scale is Bloom's now.
DOK_WORDS = BLOOM_WORDS
DOK_DEFAULT = BLOOM_DEFAULT

# How the activity's shape changes the teaching: told to the tutor beside the lesson.
ACTIVITY_WORDS = {
    ActivityKind.ANSWERS: (
        "right answers: each step has an answer the student works out; judge against it, "
        "help one notch at a time, and move on when it is met"
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
# Old briefs carried Webb's depth 1 to 4; a brief without this marker is read as one.
SCALE = "bloom"
_WEBB_TO_BLOOM = {1: 1, 2: 2, 3: 4, 4: 6}


class Step(BaseModel):
    """One part of the activity. The agent decides how to run it with each student."""

    name: str = Field(min_length=1, max_length=80, description="Its heading, a few words.")
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
            "each. Every step needs at least one before the lesson can be approved."
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
    target_dok: int | None = Field(
        default=None,
        ge=1,
        le=6,
        description=(
            "The goal for this step as a Bloom's level, 1 to 6, only when the teacher named one "
            "for this step; otherwise leave it empty and the lesson's goal (rules.depth) applies. "
            "1 remember; 2 understand; 3 apply; 4 analyse; 5 evaluate; 6 create."
        ),
    )
    activity: ActivityKind | None = Field(
        default=None,
        description=(
            "Only when this step's shape differs from the lesson's: answers (a right answer to "
            "work out) or open (open-ended writing judged against criteria). Otherwise empty."
        ),
    )

    def depth_in(self, rules: PolicyRules) -> int:
        """The Bloom's level this step is held to: its own if the teacher named one, else the
        lesson's. Still called depth in the code; the scale is Bloom's."""
        return self.target_dok or rules.depth


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
        description="A few words that fit a timetable, never 'New lesson'. Stable once set.",
    )
    subject: str = Field(
        default="",
        max_length=64,
        description=(
            "As the teacher said it, or filled in when their material makes it obvious (then "
            "name it in to_check); as stored unless they change it."
        ),
    )
    # The age of the students, not a year group: classes are named differently in every
    # country, an age means the same everywhere, and the tutor talks to that age.
    age: int | None = Field(
        default=None,
        ge=5,
        le=19,
        description=(
            "The students' age in years, as the teacher said it. Never worked out from a year "
            "group or a grade, which differ by country: ask instead. Empty until known."
        ),
    )
    activity: ActivityKind | None = Field(
        default=None,
        description=(
            "The shape of the work: answers (steps with a right answer) or open (open-ended "
            "writing: an essay, an argument, a design). From the teacher's words; filled in only "
            "when obvious, then named in to_check; otherwise asked for. Empty until known."
        ),
    )
    scale: str = Field(default=SCALE, description="Always 'bloom'.")
    # How long the lesson runs, from the teacher's words: never guessed, since the clock it
    # sets closes every pupil's box when it runs out.
    duration_minutes: int | None = Field(
        default=None,
        ge=5,
        le=240,
        description=(
            "How long the lesson runs, in minutes, as the teacher said it. Never guessed or "
            "taken from a default: ask. Empty until known."
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
    def _from_webb(cls, data, info: ValidationInfo):
        """A brief saved before Bloom's carried depth 1 to 4: read it onto the new scale. A
        brief the model has just written is on Bloom's already (validated with the context
        FRESH), whether or not it said so in "scale", and is never read across."""
        if not isinstance(data, dict) or data.get("scale") == SCALE:
            return data
        if (info.context or {}).get(FRESH):
            return {**data, "scale": SCALE}
        data = dict(data)
        rules = dict(data.get("rules") or {})
        if isinstance(rules.get("depth"), int):
            rules["depth"] = _WEBB_TO_BLOOM.get(rules["depth"], rules["depth"])
            data["rules"] = rules
        steps = []
        for step in data.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("target_dok"), int):
                level = _WEBB_TO_BLOOM.get(step["target_dok"], step["target_dok"])
                step = {**step, "target_dok": level}
            steps.append(step)
        if steps:
            data["steps"] = steps
        data.pop("year_group", None)
        data["scale"] = SCALE
        return data

    @property
    def planned_minutes(self) -> int:
        """The length a running lesson is timed to."""
        return self.duration_minutes or DURATION_DEFAULT

    def activity_of(self, index: int) -> ActivityKind | None:
        """The shape of one step: its own override, else the lesson's."""
        if 0 <= index < len(self.steps) and self.steps[index].activity:
            return self.steps[index].activity
        return self.activity

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
        if self.activity is None:
            gaps.append("what kind of activity it is: right answers, or open-ended writing")
        if not self.objectives:
            gaps.append("at least one learning objective")
        if not self.steps:
            gaps.append("at least one activity step")
        # A finish line per step: the tutor judges against it, and a student knows when they
        # are done. Lessons with a clear finish line reach the depth the teacher wanted more often.
        without = [str(n) for n, s in enumerate(self.steps, 1) if not s.success_criteria]
        if without:
            steps = "step " + without[0] if len(without) == 1 else "steps " + ", ".join(without)
            gaps.append(f"what counts as done for {steps}")
        return gaps


_ACTIVITY_SAID = re.compile(
    r"\bthe activity:\s*(right answers|open-ended writing)\b", re.IGNORECASE
)


def activity_from_words(text: str) -> ActivityKind | None:
    """The activity the teacher named outright, in the panel's own words; the last one wins."""
    found = _ACTIVITY_SAID.findall(text or "")
    if not found:
        return None
    return ActivityKind.ANSWERS if found[-1].lower() == "right answers" else ActivityKind.OPEN


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
