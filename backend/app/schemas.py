"""API and structured-output contracts."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from app.enums import ExceptionKind, Rung


class TutorResponse(BaseModel):
    """What the model must return, and the shape it is held to.

    Validation is not decoration: a response that fails here is regenerated
    once and then withheld. `misconception_code` is checked against the item's
    closed vocabulary through validation context, so the tutor cannot invent a
    diagnosis the teacher never sanctioned.
    """

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    rung_used: Rung
    misconception_code: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    requests_teacher: bool = False

    @model_validator(mode="after")
    def _diagnosis_must_come_from_the_teachers_vocabulary(
        self, info: ValidationInfo
    ) -> "TutorResponse":
        vocabulary = (info.context or {}).get("misconception_vocabulary")
        if vocabulary is None or self.misconception_code is None:
            return self
        if self.misconception_code not in vocabulary:
            raise ValueError(
                f"misconception_code {self.misconception_code!r} is not in this item's "
                f"vocabulary {sorted(vocabulary)}"
            )
        return self


class AttemptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: uuid.UUID
    answer: str = Field(max_length=2000)


class AttemptResult(BaseModel):
    """What the student sees. Deliberately narrow.

    There is no field here for the expected answer, the permitted rung, or the
    conflicts the Supervisor found - none of that is the student's business,
    and shipping it would undo the ladder.
    """

    attempt_id: uuid.UUID
    correct: bool
    attempt_index: int
    tutor_message: str
    help_given: bool
    teacher_notified: bool


class ExceptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_pseudonym: str
    kind: ExceptionKind
    priority: int
    status: str
    summary: str
    supporting_record_ids: list[uuid.UUID]
    created_at: datetime
