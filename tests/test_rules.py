from uuid import uuid4

from agent_dashboard.models import NotificationRule
from agent_dashboard.rules import evaluate
from tests.test_models import make_event


def test_rule_evaluator_matches_all_selected_dimensions(database):
    event = make_event(agent_id="agent-1", harness="pi", event_type="waiting_for_input")
    state = database.record_event(event)
    rule = NotificationRule(rule_id=uuid4(), name="Pi attention",
                            match={"agent_type": "pi", "status": "waiting_for_input"},
                            actions=[{"type": "native", "hostname_regex": ".*"}])
    assert evaluate([rule], event, state) == [rule]


def test_disabled_or_nonmatching_rules_are_ignored(database):
    event = make_event(harness="opencode")
    state = database.record_event(event)
    rules = [NotificationRule(rule_id=uuid4(), name="off", enabled=False),
             NotificationRule(rule_id=uuid4(), name="other", match={"agent_type": "pi"})]
    assert evaluate(rules, event, state) == []


def test_rule_status_regex_matches_state_status(database):
    event = make_event(event_type="error")
    state = database.record_event(event)
    rule = NotificationRule(rule_id=uuid4(), name="failures", match={"status": "err.*"})
    assert evaluate([rule], event, state) == [rule]


def test_rule_matches_message_text_and_other_attributes(database):
    event = make_event(agent_id="agent-12", event_type="message", message="Approval needed")
    state = database.record_event(event)
    rule = NotificationRule(rule_id=uuid4(), name="approval", match={
        "type": "message", "text": "Approval.*", "agent_id": "agent-\\d+",
        "working_dir": ".*", "session_id": ".+",
    })
    assert evaluate([rule], event, state) == [rule]


def test_rule_regexes_match_substrings_and_can_be_anchored(database):
    event = make_event(agent_id="prefix-agent-12-suffix", event_type="waiting_for_input")
    state = database.record_event(event)
    substring = NotificationRule(rule_id=uuid4(), name="substring", match={"status": "input", "agent_id": "agent-12"})
    anchored = NotificationRule(rule_id=uuid4(), name="anchored", match={"agent_id": "^agent-12$"})
    assert evaluate([substring, anchored], event, state) == [substring]
