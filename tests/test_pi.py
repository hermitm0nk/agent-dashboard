from datetime import datetime, timezone

from agent_dashboard.hooks.pi import PiJsonHook


def test_pi_json_stream_normalizes_session_and_agent_lifecycle():
    hook = PiJsonHook(host_id="host-1", working_dir="/tmp/project",
                      location={"kind": "tmux", "session": "dev", "window": "1", "pane": "2"})
    assert hook.normalize({"type": "session", "id": "pi-session-1"}) is None
    event = hook.normalize({"type": "agent_end", "timestamp": "2026-01-01T12:00:00+00:00"})
    assert event.agent_id == "pi-session-1"
    assert event.event_type == "waiting_for_input"
    assert event.timestamp == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def test_pi_hook_replaces_placeholder_host(monkeypatch):
    monkeypatch.setattr("socket.gethostname", lambda: "archbox")
    hook = PiJsonHook(host_id="unknown-host", working_dir="/tmp", location={"kind": "tmux", "session": "s", "window": "w", "pane": "p"})
    assert hook.host_id == "archbox"


def test_pi_json_hook_ignores_unmapped_records():
    hook = PiJsonHook(host_id="host-1", working_dir="/tmp", location={"kind": "tmux", "session": "s", "window": "w", "pane": "p"})
    hook.normalize({"type": "session", "id": "pi-session-1"})
    assert hook.normalize({"type": "turn_start"}) is None


def test_pi_json_hook_extracts_assistant_message_text():
    hook = PiJsonHook(host_id="host-1", working_dir="/tmp", location={"kind": "tmux", "session": "s", "window": "w", "pane": "p"})
    hook.normalize({"type": "session", "id": "pi-session-1"})
    event = hook.normalize({"type": "message_end", "message": {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "internal"}, {"type": "text", "text": "PI_HOOK_OK"}
    ]}})
    assert event.message == "PI_HOOK_OK"
