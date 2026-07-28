#!/usr/bin/env python3
"""Launch Codex; native plugin hooks own dashboard session lifecycle."""
import json
import os
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


def report(hook: str, event: str, instance_id: str, env: dict[str, str]) -> None:
    payload = {"hook_event_name": event, "session_id": instance_id, "cwd": os.getcwd()}
    try:
        subprocess.run(
            [hook], input=json.dumps(payload), text=True, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def main() -> int:
    config = load_config()
    real_codex = os.getenv("AGENT_DASHBOARD_CODEX_REAL") or config.get("real_codex") or "/usr/bin/codex"
    hook = config.get("hook") or str(Path.home() / ".codex/plugins/agent-dashboard/scripts/codex-dashboard-hook.py")
    instance_id = f"codex-{socket.gethostname()}-{os.getpid()}"
    env = {**os.environ, "AGENT_DASHBOARD_INSTANCE_ID": instance_id}
    report(hook, "DashboardProcessStart", instance_id, env)
    try:
        process = subprocess.run([real_codex, *sys.argv[1:]], env=env, check=False)
        return 128 + (-process.returncode) if process.returncode < 0 else process.returncode
    except KeyboardInterrupt:
        return 130
    finally:
        report(hook, "DashboardProcessEnd", instance_id, env)


if __name__ == "__main__":
    raise SystemExit(main())
