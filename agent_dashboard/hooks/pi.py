import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..models import AgentEvent


class PiJsonHook:
    """Normalize records from Pi's documented ``--mode json`` stream."""

    def __init__(self, *, host_id: str | None = None, working_dir: str | Path, location: dict[str, Any]):
        self.host_id = socket.gethostname() if not host_id or host_id == "unknown-host" else host_id
        self.working_dir = str(Path(working_dir).resolve())
        self.location = location
        self.session_id: str | None = None

    def normalize(self, record: str | dict[str, Any]) -> AgentEvent | None:
        data = json.loads(record) if isinstance(record, str) else record
        if data.get("type") == "session":
            self.session_id = str(data["id"])
            return None
        if not self.session_id:
            raise ValueError("Pi event received before session header")
        event_type = {"agent_start": "working", "agent_end": "waiting_for_input",
                      "message_end": "message"}.get(data.get("type"))
        if not event_type:
            return None
        message = data.get("message", {})
        text = "\n".join(part.get("text", "") for part in message.get("content", [])
                          if part.get("type") == "text") or None
        timestamp = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
        return AgentEvent(event_id=uuid4(), agent_id=self.session_id, session_id=self.session_id, harness="pi",
                          event_type=event_type, timestamp=timestamp, host_id=self.host_id,
                          working_dir=self.working_dir, location=data.get("location", self.location),
                          model=data.get("model"), message=text)
