"""The lesson brief: what the teacher and the class agent agree the lesson is.

The agent drafts it in conversation, the teacher approves it, and the agent
teaches from exactly that.
"""

from pydantic import BaseModel, Field

from app.agent.policy import PolicyRules
from app.enums import StepKind

# Depth of knowledge, 1 to 4 (Webb): the kind of thinking a step asks for, in any subject.
DOK_WORDS = {
    1: "recall, or a bare answer",
    2: "apply a method, or explain a concept",
    3: "justify, compare approaches, or use evidence",
    4: "sustained reasoning across several parts or sources",
}
# The target a step is held to when the teacher set none: apply or explain.
DOK_DEFAULT = 2


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
        le=4,
        description=(
            "The depth of thinking the teacher wants the student to show on this step, 1 to 4: "
            "1 recall or a bare answer; 2 apply a method or explain a concept; 3 justify, "
            "compare approaches or use evidence; 4 sustained reasoning across several parts or "
            "sources. Set it from the goal, with later steps at least as deep as earlier ones."
        ),
    )

    @property
    def depth(self) -> int:
        return self.target_dok or DOK_DEFAULT


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
        default="", max_length=64, description="As stored unless the teacher changes it."
    )
    year_group: str = Field(default="", max_length=64)
    duration_minutes: int = Field(default=30, ge=5, le=240)
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
            "the card marks them for checking: 'objectives', 'step 2 criteria', 'depth "
            "targets', 'rules'. Keep each until the teacher has confirmed it; approval clears "
            "them all."
        ),
    )

    def as_text(self) -> str:
        """The lesson in plain words, as the teacher left it and with nothing added."""
        about = ", ".join(
            x for x in (self.subject, self.year_group, f"{self.duration_minutes} minutes") if x
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
