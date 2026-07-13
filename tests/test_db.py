from tests.test_models import make_event


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
