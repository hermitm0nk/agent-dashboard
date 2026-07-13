from datetime import datetime, timezone

from agent_dashboard.hooks.opencode import OpenCodeHook


def test_opencode_normalizes_native_lifecycle_payload():
    hook = OpenCodeHook("http://dashboard.test", host_id="host-1", working_dir="/tmp/project",
                        location={"kind": "tmux", "session": "dev", "window": "1", "pane": "2"})
    event = hook.normalize({"event": "session.waiting", "sessionID": "session-1",
                            "timestamp": "2026-01-01T12:00:00+00:00", "message": "Approve?"})
    assert event.agent_id == "session-1"
    assert event.event_type == "waiting_for_input"
    assert event.timestamp == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def test_opencode_hook_does_not_raise_when_server_unavailable():
    hook = OpenCodeHook("http://127.0.0.1:1", working_dir="/tmp")
    assert hook.send({"event": "session.started", "sessionID": "session-1"}) is False
