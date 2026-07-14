#!/usr/bin/env python3
"""Codex package hook forwarding lifecycle events to Agent Dashboard."""
import json
import os
import socket
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def dashboard_config() -> dict[str, str]:
    """Load installer defaults; environment variables remain authoritative."""
    path = Path.home() / ".codex" / "agent-dashboard.json"
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        config = dashboard_config()
        native = str(payload.get("hook_event_name") or os.getenv("CODEX_HOOK_EVENT", ""))
        mapping = {"DashboardProcessStart": "started", "DashboardProcessEnd": "finished",
                   "SessionStart": "started", "UserPromptSubmit": "working",
                   "PreToolUse": "working", "PostToolUse": "working",
                   "Stop": "waiting_for_input"}
        event_type = mapping.get(native) or mapping.get(native[:1].upper() + native[1:])
        if not event_type:
            return 0
        session_id = str(os.getenv("AGENT_DASHBOARD_INSTANCE_ID") or payload.get("session_id") or payload.get("thread_id")
                         or payload.get("conversation_id") or payload.get("id") or "codex-session")
        host = (os.getenv("AGENT_DASHBOARD_HOST_ID") or config.get("host_id")
                or os.getenv("HOSTNAME") or socket.gethostname())
        cwd = str(Path(payload.get("cwd") or os.getcwd()).resolve())
        prompt = payload.get("prompt") or payload.get("message")
        event = {"event_id": str(uuid4()), "agent_id": session_id, "session_id": session_id,
                 "event_type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(),
                 "host_id": host, "working_dir": cwd, "harness": "codex",
                 "location": {"kind": "tmux", "pane": os.getenv("TMUX_PANE", "unknown")},
                 "message": str(prompt) if prompt else None, "model": payload.get("model")}
        endpoint = (os.getenv("AGENT_DASHBOARD_URL") or config.get("url")
                    or "http://127.0.0.1:8000").rstrip("/") + "/api/v1/events"
        headers = {"Content-Type": "application/json"}
        token = os.getenv("AGENT_DASHBOARD_TOKEN") or config.get("token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(endpoint, data=json.dumps(event).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=2):
            pass
    except Exception as exc:
        print(f"agent-dashboard codex hook: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
