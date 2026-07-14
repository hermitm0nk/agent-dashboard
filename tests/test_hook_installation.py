import os
import json
import subprocess
from pathlib import Path


HOOKS = Path(__file__).parents[1] / "agent_dashboard" / "hooks"


def test_installation_docs_cover_supported_harnesses():
    docs = (HOOKS / "README.md").read_text()
    for harness in ("pi", "OpenCode", "Hermes", "Codex"):
        assert harness in docs
    for script in ("install-pi.sh", "install-opencode.sh", "install-hermes.sh", "install-codex.sh"):
        assert os.access(HOOKS / script, os.X_OK)


def test_hermes_hook_is_non_blocking_for_unmapped_events():
    result = subprocess.run([str(HOOKS / "hermes-dashboard-hook.py")], input='{"hook_event_name":"unknown"}\n',
                            text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "{}"


def test_codex_installer_uses_current_hook_configuration(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    subprocess.run([str(HOOKS / "install-codex.sh"), "http://dashboard.test"],
                   env=env, text=True, capture_output=True, check=True)
    hooks = json.loads((tmp_path / ".codex/hooks.json").read_text())["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "Stop"}
    config = json.loads((tmp_path / ".codex/agent-dashboard.json").read_text())
    assert config["url"] == "http://dashboard.test"
    assert (tmp_path / ".local/bin/codex").is_symlink()
