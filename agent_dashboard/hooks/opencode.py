import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..models import AgentEvent


class OpenCodeHook:
    """Translate OpenCode lifecycle payloads and deliver them best-effort."""

    event_types = {"session.created": "started", "session.started": "started",
                   "session.updated": "working", "session.waiting": "waiting_for_input",
                   "session.completed": "finished", "session.error": "error",
                   "message.created": "message"}

    def __init__(self, endpoint: str, *, token: str | None = None, host_id: str | None = None,
                 working_dir: str | Path = ".", location: dict[str, Any] | None = None):
        self.endpoint = endpoint.rstrip("/") + "/api/v1/events"
        self.token = token
        self.host_id = socket.gethostname() if not host_id or host_id == "unknown-host" else host_id
        self.working_dir = str(Path(working_dir).resolve())
        self.location = {"kind": "tmux", "pane": (location or {}).get("pane", "unknown")}

    def normalize(self, payload: dict[str, Any]) -> AgentEvent:
        native_type = payload.get("type") or payload.get("event")
        event_type = self.event_types.get(native_type, native_type)
        if event_type not in {"started", "working", "waiting_for_input", "message", "finished", "error"}:
            raise ValueError(f"unsupported OpenCode event: {native_type}")
        timestamp = payload.get("timestamp") or datetime.now(timezone.utc).isoformat()
        return AgentEvent(event_id=uuid4(), agent_id=str(payload.get("agent_id") or payload["sessionID"]),
                          session_id=str(payload.get("session_id") or payload["sessionID"]), event_type=event_type,
                          timestamp=timestamp, host_id=self.host_id, working_dir=self.working_dir, harness="opencode",
                          location=self.location, model=payload.get("model"),
                          chat_title=payload.get("title") or payload.get("chat_title"),
                          message=payload.get("message"))

    def send(self, payload: dict[str, Any]) -> bool:
        try:
            event = self.normalize(payload)
            body = json.dumps(event.model_dump(mode="json")).encode()
            headers = {"Content-Type": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=2) as response:
                return 200 <= response.status < 300
        except (KeyError, ValueError, OSError, urllib.error.URLError):
            return False
