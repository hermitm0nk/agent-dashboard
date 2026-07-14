from pathlib import Path
import sys

PACKAGE = Path(__file__).parents[1] / "integrations/hermes-agent-dashboard"
sys.path.insert(0, str(PACKAGE / "src"))

from hermes_agent_dashboard.adapter import DashboardAdapter
from hermes_agent_dashboard.plugin import register



def test_hermes_plugin_load_does_not_announce_a_fake_process_session(monkeypatch):
    sent = []
    monkeypatch.setattr(DashboardAdapter, "send", lambda *args, **kwargs: sent.append(args))
    adapter = DashboardAdapter()
    assert adapter.active == set()
    assert sent == []


def test_hermes_package_declares_plugin_entry_point():
    metadata = (PACKAGE / "pyproject.toml").read_text()
    assert '[project.entry-points."hermes_agent.plugins"]' in metadata
    assert 'agent-dashboard = "hermes_agent_dashboard.plugin:register"' in metadata
    assert register.register is register


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
