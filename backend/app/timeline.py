"""A lesson's phases.

The concept note: "AI work should occur in bounded intervals followed by
teacher-led explanation, peer discussion, or class synthesis." A plan's
timeline makes that enforceable - each phase says whether students' tutors are
on - and the server, not the page, decides whether a student may use theirs.
"""

from pydantic import BaseModel, Field, field_validator

DEFAULT_TIMELINE: list[dict] = [
    {"name": "Explanation", "minutes": 10, "tutors_on": False},
    {"name": "Tutor time", "minutes": 30, "tutors_on": True},
    {"name": "Class discussion", "minutes": 10, "tutors_on": False},
]


class Phase(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    minutes: int = Field(ge=1, le=240)
    tutors_on: bool


class Timeline(BaseModel):
    phases: list[Phase] = Field(min_length=1, max_length=8)

    @field_validator("phases")
    @classmethod
    def _needs_tutor_time(cls, phases: list[Phase]) -> list[Phase]:
        if not any(p.tutors_on for p in phases):
            raise ValueError("A lesson needs at least one phase with tutors on.")
        if sum(p.minutes for p in phases) > 240:
            raise ValueError("A lesson can be at most 240 minutes.")
        return phases


# Plans written before timelines existed behaved as if tutors were on for the
# whole lesson. They keep that behaviour instead of silently gaining phases
# with tutors switched off. New plans get DEFAULT_TIMELINE from the form.
LEGACY_TIMELINE: list[dict] = [{"name": "Tutor time", "minutes": 50, "tutors_on": True}]


def timeline_of(raw: list | None) -> list[dict]:
    """The stored timeline, or the legacy single tutor-time phase."""
    return list(raw) if raw else [dict(p) for p in LEGACY_TIMELINE]


def total_minutes(raw: list | None) -> int:
    return sum(int(p["minutes"]) for p in timeline_of(raw))


def tutors_on(raw: list | None, phase_index: int) -> bool:
    phases = timeline_of(raw)
    if not 0 <= phase_index < len(phases):
        return False
    return bool(phases[phase_index]["tutors_on"])
