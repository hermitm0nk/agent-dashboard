from pathlib import Path

from agent_dashboard.hooks.hermes_plugin.adapter import DashboardAdapter


PLUGIN = Path(__file__).parents[1] / "agent_dashboard/hooks/hermes_plugin"


def test_hermes_plugin_load_does_not_announce_a_fake_process_session(monkeypatch):
    sent = []
    monkeypatch.setattr(DashboardAdapter, "send", lambda *args, **kwargs: sent.append(args))
    adapter = DashboardAdapter()
    assert adapter.active == set()
    assert sent == []


def test_hermes_plugin_manifest_declares_registered_lifecycle_hooks():
    manifest = (PLUGIN / "plugin.yaml").read_text()
    assert "name: agent-dashboard" in manifest
    for hook in ("on_session_start", "pre_llm_call", "post_llm_call", "on_session_end",
                 "on_session_finalize", "on_session_reset"):
        assert f"  - {hook}\n" in manifest


def test_hermes_adapter_reports_session_lifecycle_and_response(monkeypatch):
    adapter = DashboardAdapter()
    sent = []
    monkeypatch.setattr(adapter, "send", lambda session, event, **extra: sent.append((session, event, extra)) or True)

    adapter.on_session_start("session-1", model="model-1")
    adapter.pre_llm_call("session-1", model="model-1")
    adapter.post_llm_call("session-1", assistant_response="Done", model="model-1")
    adapter.on_session_finalize("session-1")

    assert [event for _, event, _ in sent] == [
        "started", "working", "message", "waiting_for_input", "finished",
    ]
    assert sent[2][2]["message"] == "Done"


def test_hermes_session_reset_starts_new_gateway_session(monkeypatch):
    adapter = DashboardAdapter()
    sent = []
    monkeypatch.setattr(adapter, "send", lambda session, event, **extra: sent.append((session, event)) or True)
    adapter.on_session_reset("new-session")
    assert sent == [("new-session", "started")]


def test_hermes_failed_turn_reports_error_without_finishing_session(monkeypatch):
    adapter = DashboardAdapter()
    sent = []
    monkeypatch.setattr(adapter, "send", lambda session, event, **extra: sent.append(event) or True)
    adapter.on_session_start("session-1")
    adapter.on_session_end("session-1", completed=False)
    assert sent == ["started", "error"]
    assert "session-1" in adapter.active
