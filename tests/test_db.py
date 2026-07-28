from datetime import timedelta

from tests.test_models import make_event
from uuid import uuid4

from agent_dashboard.models import NotificationRule


def test_record_event_updates_current_state_and_history(database):
    event = make_event(event_type="waiting_for_input", message="Need approval")
    state = database.record_event(event)

    assert state.status.value == "waiting_for_input"
    assert state.last_message == "Need approval"
    assert database.snapshot()[0] == state
    assert database.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_snapshot_is_sorted_by_agent_id(database):
    database.record_event(make_event(agent_id="z-agent"))
    database.record_event(make_event(agent_id="a-agent"))
    assert [state.agent_id for state in database.snapshot()] == ["a-agent", "z-agent"]


def test_agent_events_are_returned_in_chronological_order(database):
    later = make_event(message="later")
    earlier = make_event(timestamp=later.timestamp - timedelta(minutes=1), message="earlier")
    database.record_event(later)
    database.record_event(earlier)
    assert [event.message for event in database.events_for_agent("agent-1")] == ["earlier", "later"]


def test_duplicate_and_late_events_do_not_replace_current_state(database):
    current = make_event(event_type="waiting_for_input", message="Approve this")
    database.record_event(current)
    _, inserted = database.record_event_if_new(current)
    assert inserted is False

    late = make_event(timestamp=current.timestamp - timedelta(minutes=1), event_type="working")
    state, inserted = database.record_event_if_new(late)
    assert inserted is True
    assert state.status.value == "waiting_for_input"
    assert state.last_message == "Approve this"
    assert database.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2


def test_message_preserves_status_and_optional_metadata(database):
    waiting = make_event(event_type="waiting_for_input", model="gpt-test", effort="high", chat_title="Review")
    database.record_event(waiting)
    message = make_event(event_type="message", message="Still waiting", model=None, chat_title=None)
    state = database.record_event(message)
    assert state.status.value == "waiting_for_input"
    assert state.model == "gpt-test"
    assert state.effort == "high"
    assert state.chat_title == "Review"


def test_notification_rule_matchers_and_actions_are_persistent(database):
    rule = NotificationRule(rule_id=uuid4(), name="agent alerts", match={"agent_id": "agent-.*"},
                            actions=[{"type": "ntfy", "topic": "agent-alerts"},
                                     {"type": "native", "hostname_regex": "laptop-.*"}])
    database.save_rule(rule)
    assert database.rules() == [rule]
