"""The model seam.

`LLMProvider` returns raw text, not a parsed object, because the failure this
system must survive is the model returning something malformed or
non-compliant. Parsing and judging that text is the caller's job.

One deliberate constraint: `TutorRequest` does not carry the expected answer.
The teacher's hint template for the permitted rung is the only privileged
content the model receives. Defence in depth - the model cannot disclose what
it was never told. The Supervisor still checks for leakage afterwards, because
a capable model can simply solve the equation itself.

The adversarial stubs below are not test scaffolding kept out of the way; they
are the failure modes the platform claims to survive, so they live beside the
real provider and CI exercises every one of them.
"""

import json
from dataclasses import dataclass
from typing import Protocol

from app.enums import Rung


@dataclass(frozen=True)
class TutorRequest:
    item_prompt: str
    student_answer: str
    rung: Rung
    hint_template: str | None
    misconception_vocabulary: tuple[str, ...]
    target_misconception: str | None = None
    evidence_summary: str = ""


class LLMProvider(Protocol):
    name: str
    model: str

    async def generate(self, request: TutorRequest) -> str: ...


class ProviderTimeout(Exception):
    """The provider did not answer. The student still gets a reply."""


def _payload(
    message: str,
    rung: Rung,
    misconception: str | None,
    confidence: float,
    requests_teacher: bool = False,
) -> str:
    return json.dumps(
        {
            "message": message,
            "rung_used": rung.value,
            "misconception_code": misconception,
            "confidence": confidence,
            "requests_teacher": requests_teacher,
        }
    )


class StubProvider:
    """Deterministic, offline, and well-behaved.

    The default provider, so the whole stack runs and every test passes with no
    API key. It answers with the teacher's own hint template for the permitted
    rung, which is also the honest floor for what the real provider must beat.
    """

    name = "stub"
    model = "stub-v1"

    async def generate(self, request: TutorRequest) -> str:
        if request.rung is Rung.ATTEMPT:
            return _payload("That's correct. Move on when you're ready.", request.rung, None, 0.95)

        message = request.hint_template or "Have another look at your working."
        if request.target_misconception:
            message = f"{message} (Watch the step you have repeated.)"

        diagnosis = request.target_misconception or (
            request.misconception_vocabulary[0] if request.misconception_vocabulary else None
        )
        return _payload(message, request.rung, diagnosis, 0.8)


class OverHelpfulProvider:
    """Climbs past the rung it was permitted. The Supervisor must catch it."""

    name = "stub-over-helpful"
    model = "stub-v1"

    async def generate(self, request: TutorRequest) -> str:
        return _payload(
            "Here is the whole method, step by step.", Rung.FULL_SOLUTION, None, 0.9
        )


class AnswerLeakingProvider:
    """States the answer while permitted only to hint.

    This is the TASD failure mode - "no direct answers" reduced leakage without
    eliminating it - which is why it is checked in output rather than asked for
    in a prompt.
    """

    name = "stub-answer-leaking"
    model = "stub-v1"

    def __init__(self, leak: str) -> None:
        self._leak = leak

    async def generate(self, request: TutorRequest) -> str:
        return _payload(f"Think about it this way: x = {self._leak}.", request.rung, None, 0.9)


class InvalidDiagnosisProvider:
    """Invents a misconception code outside the teacher's vocabulary."""

    name = "stub-invalid-diagnosis"
    model = "stub-v1"

    async def generate(self, request: TutorRequest) -> str:
        return _payload("Check your signs.", request.rung, "careless_student", 0.7)


class MalformedProvider:
    """Returns something that is not the agreed contract."""

    name = "stub-malformed"
    model = "stub-v1"

    def __init__(self, body: str = "I'm afraid I can't do that.") -> None:
        self._body = body

    async def generate(self, request: TutorRequest) -> str:
        return self._body


class TimeoutProvider:
    name = "stub-timeout"
    model = "stub-v1"

    async def generate(self, request: TutorRequest) -> str:
        raise ProviderTimeout("provider did not respond")


class UncertainProvider:
    """Answers, but with low confidence. Routes attention to the teacher
    rather than helping harder."""

    name = "stub-uncertain"
    model = "stub-v1"

    async def generate(self, request: TutorRequest) -> str:
        return _payload(
            request.hint_template or "Try re-reading the question.",
            request.rung,
            None,
            0.2,
        )


def get_provider(name: str) -> LLMProvider:
    if name == "stub":
        return StubProvider()
    if name == "anthropic":
        from app.tutor.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    raise ValueError(f"unknown LLM provider {name!r}")
