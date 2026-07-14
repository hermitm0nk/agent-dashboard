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
        properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
        info = properties.get("info") if isinstance(properties.get("info"), dict) else {}
        session_id = (payload.get("session_id") or payload.get("sessionID")
                      or properties.get("sessionID") or properties.get("session_id")
                      or properties.get("id") or info.get("sessionID") or info.get("session_id"))
        if not session_id:
            raise ValueError("OpenCode event has no session ID")
        message = payload.get("message") or properties.get("message") or info.get("content")
        if isinstance(message, dict):
            message = message.get("text") or message.get("content")
        if isinstance(message, list):
            message = "\n".join(str(part.get("text", "")) for part in message
                                   if isinstance(part, dict) and part.get("type") == "text") or None
        return AgentEvent(event_id=uuid4(), agent_id=str(payload.get("agent_id") or session_id),
                          session_id=str(session_id), event_type=event_type,
                          timestamp=timestamp, host_id=self.host_id, working_dir=self.working_dir, harness="opencode",
                          location=self.location, model=payload.get("model"),
                          chat_title=payload.get("title") or payload.get("chat_title"),
                          message=str(message) if message is not None else None)

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
