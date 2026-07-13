import os
import subprocess
from pathlib import Path


HOOKS = Path(__file__).parents[1] / "agent_dashboard" / "hooks"


def test_installation_docs_cover_supported_harnesses():
    docs = (HOOKS / "README.md").read_text()
    for harness in ("pi", "OpenCode", "Hermes"):
        assert harness in docs
    for script in ("install-pi.sh", "install-opencode.sh", "install-hermes.sh"):
        assert os.access(HOOKS / script, os.X_OK)


def test_hermes_hook_is_non_blocking_for_unmapped_events():
    result = subprocess.run([str(HOOKS / "hermes-dashboard-hook.py")], input='{"hook_event_name":"unknown"}\n',
                            text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "{}"
