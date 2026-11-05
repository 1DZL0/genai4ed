"""Which signals reach the teacher at once. The two the policy promises are never held back
must reach them whatever the model put in `tell_teacher`."""

from app.agent import alerts
from app.agent.policy import ALWAYS_TOLD, PolicyRules
from app.enums import SignalKind, TriageAction


def test_a_wellbeing_concern_alerts_even_when_the_model_forgot_to_say_so():
    for signal in ALWAYS_TOLD:
        assert alerts.decide(signal, tell_teacher=False, rule=None, seen=0) is TriageAction.ALERT


def test_a_teachers_rule_cannot_quieten_the_two_that_are_always_told():
    rules = PolicyRules()
    for signal in ALWAYS_TOLD:
        rule = rules.escalation_for(signal) if hasattr(rules, "escalation_for") else None
        assert alerts.decide(signal, tell_teacher=False, rule=rule, seen=0) is TriageAction.ALERT


def test_other_signals_still_follow_the_models_call_and_the_teachers_rule():
    assert (
        alerts.decide(SignalKind.OFF_TASK, tell_teacher=False, rule=None, seen=0)
        is TriageAction.LOG
    )
    assert (
        alerts.decide(SignalKind.OFF_TASK, tell_teacher=True, rule=None, seen=0)
        is TriageAction.ALERT
    )


def test_enforcement_is_on_unless_someone_turns_it_off():
    """Outside compose, with no .env, the server must still redraft or hold back a reply that
    breaks a rule; the one way to switch it off is to say so."""
    from app.config import Settings

    assert Settings(_env_file=None).supervisor_enforce is True
