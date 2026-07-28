from datetime import timedelta
from pathlib import Path

from tests.test_models import make_event
from uuid import uuid4

from agent_dashboard.models import NotificationRule
from agent_dashboard.db import Database


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


def test_agent_updates_mark_unseen_but_initial_ready_does_not(database):
    initial = database.record_event(make_event(event_type="waiting_for_input"))
    assert initial.unseen is False

    database.record_event(make_event(event_type="working"))
    ready = database.record_event(make_event(event_type="waiting_for_input"))
    assert ready.unseen is True

    assert database.set_seen("agent-1", True).unseen is False
    assistant = database.record_event(
        make_event(event_type="message", message_role="assistant", message="Progress")
    )
    assert assistant.unseen is True


def test_user_messages_do_not_mark_a_seen_session_unseen(database):
    database.record_event(make_event(event_type="waiting_for_input"))
    state = database.record_event(
        make_event(event_type="message", message_role="user", message="Continue")
    )
    assert state.unseen is False


def test_seen_state_can_be_toggled_and_cleared_in_bulk(database):
    database.record_event(
        make_event(agent_id="agent-1", event_type="message",
                   message_role="assistant", message="One")
    )
    database.record_event(
        make_event(agent_id="agent-2", session_id="session-2", event_type="message",
                   message_role="assistant", message="Two")
    )
    assert database.set_seen("agent-1", True).unseen is False
    assert database.set_seen("agent-1", False).unseen is True
    assert all(not agent.unseen for agent in database.mark_all_seen())


def test_finished_and_manual_archive_state_are_persistent(database):
    finished = database.record_event(make_event(event_type="finished"))
    assert finished.archived is True
    assert database.set_archived("agent-1", False).archived is False
    assert database.set_archived("agent-1", True).archived is True


def test_database_uses_persistent_home_directory_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    database = Database()
    try:
        assert database.path == tmp_path / ".agent-dashboard" / "agent-dashboard.db"
        assert database.path.is_file()
    finally:
        database.connection.close()


def test_message_search_uses_fts_bm25_ranking(database):
    database.record_event(make_event(
        agent_id="focused", session_id="focused-session", event_type="message",
        message_role="assistant", message="quantum banana quantum banana quantum banana",
    ))
    database.record_event(make_event(
        agent_id="broad", session_id="broad-session", event_type="message",
        message_role="assistant",
        message="quantum banana appears once among many unrelated deployment details",
    ))
    database.record_event(make_event(
        agent_id="irrelevant", session_id="irrelevant-session", event_type="message",
        message_role="assistant", message="ordinary build output",
    ))
    assert database.search_agent_messages("quantum banana") == ["focused", "broad"]


def test_notification_rule_matchers_and_actions_are_persistent(database):
    rule = NotificationRule(rule_id=uuid4(), name="agent alerts", match={"agent_id": "agent-.*"},
                            actions=[{"type": "ntfy", "topic": "agent-alerts"},
                                     {"type": "native", "hostname_regex": "laptop-.*"}])
    database.save_rule(rule)
    assert database.rules() == [rule]


def test_notification_history_replays_state_for_rule_preview(database):
    ready = make_event(
        event_type="waiting_for_input", model="model-a", chat_title="Deploy",
    )
    message = make_event(
        event_type="message", message_role="assistant", message="Approval needed",
        timestamp=ready.timestamp + timedelta(seconds=1),
    )
    database.record_event(ready)
    database.record_event(message)

    history = database.notification_history()
    assert [event.event_type for event, _state in history] == ["waiting_for_input", "message"]
    assert history[1][1].status.value == "waiting_for_input"
    assert history[1][1].model == "model-a"
    assert history[1][1].chat_title == "Deploy"
