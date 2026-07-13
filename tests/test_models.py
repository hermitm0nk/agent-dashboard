from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_dashboard.models import AgentEvent, AgentStatus, TmuxLocation


def make_event(**overrides):
    data = dict(event_id=uuid4(), agent_id="agent-1", session_id="session-1", event_type="working",
                timestamp=datetime(2026, 1, 1, 12, tzinfo=timezone.utc), host_id="host-1",
                working_dir="/work/project", location={"kind": "tmux", "session": "dev",
                "window": "0", "pane": "1"})
    data.update(overrides)
    return AgentEvent.model_validate(data)


def test_event_normalizes_timestamp_to_utc():
    event = make_event(timestamp="2026-01-01T15:00:00+03:00")
    assert event.timestamp == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def test_event_rejects_naive_timestamp_and_unknown_fields():
    with pytest.raises(ValidationError):
        make_event(timestamp="2026-01-01T12:00:00")
    with pytest.raises(ValidationError):
        make_event(unexpected="nope")


def test_location_and_status_are_typed():
    event = make_event()
    assert isinstance(event.location, TmuxLocation)
    assert AgentStatus.WORKING.value == "working"
