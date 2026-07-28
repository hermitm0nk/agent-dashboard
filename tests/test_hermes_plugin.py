from pathlib import Path
import sys
from types import ModuleType

PACKAGE = Path(__file__).parents[1] / "plugins/hermes-agent-dashboard"
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
    adapter.pre_llm_call("session-1", user_message="Please do it", model="model-1",
                         reasoning_effort="high")
    adapter.post_llm_call("session-1", assistant_response="Done", model="model-1",
                          reasoning_effort="high")
    adapter.on_session_finalize("session-1")

    assert [event for _, event, _ in sent] == [
        "waiting_for_input", "message", "working", "message", "waiting_for_input", "finished",
    ]
    assert sent[1][2] == {
        "model": "model-1", "effort": "high",
        "message_role": "user", "message": "Please do it",
    }
    assert sent[3][2]["message"] == "Done"
    assert sent[3][2]["message_role"] == "assistant"


def test_hermes_session_reset_starts_new_gateway_session(monkeypatch):
    adapter = DashboardAdapter()
    sent = []
    monkeypatch.setattr(adapter, "send", lambda session, event, **extra: sent.append((session, event)) or True)
    adapter.on_session_reset("new-session")
    assert sent == [("new-session", "waiting_for_input")]


def test_hermes_failed_turn_reports_error_without_finishing_session(monkeypatch):
    adapter = DashboardAdapter()
    sent = []
    monkeypatch.setattr(adapter, "send", lambda session, event, **extra: sent.append(event) or True)
    adapter.on_session_start("session-1")
    adapter.on_session_end("session-1", completed=False)
    assert sent == ["waiting_for_input", "error"]
    assert "session-1" in adapter.active


def test_hermes_effort_uses_native_model_aware_config_resolver(monkeypatch):
    config_module = ModuleType("hermes_cli.config")
    config_module.load_config_readonly = lambda: {
        "agent": {"reasoning_effort": "medium", "reasoning_overrides": {"model-1": "high"}},
    }
    constants_module = ModuleType("hermes_constants")
    def resolve(config, model):
        value = config["agent"]["reasoning_overrides"].get(
            model, config["agent"]["reasoning_effort"],
        )
        return {"enabled": True, "effort": value}
    constants_module.resolve_reasoning_config = resolve
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config_module)
    monkeypatch.setitem(sys.modules, "hermes_constants", constants_module)

    assert DashboardAdapter._effort({}, "model-1") == "high"


def test_hermes_hook_effort_takes_priority_over_config(monkeypatch):
    monkeypatch.setattr(DashboardAdapter, "_configured_effort", lambda model: "medium")
    assert DashboardAdapter._effort({"reasoning_effort": "xhigh"}, "model-1") == "xhigh"
