import json
import os
import subprocess
import sys
from pathlib import Path


HOOK = Path(__file__).parents[1] / "agent_dashboard/hooks/codex-dashboard-hook.py"
WRAPPER = Path(__file__).parents[1] / "agent_dashboard/hooks/codex-dashboard-wrapper.py"


def test_codex_hook_is_fail_open_and_emits_no_stdout_for_unmapped_event():
    result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"hook_event_name": "Unknown"}) + "\n",
                            text=True, capture_output=True, check=True)
    assert result.stdout == ""


def test_codex_hook_sends_session_start(monkeypatch):
    import urllib.request

    captured = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
    def urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("AGENT_DASHBOARD_HOST_ID", "host-1")
    monkeypatch.setenv("TMUX_PANE", "%4")
    from runpy import run_path
    # Invoke main directly so urllib can be replaced without a child process.
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart",
                                                               "session_id": "thread-1", "cwd": "/tmp"})))
    namespace = run_path(str(HOOK), run_name="codex_hook_test")
    namespace["main"]()
    assert captured["body"]["harness"] == "codex"
    assert captured["body"]["location"]["pane"] == "%4"
    assert captured["body"]["event_type"] == "started"


def test_codex_hook_uses_installed_dashboard_config(monkeypatch, tmp_path):
    import urllib.request

    captured = {}
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "agent-dashboard.json").write_text(json.dumps({"url": "http://dashboard.test"}))
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
    def urlopen(request, timeout):
        captured["url"] = request.full_url
        return Response()
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({
        "hook_event_name": "Stop", "session_id": "thread-1", "cwd": "/tmp",
    })))
    from runpy import run_path
    run_path(str(HOOK), run_name="codex_hook_test")["main"]()
    assert captured["url"] == "http://dashboard.test/api/v1/events"


def test_codex_wrapper_reports_process_lifecycle_with_one_identity(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    events = tmp_path / "events.jsonl"
    hook = tmp_path / "hook.py"
    hook.write_text("#!/usr/bin/env python3\nimport os,sys\n"
                    "with open(os.environ['EVENTS'], 'a') as f: f.write(sys.stdin.read().strip() + '\\n')\n")
    hook.chmod(0o755)
    real_codex = tmp_path / "real-codex"
    real_codex.write_text("#!/usr/bin/env sh\nexit 7\n")
    real_codex.chmod(0o755)
    (codex_dir / "agent-dashboard.json").write_text(json.dumps({
        "hook": str(hook), "real_codex": str(real_codex),
    }))
    result = subprocess.run([sys.executable, str(WRAPPER)], env={
        **os.environ, "HOME": str(tmp_path), "EVENTS": str(events),
    }, check=False)
    payloads = [json.loads(line) for line in events.read_text().splitlines()]
    assert result.returncode == 7
    assert [item["hook_event_name"] for item in payloads] == ["DashboardProcessStart", "DashboardProcessEnd"]
    assert payloads[0]["session_id"] == payloads[1]["session_id"]
