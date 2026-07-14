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


def test_codex_installer_uses_current_hook_configuration(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    subprocess.run([str(HOOKS / "install-codex.sh"), "http://dashboard.test"],
                   env=env, text=True, capture_output=True, check=True)
    hooks = json.loads((tmp_path / ".codex/hooks.json").read_text())["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "Stop"}
    config = json.loads((tmp_path / ".codex/agent-dashboard.json").read_text())
    assert config["url"] == "http://dashboard.test"
    assert (tmp_path / ".local/bin/codex").is_symlink()


def test_hermes_installer_installs_and_enables_entrypoint_plugin(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "hermes-calls"
    uv_calls = tmp_path / "uv-calls"
    hermes = bin_dir / "hermes"
    hermes.write_text(f"#!/usr/bin/env sh\nprintf '%s\\n' \"$*\" >> {calls}\n")
    hermes.chmod(0o755)
    python = bin_dir / "hermes-python"
    python.write_text("#!/usr/bin/env sh\nexit 0\n")
    python.chmod(0o755)
    uv = bin_dir / "uv"
    uv.write_text(f"#!/usr/bin/env sh\nprintf '%s\\n' \"$*\" >> {uv_calls}\n")
    uv.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "HERMES_PYTHON": str(python)}
    subprocess.run([str(HOOKS / "install-hermes.sh"), "http://dashboard.test"],
                   env=env, text=True, capture_output=True, check=True)
    assert json.loads((tmp_path / ".hermes/agent-dashboard.json").read_text())["url"] == "http://dashboard.test"
    assert calls.read_text().strip() == "plugins enable --no-allow-tool-override agent-dashboard"
    assert "pip install --python" in uv_calls.read_text()
    assert "--no-deps --reinstall" in uv_calls.read_text()
    assert "integrations/hermes-agent-dashboard" in uv_calls.read_text()
