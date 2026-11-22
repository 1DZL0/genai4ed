"""The shape of one reply from the tutor, with every field described: the descriptions reach
the model inside the JSON schema, which is where a field's meaning belongs."""

from pydantic import BaseModel, Field, field_validator

from app import study
from app.enums import AgentMove, Disclosure, Judgment, PitchCall, PitchDial, Severity, SignalKind


class AssessmentOut(BaseModel):
    """How the student's attempt measures against the step's success criteria."""

    judgment: Judgment = Field(
        description=(
            "met, partial, not_met or unclear, against the success criteria. Never call a "
            "partly wrong answer met. Judge what the question on screen asks, in their own "
            "words: a finish line's quoted phrases, details and examples show what counts, not "
            "words they must repeat. 'it comes and sits and goes away' meets 'names the three "
            "actions in order: it comes in, it sits looking over harbor and city, it moves on'. "
            "Asking for more than the question did is never a reason for partial."
        )
    )
    criterion: str = Field(
        default="", max_length=300, description="The criterion you judged against, in a few words."
    )
    evidence_quote: str = Field(
        default="", max_length=600, description="Their exact words that show it."
    )
    misconception: str | None = Field(
        default=None,
        max_length=300,
        description="Only when their words show a specific wrong idea; say it in plain words.",
    )


class SignalOut(BaseModel):
    """Something you noticed about the student, as an observation."""

    kind: SignalKind = Field(
        description=(
            "struggling, misconception, manipulation_attempt, off_task, fast_progress, "
            "unresolved_question, wellbeing (the student may be unsafe or distressed), or "
            "asked_for_teacher (they ask for their teacher in words)."
        )
    )
    severity: Severity = Field(default=Severity.LOW, description="low, medium or high.")
    note: str = Field(
        default="",
        max_length=400,
        description="What you saw, in plain words, with their words where they matter.",
    )
    tell_teacher: bool = Field(
        default=False,
        description=(
            "True when the teacher should know now, going by the list under Allowed right "
            "now. Wellbeing where the student may be unsafe is always high and always true. "
            "This is your only way to reach the teacher."
        ),
    )


def kept_pitch(data: dict) -> dict | None:
    """The tutor's note on how it pitched a step, as kept with its message, for the teacher's
    and the research pages; None when it had nothing to say about it. Never for a student."""
    line, call, changed = data.get("pitch") or "", data.get("pitch_call"), data.get("pitch_changed")
    if not (line or call or changed):
        return None
    return {"line": line, "call": call, "changed": list(changed or [])}


class StudentTurnOut(BaseModel):
    """One reply to the student. They see only the message."""

    message: str = Field(
        min_length=1,
        max_length=2500,
        description="What the student reads, written as How to talk says.",
    )
    move: AgentMove = Field(
        description=(
            "What this reply does: ask, follow_up, clarify, challenge, hint, explain, example, "
            "simplify, harder, justify, revisit, advance, complete or decline. advance or "
            "complete only with a met assessment; complete only on the last step, because it "
            "ends the whole lesson; revisit only to send them back a step."
        )
    )
    student_attempted: bool = Field(
        default=False,
        description="True only when their message is an attempt at the current step.",
    )
    assessment: AssessmentOut | None = Field(
        default=None, description="When they attempted: the judgment, with their exact words."
    )
    disclosure: Disclosure = Field(
        default=Disclosure.NONE,
        description=(
            "Honestly, how much of this step's answer your reply gives away: none, hint, "
            "partial or full. A worked example of a similar problem, or one step of this one "
            "done for them, counts as partial; the full answer or a complete solution counts "
            "as full."
        ),
    )
    task: str | None = Field(
        default=None,
        max_length=1200,
        description=(
            "The question your message actually asked, so it stays on screen; on a reply that "
            "moves them on, the next step's first question. Null when you asked nothing, and "
            "the last one stays on screen."
        ),
    )
    step_done: bool = Field(
        default=False,
        description=(
            "True only with a met assessment, when you are moving them to the next step and "
            "asking its first question in this same reply; the platform moves them when you "
            "set it. A step with several questions is done when each has been asked and met. "
            "On the last step a met answer ends the lesson whatever you set, so close it in "
            "that same reply."
        ),
    )
    rung: str | None = Field(
        default=None,
        max_length=40,
        description="On a help ladder, the rung this reply is; otherwise null.",
    )
    pitch: str = Field(
        default="",
        max_length=300,
        description=(
            'Only when the prompt has "Pitching each step for this student": one line the '
            "student never sees, on what you changed about how you asked and why, or "
            '"as written" and why. Otherwise leave it empty.'
        ),
    )
    pitch_call: PitchCall | None = Field(
        default=None,
        description=(
            'Only with "Pitching each step for this student": your call on the question this '
            'reply asks. "as written": the step as the lesson has it, when you have not asked '
            'your own version of it. "stretched": you ask your own version, which asks more of '
            'them. "more support": your version gives more help up front than the step as '
            "written, for a student finding it hard; never help towards a version you already "
            'asked. "stayed": they have not met your harder version yet and you are still on '
            "it, whether by explaining it another way, narrowing it, or helping them into it "
            'with a support. "let go": you go back to the step as written after asking your '
            'version; use "let go" for that reply, not "as written". Otherwise null.'
        ),
    )
    pitch_changed: list[PitchDial] = Field(
        default_factory=list,
        max_length=len(PitchDial),
        description=(
            'Only with "Pitching each step for this student": the things listed there that you '
            "changed in the question this reply asks; empty when you ask it as written."
        ),
    )
    signals: list[SignalOut] = Field(
        default_factory=list,
        max_length=6,
        description="What you noticed, as observations; empty when nothing stood out.",
    )

    @field_validator("rung", mode="before")
    @classmethod
    def _known_rung(cls, value):
        return value if value in study.LADDER else None

    # A label the tutor made up is dropped, not a broken reply: these are for counting, and the
    # student's turn must not be redrafted over them.
    @field_validator("pitch_call", mode="before")
    @classmethod
    def _known_call(cls, value):
        return value if value in PitchCall else None

    @field_validator("pitch_changed", mode="before")
    @classmethod
    def _known_things(cls, value):
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(v for v in value if v in PitchDial))
