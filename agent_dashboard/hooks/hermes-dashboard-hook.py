#!/usr/bin/env python3
"""Hermes shell hook: translate Hermes hook JSON into dashboard events."""
import json
import os
import socket
import sys
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        event_type = {"on_session_start": "started", "pre_llm_call": "working",
                      "post_llm_call": "waiting_for_input", "on_session_end": "finished",
                      "on_session_finalize": "finished"}.get(
                          payload.get("hook_event_name", ""))
        if not event_type:
            print("{}")
            return
        session_id = str(payload.get("session_id") or "hermes-session")
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        message = extra.get("response") or extra.get("assistant_message")
        body = {"event_id": str(uuid4()), "agent_id": session_id, "session_id": session_id,
                "event_type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(),
                "host_id": os.getenv("AGENT_DASHBOARD_HOST_ID", socket.gethostname()), "harness": "hermes",
                "working_dir": payload.get("cwd") or os.getcwd(),
                "location": {"kind": "tmux", "pane": os.getenv("TMUX_PANE", "unknown")},
                "model": extra.get("model"), "message": str(message) if message else None}
        request = urllib.request.Request(
            os.getenv("AGENT_DASHBOARD_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1/events",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=2):
            pass
    except Exception as exc:  # hook failures must never stop Hermes
        print(f"agent-dashboard hook: {exc}", file=sys.stderr)
    print("{}")


if __name__ == "__main__":
    main()
