"""Best-effort Hermes lifecycle plugin adapter for Agent Dashboard."""
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
             effort: str | None = None, message_role: str | None = None,
             message: str | None = None) -> bool:
        body = {"event_id": str(uuid4()), "agent_id": session_id, "session_id": session_id,
                "event_type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(),
                "host_id": self.host_id, "harness": "hermes", "working_dir": self.working_dir,
                "location": self.location, "model": model, "effort": effort,
                "message_role": message_role, "message": message}
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

    @staticmethod
    def _configured_effort(model: str | None) -> str | None:
        """Resolve effort through Hermes's own model-aware config machinery."""
        try:
            from hermes_cli.config import load_config_readonly
            from hermes_constants import resolve_reasoning_config

            reasoning = resolve_reasoning_config(load_config_readonly(), model or "")
            if not isinstance(reasoning, dict):
                return None
            if reasoning.get("enabled") is False:
                return "none"
            effort = reasoning.get("effort")
            return str(effort) if effort is not None else None
        except (ImportError, OSError, TypeError, ValueError):
            # Keep the plugin importable for packaging/tests and fail open if
            # Hermes changes an internal config API.
            return None

    @classmethod
    def _effort(cls, kwargs: dict, model: str | None = None) -> str | None:
        for key in ("reasoning_effort", "effort", "thinking_level"):
            value = kwargs.get(key)
            if value is not None:
                return str(value)
        reasoning = kwargs.get("reasoning_config")
        if isinstance(reasoning, dict):
            value = reasoning.get("effort") or reasoning.get("reasoning_effort")
            if value is not None:
                return str(value)
            if reasoning.get("enabled") is False:
                return "none"
        return cls._configured_effort(model)

    def ensure_started(self, session_id: str, model: str | None = None,
                       effort: str | None = None) -> None:
        with self.lock:
            if session_id in self.active:
                return
            self.active.add(session_id)
            self.finished.discard(session_id)
        self.send(session_id, "waiting_for_input", model=model, effort=effort)

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

    def on_session_start(self, session_id: str, model: str | None = None,
                         platform: str | None = None, **kwargs) -> None:
        self.ensure_started(str(session_id), model, self._effort(kwargs, model))

    def pre_llm_call(self, session_id: str, user_message: str | None = None,
                     conversation_history=None, is_first_turn: bool = False,
                     model: str | None = None, platform: str | None = None,
                     **kwargs) -> None:
        session_id = str(session_id)
        effort = self._effort(kwargs, model)
        self.ensure_started(session_id, model, effort)
        if user_message:
            self.send(session_id, "message", model=model, effort=effort,
                      message_role="user", message=str(user_message)[-10000:])
        self.send(session_id, "working", model=model, effort=effort)

    def post_llm_call(self, session_id: str, user_message: str | None = None,
                      assistant_response: str | None = None, conversation_history=None,
                      model: str | None = None, platform: str | None = None,
                      **kwargs) -> None:
        session_id = str(session_id)
        effort = self._effort(kwargs, model)
        self.ensure_started(session_id, model, effort)
        if assistant_response:
            self.send(session_id, "message", model=model, effort=effort,
                      message_role="assistant", message=str(assistant_response)[-10000:])
        self.send(session_id, "waiting_for_input", model=model, effort=effort)

    def on_session_end(self, session_id: str, completed: bool = True, interrupted: bool = False,
                       model: str | None = None, platform: str | None = None,
                       **kwargs) -> None:
        # Hermes emits this after every run_conversation call as well as CLI
        # exit, so it is a turn boundary rather than a reliable terminal event.
        if interrupted:
            self.send(str(session_id), "waiting_for_input", model=model)
        elif not completed:
            self.send(str(session_id), "error", model=model)

    def on_session_finalize(self, session_id: str | None = None,
                            platform: str | None = None, **kwargs) -> None:
        if session_id is None:
            self.finish_all()
        else:
            self.finish(str(session_id))

    def on_session_reset(self, session_id: str, platform: str | None = None,
                         **kwargs) -> None:
        # Hermes passes the newly allocated ID after finalizing the old one.
        self.ensure_started(str(session_id))
