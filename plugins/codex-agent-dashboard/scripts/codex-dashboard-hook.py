#!/usr/bin/env python3
"""Best-effort Codex hook forwarding native lifecycle and chat events."""
import json
import os
import socket
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def dashboard_config() -> dict[str, str]:
    try:
        data = json.loads((Path.home() / ".codex" / "agent-dashboard.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def transcript_metadata(path_value: object) -> dict[str, str]:
    """Read the latest model/effort recorded in Codex's native JSONL transcript."""
    if not path_value:
        return {}
    result: dict[str, str] = {}
    try:
        with Path(str(path_value)).open(encoding="utf-8") as transcript:
            for line in transcript:
                try:
                    item = json.loads(line)
                except (ValueError, TypeError):
                    continue
                payload = item.get("payload")
                if not isinstance(payload, dict):
                    continue
                if item.get("type") == "turn_context":
                    if payload.get("model"):
                        result["model"] = str(payload["model"])
                    if payload.get("effort"):
                        result["effort"] = str(payload["effort"])
                elif (item.get("type") == "event_msg"
                      and payload.get("type") == "thread_settings_applied"):
                    if payload.get("model"):
                        result["model"] = str(payload["model"])
                    if payload.get("reasoning_effort"):
                        result["effort"] = str(payload["reasoning_effort"])
    except OSError:
        pass
    return result


def post(endpoint: str, headers: dict[str, str], base: dict, event_type: str,
         *, message: object = None, message_role: str | None = None) -> None:
    event = {**base, "event_id": str(uuid4()), "event_type": event_type,
             "timestamp": datetime.now(timezone.utc).isoformat()}
    if message:
        event["message"] = str(message)[-10000:]
    if message_role:
        event["message_role"] = message_role
    request = urllib.request.Request(endpoint, data=json.dumps(event).encode(),
                                     headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=2):
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        native = str(payload.get("hook_event_name") or os.getenv("CODEX_HOOK_EVENT", ""))
        if native not in {
            "DashboardProcessStart", "DashboardProcessEnd",
            "SessionStart", "UserPromptSubmit", "Stop", "SessionEnd",
        }:
            return 0
        config = dashboard_config()
        session_id = str(payload.get("session_id") or payload.get("thread_id")
                         or payload.get("conversation_id") or payload.get("id")
                         or "codex-session")
        agent_id = str(os.getenv("AGENT_DASHBOARD_INSTANCE_ID") or session_id)
        metadata = transcript_metadata(payload.get("transcript_path"))
        model = payload.get("model") or metadata.get("model")
        base = {
            "agent_id": agent_id,
            "session_id": session_id,
            "host_id": (os.getenv("AGENT_DASHBOARD_HOST_ID") or config.get("host_id")
                        or os.getenv("HOSTNAME") or socket.gethostname()),
            "working_dir": str(Path(payload.get("cwd") or os.getcwd()).resolve()),
            "harness": "codex",
            "location": {"kind": "tmux", "pane": os.getenv("TMUX_PANE", "unknown")},
            "model": model,
            "effort": metadata.get("effort"),
        }
        endpoint = (os.getenv("AGENT_DASHBOARD_URL") or config.get("url")
                    or "http://127.0.0.1:8000").rstrip("/") + "/api/v1/events"
        headers = {"Content-Type": "application/json"}

        if native == "DashboardProcessStart":
            post(endpoint, headers, base, "waiting_for_input")
        elif native == "DashboardProcessEnd":
            post(endpoint, headers, base, "finished")
        elif native == "SessionStart":
            post(endpoint, headers, base, "waiting_for_input")
        elif native == "UserPromptSubmit":
            if payload.get("prompt"):
                post(endpoint, headers, base, "message", message=payload["prompt"],
                     message_role="user")
            post(endpoint, headers, base, "working")
        elif native == "Stop":
            if payload.get("last_assistant_message"):
                post(endpoint, headers, base, "message",
                     message=payload["last_assistant_message"], message_role="assistant")
            post(endpoint, headers, base, "waiting_for_input")
        elif native == "SessionEnd":
            post(endpoint, headers, base, "finished")
    except Exception:
        # Hooks must never delay or interrupt Codex.
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
