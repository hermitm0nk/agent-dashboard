import os
import json
import subprocess
from pathlib import Path


PLUGINS = Path(__file__).parents[1] / "plugins"


def test_installation_docs_cover_supported_harnesses():
    docs = (PLUGINS / "README.md").read_text()
    for harness in ("pi", "OpenCode", "Hermes", "Codex"):
        assert harness in docs
    for plugin in ("pi-agent-dashboard", "opencode-agent-dashboard",
                   "hermes-agent-dashboard", "codex-agent-dashboard"):
        assert os.access(PLUGINS / plugin / "install.sh", os.X_OK)
    assert os.access(PLUGINS / "install-all.sh", os.X_OK)


def test_install_all_skips_unavailable_harnesses_without_failing(tmp_path):
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    env = {**os.environ, "PATH": str(empty_bin), "HOME": str(tmp_path)}
    result = subprocess.run(
        ["/bin/bash", str(PLUGINS / "install-all.sh")],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Installed: none" in result.stdout
    assert "Skipped:   Codex, Pi, OpenCode, Hermes" in result.stdout
    assert "Failed:    none" in result.stdout


def test_codex_installer_uses_current_hook_configuration(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "codex-calls"
    codex = bin_dir / "codex"
    codex.write_text(f"#!/usr/bin/env sh\nprintf '%s\\n' \"$*\" >> {calls}\n")
    codex.chmod(0o755)
    marketplace = tmp_path / ".agents/plugins/marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(json.dumps({
        "name": "existing-personal",
        "interface": {"displayName": "My existing plugins"},
        "plugins": [
            {"name": "keep-me", "source": "./keep-me"},
            {"name": "agent-dashboard", "source": "./old", "custom": "preserved"},
        ],
        "custom": {"preserved": True},
    }))
    env = {**os.environ, "HOME": str(tmp_path),
           "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "AGENT_DASHBOARD_CODEX_REAL": "/usr/bin/true"}
    subprocess.run([str(PLUGINS / "codex-agent-dashboard/install.sh"), "http://dashboard.test"],
                   env=env, text=True, capture_output=True, check=True)
    plugin = tmp_path / ".codex/plugins/agent-dashboard"
    hooks = json.loads((plugin / "hooks/hooks.json").read_text())["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "Stop"}
    config = json.loads((tmp_path / ".codex/agent-dashboard.json").read_text())
    assert config["url"] == "http://dashboard.test"
    assert (tmp_path / ".local/bin/codex").is_symlink()
    merged = json.loads(marketplace.read_text())
    assert merged["name"] == "existing-personal"
    assert merged["interface"] == {"displayName": "My existing plugins"}
    assert merged["custom"] == {"preserved": True}
    assert [entry["name"] for entry in merged["plugins"]] == ["keep-me", "agent-dashboard"]
    assert merged["plugins"][-1]["source"]["path"] == "./.codex/plugins/agent-dashboard"
    assert merged["plugins"][-1]["custom"] == "preserved"
    assert calls.read_text().strip() == "plugin add agent-dashboard --marketplace existing-personal"


def test_pi_installer_uses_package_install_command(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "pi-calls"
    pi = bin_dir / "pi"
    pi.write_text(f"#!/usr/bin/env sh\nprintf '%s\\n' \"$*\" >> {calls}\n")
    pi.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    subprocess.run([str(PLUGINS / "pi-agent-dashboard/install.sh")], env=env, check=True)
    assert calls.read_text().startswith("install ")
    assert "plugins/pi-agent-dashboard" in calls.read_text()


def test_opencode_installer_uses_plugin_command(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "opencode-calls"
    opencode = bin_dir / "opencode"
    opencode.write_text(f"#!/usr/bin/env sh\nprintf '%s\\n' \"$*\" >> {calls}\n")
    opencode.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    subprocess.run([str(PLUGINS / "opencode-agent-dashboard/install.sh")], env=env, check=True)
    assert "plugin " in calls.read_text()
    assert "plugins/opencode-agent-dashboard --global --force" in calls.read_text()


def test_opencode_package_exposes_server_plugin_entrypoint():
    manifest = json.loads((PLUGINS / "opencode-agent-dashboard/package.json").read_text())
    assert manifest["exports"]["./server"] == "./src/index.ts"


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
    subprocess.run([str(PLUGINS / "hermes-agent-dashboard/install.sh"), "http://dashboard.test"],
                   env=env, text=True, capture_output=True, check=True)
    assert json.loads((tmp_path / ".hermes/agent-dashboard.json").read_text())["url"] == "http://dashboard.test"
    assert calls.read_text().strip() == "plugins enable --no-allow-tool-override agent-dashboard"
    assert "pip install --python" in uv_calls.read_text()
    assert "--no-deps --reinstall" in uv_calls.read_text()
    assert "plugins/hermes-agent-dashboard" in uv_calls.read_text()
