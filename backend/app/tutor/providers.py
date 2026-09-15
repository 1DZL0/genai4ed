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


@dataclass(frozen=True)
class WritingRequest:
    """One request for help with a written response.

    Like `TutorRequest`, it carries only what the tutor may use: the task, the
    student's own text, the permitted rung and the teacher's wording for it,
    and the teacher's approved notes. Never a model answer.
    """

    task: str
    student_text: str
    ask: str  # TutorAsk value
    question: str
    rung: Rung
    hint_template: str | None
    material_notes: str
    may_rewrite_sentence: bool


@dataclass(frozen=True)
class ScoreRequest:
    task: str
    student_text: str
    criteria: tuple[dict, ...]  # {"name", "max", "description"}


class LLMProvider(Protocol):
    name: str
    model: str

    async def generate(self, request: TutorRequest) -> str: ...

    async def generate_writing(self, request: WritingRequest) -> str: ...

    async def score(self, request: ScoreRequest) -> str: ...


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

    async def generate_writing(self, request: WritingRequest) -> str:
        """The teacher's own wording where there is some, otherwise a plain,
        short prompt for the permitted step. Never more than two sentences."""
        if request.ask == "language":
            message = (
                "Read each sentence aloud. Check it has a subject and a verb, ends with a full "
                "stop, and uses formal words rather than everyday ones."
            )
        elif request.ask == "feedback":
            message = _stub_feedback(request.student_text)
        elif request.rung is Rung.ATTEMPT:
            message = (
                "Have a go first. Write what you think, even if it's rough, "
                "and I'll help from there."
            )
        else:
            message = request.hint_template or _STUB_STEPS.get(
                request.rung, "Look again at the structure on the board."
            )
        return json.dumps(
            {
                "message": message,
                "rung_used": request.rung.value,
                "rewrites_sentence": False,
                "confidence": 0.8,
                "requests_teacher": False,
            }
        )

    async def score(self, request: ScoreRequest) -> str:
        """A deterministic stand-in for rubric marking, so the whole flow runs
        offline. It is not a judgement of quality; the teacher confirms every
        score before a student sees it."""
        words = len(request.student_text.split())
        lowered = request.student_text.lower()
        signals = sum(
            phrase in lowered
            for phrase in ("for example", "because", "therefore", "for this reason", "firstly")
        )
        criteria = []
        for c in request.criteria:
            share = min(1.0, words / 90) * 0.6 + min(1.0, signals / 3) * 0.4
            points = max(0, min(int(c["max"]), round(int(c["max"]) * share)))
            criteria.append(
                {
                    "name": c["name"],
                    "points": points,
                    "reason": f"{words} words; {signals} linking or example phrases found.",
                }
            )
        return json.dumps(
            {
                "criteria": criteria,
                "keep": "Your argument is stated clearly.",
                "develop": ["Back each reason with a real example."],
                "confidence": 0.6,
            }
        )


_STUB_STEPS = {
    Rung.DIAGNOSTIC_QUESTION: "Think back to what you studied. What did it say about this?",
    Rung.CONCEPTUAL_CUE: (
        "Look at the structure on the board. Which part is missing from your paragraph?"
    ),
    Rung.TARGETED_HINT: (
        "Pick one of your reasons and say what actually happens in someone's life because of it."
    ),
    Rung.ANALOGOUS_EXAMPLE: (
        "One idea from the material: think of a real person or job that shows your reason."
    ),
    Rung.PARTIAL_STEP: 'You could build on a sentence that starts: "For example, ..."',
}


def _stub_feedback(text: str) -> str:
    lowered = text.lower()
    has_example = "for example" in lowered or "for instance" in lowered
    return (
        "Content: your argument is there. "
        + ("You give an example. " if has_example else "Add a real example to back a reason. ")
        + "Structure: check each reason comes before the example that supports it."
    )


class OverHelpfulProvider:
    """Climbs past the rung it was permitted. The Supervisor must catch it."""

    name = "stub-over-helpful"
    model = "stub-v1"

    async def generate(self, request: TutorRequest) -> str:
        return _payload("Here is the whole method, step by step.", Rung.FULL_SOLUTION, None, 0.9)


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


class ParagraphWriterProvider(StubProvider):
    """Writes the student's paragraph for them while permitted only a hint.

    The writing equivalent of answer leakage, and the failure the writing
    supervisor exists to stop.
    """

    name = "stub-paragraph-writer"

    async def generate_writing(self, request: WritingRequest) -> str:
        paragraph = (
            "Salary is one of the most important criteria when choosing a profession. "
            "Firstly, a good salary gives people security, because they can pay for a home. "
            "Secondly, it improves their quality of life, since they can travel and rest. "
            "For example, doctors can support a family comfortably. "
            "For this reason, many people consider salary carefully."
        )
        return json.dumps(
            {
                "message": paragraph,
                "rung_used": request.rung.value,
                "rewrites_sentence": False,
                "confidence": 0.9,
                "requests_teacher": False,
            }
        )


class OverScoringProvider(StubProvider):
    """Gives more points than a criterion allows. Validation must refuse it."""

    name = "stub-over-scoring"

    async def score(self, request: ScoreRequest) -> str:
        return json.dumps(
            {
                "criteria": [
                    {"name": c["name"], "points": int(c["max"]) + 5, "reason": "Excellent."}
                    for c in request.criteria
                ],
                "keep": "",
                "develop": [],
                "confidence": 0.9,
            }
        )


def get_provider(name: str) -> LLMProvider:
    if name == "stub":
        return StubProvider()
    if name == "anthropic":
        from app.tutor.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    raise ValueError(f"unknown LLM provider {name!r}")
