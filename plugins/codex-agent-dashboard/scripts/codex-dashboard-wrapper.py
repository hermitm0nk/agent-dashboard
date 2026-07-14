#!/usr/bin/env python3
"""Run Codex while reporting process lifecycle through the installed plugin."""
import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path


def load_config() -> dict[str, str]:
    try:
        data = json.loads((Path.home() / ".codex" / "agent-dashboard.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def report(hook: str, event: str, instance_id: str) -> None:
    payload = {"hook_event_name": event, "session_id": instance_id,
               "cwd": os.getcwd()}
    try:
        subprocess.run([hook], input=json.dumps(payload), text=True,
                       stdout=subprocess.DEVNULL, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def main() -> int:
    config = load_config()
    real_codex = os.getenv("AGENT_DASHBOARD_CODEX_REAL") or config.get("real_codex") or "/usr/bin/codex"
    hook = config.get("hook") or str(Path.home() / ".codex" / "agent-dashboard-hook.py")
    instance_id = f"codex-{socket.gethostname()}-{os.getpid()}"
    env = {**os.environ, "AGENT_DASHBOARD_INSTANCE_ID": instance_id}
    report(hook, "DashboardProcessStart", instance_id)
    try:
        process = subprocess.Popen([real_codex, *sys.argv[1:]], env=env)
        returncode = process.wait()
        return 128 + (-returncode) if returncode < 0 else returncode
    except KeyboardInterrupt:
        return 130
    finally:
        report(hook, "DashboardProcessEnd", instance_id)


if __name__ == "__main__":
    raise SystemExit(main())
