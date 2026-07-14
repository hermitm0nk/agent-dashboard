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


def test_hermes_installer_links_and_enables_native_plugin(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "hermes-calls"
    hermes = bin_dir / "hermes"
    hermes.write_text(f"#!/usr/bin/env sh\nprintf '%s\\n' \"$*\" >> {calls}\n")
    hermes.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    subprocess.run([str(HOOKS / "install-hermes.sh"), "http://dashboard.test"],
                   env=env, text=True, capture_output=True, check=True)
    plugin = tmp_path / ".hermes/plugins/agent-dashboard"
    assert plugin.is_symlink()
    assert (plugin / "plugin.yaml").is_file()
    assert json.loads((tmp_path / ".hermes/agent-dashboard.json").read_text())["url"] == "http://dashboard.test"
    assert calls.read_text().strip() == "plugins enable --no-allow-tool-override agent-dashboard"
