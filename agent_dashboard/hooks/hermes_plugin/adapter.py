"""Best-effort Hermes lifecycle adapter for Agent Dashboard."""
import atexit
import json
import os
import socket
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class DashboardAdapter:
    def __init__(self) -> None:
        config = self._config()
        self.endpoint = (os.getenv("AGENT_DASHBOARD_URL") or config.get("url")
                         or "http://127.0.0.1:8000").rstrip("/") + "/api/v1/events"
        self.token = os.getenv("AGENT_DASHBOARD_TOKEN") or config.get("token")
        self.host_id = (os.getenv("AGENT_DASHBOARD_HOST_ID") or config.get("host_id")
                        or socket.gethostname())
        self.working_dir = os.getcwd()
        self.location = {"kind": "tmux", "pane": os.getenv("TMUX_PANE", "unknown")}
        self.active: set[str] = set()
        self.finished: set[str] = set()
        self.lock = threading.Lock()
        atexit.register(self.finish_all)

    @staticmethod
    def _config() -> dict[str, str]:
        try:
            data = json.loads((Path.home() / ".hermes" / "agent-dashboard.json").read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def send(self, session_id: str, event_type: str, *, model: str | None = None,
             message: str | None = None) -> bool:
        body = {"event_id": str(uuid4()), "agent_id": session_id, "session_id": session_id,
                "event_type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(),
                "host_id": self.host_id, "harness": "hermes", "working_dir": self.working_dir,
                "location": self.location, "model": model, "message": message}
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            request = urllib.request.Request(self.endpoint, data=json.dumps(body).encode(),
                                             headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=2):
                return True
        except (OSError, urllib.error.URLError, ValueError):
            return False

    def ensure_started(self, session_id: str, model: str | None = None) -> None:
        with self.lock:
            if session_id in self.active:
                return
            self.active.add(session_id)
            self.finished.discard(session_id)
        self.send(session_id, "started", model=model)

    def finish(self, session_id: str) -> None:
        with self.lock:
            if session_id in self.finished:
                return
            self.finished.add(session_id)
            self.active.discard(session_id)
        self.send(session_id, "finished")

    def finish_all(self) -> None:
        with self.lock:
            sessions = list(self.active)
        for session_id in sessions:
            self.finish(session_id)

    def on_session_start(self, session_id: str, model: str | None = None, **kwargs) -> None:
        self.ensure_started(str(session_id), model)

    def pre_llm_call(self, session_id: str, model: str | None = None, **kwargs) -> None:
        session_id = str(session_id)
        self.ensure_started(session_id, model)
        self.send(session_id, "working", model=model)

    def post_llm_call(self, session_id: str, assistant_response: str | None = None,
                      model: str | None = None, **kwargs) -> None:
        session_id = str(session_id)
        self.ensure_started(session_id, model)
        if assistant_response:
            self.send(session_id, "message", model=model, message=str(assistant_response)[-10000:])
        self.send(session_id, "waiting_for_input", model=model)

    def on_session_end(self, session_id: str, completed: bool = True, interrupted: bool = False,
                       model: str | None = None, **kwargs) -> None:
        # Hermes emits this after every run_conversation call as well as CLI
        # exit, so it is a turn boundary rather than a reliable terminal event.
        if interrupted:
            self.send(str(session_id), "waiting_for_input", model=model)
        elif not completed:
            self.send(str(session_id), "error", model=model)

    def on_session_finalize(self, session_id: str | None = None, **kwargs) -> None:
        if session_id is None:
            self.finish_all()
        else:
            self.finish(str(session_id))

    def on_session_reset(self, session_id: str, **kwargs) -> None:
        # Hermes passes the newly allocated ID after finalizing the old one.
        self.ensure_started(str(session_id))
