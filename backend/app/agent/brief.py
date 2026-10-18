"""The lesson brief: what the teacher and the class agent agree the lesson is.

The agent drafts it in conversation, the teacher approves it, and the agent
teaches from exactly that.
"""

from pydantic import BaseModel, Field

from app.agent.policy import PolicyRules
from app.enums import StepKind


class Step(BaseModel):
    """One part of the activity. The agent decides how to run it with each student."""

    name: str = Field(min_length=1, max_length=80)
    kind: StepKind
    goal: str = Field(min_length=1, max_length=600)
    # Ways in the agent may use: a question, a scenario, a problem.
    prompt_ideas: list[str] = Field(default_factory=list, max_length=8)
    # What a student has to show to have done this step.
    success_criteria: list[str] = Field(default_factory=list, max_length=8)
    # For the agent's judging and the server's checks only; never shown to a student.
    reference_answer: str | None = Field(default=None, max_length=2000)


class Criterion(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    max: int = Field(ge=1, le=20)
    description: str = Field(default="", max_length=400)


class LessonBrief(BaseModel):
    title: str = Field(default="", max_length=255)
    subject: str = Field(default="", max_length=64)
    year_group: str = Field(default="", max_length=64)
    duration_minutes: int = Field(default=30, ge=5, le=240)
    prior_knowledge: str = Field(default="", max_length=1000)
    objectives: list[str] = Field(default_factory=list, max_length=10)
    # How the agent should teach: order, tone, level, what to emphasise.
    strategy: str = Field(default="", max_length=2000)
    steps: list[Step] = Field(default_factory=list, max_length=12)
    assessment: list[Criterion] = Field(default_factory=list, max_length=8)
    # The teacher's rules in their own words, and compiled for enforcement.
    rules_text: str = Field(default="", max_length=3000)
    rules: PolicyRules = Field(default_factory=PolicyRules)
    # Short tags that connect this lesson to a student's earlier work.
    topics: list[str] = Field(default_factory=list, max_length=10)

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
        return gaps
