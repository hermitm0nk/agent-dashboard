import json
import os
import subprocess
import sys
from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "plugins/codex-agent-dashboard"
HOOK = PLUGIN / "scripts/codex-dashboard-hook.py"
WRAPPER = PLUGIN / "scripts/codex-dashboard-wrapper.py"


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
    assert captured["body"]["event_type"] == "waiting_for_input"


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


def test_codex_hook_reports_messages_and_transcript_effort(monkeypatch, tmp_path):
    import io
    import urllib.request
    from runpy import run_path

    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"type": "turn_context", "payload": {
            "model": "gpt-5.2-codex", "effort": "high",
        }}) + "\n"
    )
    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
    def urlopen(request, timeout):
        captured.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    namespace = run_path(str(HOOK), run_name="codex_hook_test")

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "hook_event_name": "UserPromptSubmit", "session_id": "thread-1",
        "cwd": "/tmp", "transcript_path": str(transcript), "prompt": "Build it",
    })))
    namespace["main"]()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "hook_event_name": "Stop", "session_id": "thread-1", "cwd": "/tmp",
        "transcript_path": str(transcript), "last_assistant_message": "Done",
    })))
    namespace["main"]()

    assert [item["event_type"] for item in captured] == [
        "message", "working", "message", "waiting_for_input",
    ]
    assert captured[0]["message_role"] == "user"
    assert captured[2]["message_role"] == "assistant"
    assert all(item["model"] == "gpt-5.2-codex" for item in captured)
    assert all(item["effort"] == "high" for item in captured)


def test_codex_hooks_include_native_session_end():
    hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text())["hooks"]
    assert {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"} <= hooks.keys()


def test_codex_wrapper_announces_process_with_one_dashboard_identity(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    events = tmp_path / "events.jsonl"
    hook = tmp_path / "hook.py"
    hook.write_text(
        "#!/usr/bin/env python3\nimport json,os,sys\n"
        "item=json.load(sys.stdin); item['instance']=os.environ.get('AGENT_DASHBOARD_INSTANCE_ID')\n"
        "with open(os.environ['EVENTS'], 'a') as f: f.write(json.dumps(item)+'\\n')\n"
    )
    hook.chmod(0o755)
    real_codex = tmp_path / "real-codex"
    real_codex.write_text("#!/usr/bin/env sh\nexit 7\n")
    real_codex.chmod(0o755)
    (codex_dir / "agent-dashboard.json").write_text(json.dumps({
        "real_codex": str(real_codex), "hook": str(hook),
    }))
    result = subprocess.run([sys.executable, str(WRAPPER)], env={
        **os.environ, "HOME": str(tmp_path), "EVENTS": str(events),
    }, check=False)
    assert result.returncode == 7
    payloads = [json.loads(line) for line in events.read_text().splitlines()]
    assert [item["hook_event_name"] for item in payloads] == [
        "DashboardProcessStart", "DashboardProcessEnd",
    ]
    assert payloads[0]["session_id"] == payloads[1]["session_id"]
    assert payloads[0]["instance"] == payloads[0]["session_id"]
    assert payloads[1]["instance"] == payloads[0]["session_id"]


def test_codex_native_session_reuses_wrapper_dashboard_identity(monkeypatch):
    import io
    import urllib.request
    from runpy import run_path

    captured = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
    def urlopen(request, timeout):
        captured.update(json.loads(request.data))
        return Response()
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("AGENT_DASHBOARD_INSTANCE_ID", "codex-host-123")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "hook_event_name": "SessionStart", "session_id": "native-thread",
        "cwd": "/tmp",
    })))
    run_path(str(HOOK), run_name="codex_hook_test")["main"]()
    assert captured["agent_id"] == "codex-host-123"
    assert captured["session_id"] == "native-thread"
