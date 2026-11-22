"""The learning-science guidance (docs/superpowers/specs/2026-11-22-tutor-learning-science-
design.md): each change is said to the tutor, in its own words, and none is enforced by the
server. The tutor decides; the platform records."""

import inspect

import pytest
from pydantic import ValidationError

from app.agent import scaffold, student_mode, supervisor
from app.agent.tutor_reply import AssessmentOut
from app.enums import ErrorKind

# The student prompt before this change, measured as "old" by bench.tutor_ab.
BEFORE = "student-v21-149ae41f"


def _flat(text: str) -> str:
    return " ".join(text.split()).lower()


def test_how_to_teach_carries_each_change():
    teach = _flat(scaffold.TEACH)
    # T1: why it is wrong, one of three causes.
    assert (
        "a missing or mistaken piece of knowledge, a slip in reasoning, or trouble putting it "
        "into words"
    ) in teach
    # T2: supported is not yet independent.
    assert "met with help is progress, not yet mastery" in teach
    assert "one brief comparable question to do without help" in teach
    # T3: what usually fits the cause, judged by what comes next.
    assert "a misconception wants refuting, with a reason why" in teach
    assert "their next reply tells you whether it worked" in teach
    # T4: language is not understanding.
    assert "a short or clumsy answer is not a shallow one" in teach
    # T5: support, not less demand.
    assert "more support towards the same thinking before an easier question" in teach
    # T6: switched off is not stuck.
    assert "a brief check-in" in teach


def test_depth_of_knowledge_is_in_the_fixed_prose_and_the_pitch_points_to_it():
    fixed = _flat(" ".join(scaffold.fixed_parts()))
    assert "depth of knowledge" in fixed
    for kind in ("recalling", "applying", "reasoning strategically", "extended thinking"):
        assert kind in fixed, kind
    assert "not a ladder" in fixed
    assert "depth of knowledge" in _flat(scaffold.PITCH)


def test_no_new_rule_is_enforced():
    for module in (supervisor, student_mode):
        assert "error_kind" not in inspect.getsource(module), module.__name__


def test_error_kind_is_optional_and_named():
    assert AssessmentOut(judgment="not_met").error_kind is None
    named = AssessmentOut(judgment="not_met", error_kind="expression")
    assert named.error_kind is ErrorKind.EXPRESSION
    assert {k.value for k in ErrorKind} == {"knowledge", "reasoning", "expression"}
    with pytest.raises(ValidationError):
        AssessmentOut(judgment="not_met", error_kind="laziness")
    # Recorded, never said to the student.
    described = AssessmentOut.model_fields["error_kind"].description or ""
    assert "never" in described.lower() and "student" in described.lower()


def test_the_student_prompt_version_changed():
    assert student_mode.prompt_version() != BEFORE
