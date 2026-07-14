from uuid import uuid4

from agent_dashboard.models import AgentStatus, NotificationRule
from agent_dashboard.rules import evaluate
from tests.test_models import make_event


def test_rule_evaluator_matches_all_selected_dimensions(database):
    event = make_event(agent_id="agent-1", harness="pi", event_type="waiting_for_input")
    state = database.record_event(event)
    rule = NotificationRule(rule_id=uuid4(), name="Pi attention", action="notify",
                            harness="pi", status=AgentStatus.WAITING_FOR_INPUT)
    assert evaluate([rule], event, state) == [rule]


def test_disabled_or_nonmatching_rules_are_ignored(database):
    event = make_event(harness="opencode")
    state = database.record_event(event)
    rules = [NotificationRule(rule_id=uuid4(), name="off", action="notify", enabled=False),
             NotificationRule(rule_id=uuid4(), name="other", action="silence", harness="pi")]
    assert evaluate(rules, event, state) == []
