import asyncio
import json
import socket
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from .actions import FirefoxAdapter, TmuxAdapter
from .models import FirefoxLocation, TmuxLocation


class DbusNotifier:
    """Send desktop notifications through the user's session bus."""

    name = "dbus"

    def __init__(self, runner: Callable[..., Awaitable[Any]] | None = None):
        self.runner = runner or self._run

    async def _run(self, *args: str):
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE)
        await process.communicate()
        if process.returncode:
            raise RuntimeError(f"notify-send exited with {process.returncode}")

    async def notify(self, title: str, body: str):
        await self.runner("notify-send", "--", title, body)


class WorkstationHelper:
    """Outbound-only helper command dispatcher with a strict allowlist."""

    allowed = {"notify", "focus"}

    def __init__(self, notifier: DbusNotifier, *, helper_host: str | None = None,
                 tmux: TmuxAdapter | None = None, firefox: FirefoxAdapter | None = None):
        self.notifier = notifier
        host = helper_host or socket.gethostname()
        self.tmux = tmux or TmuxAdapter(host)
        self.firefox = firefox or FirefoxAdapter(helper_host=host)

    async def handle(self, raw: str | bytes) -> dict[str, Any]:
        command = json.loads(raw)
        if command.get("type") == "notify":
            if set(command) - {"type", "title", "body"} or not isinstance(command.get("title"), str) or not isinstance(command.get("body"), str):
                raise ValueError("invalid notification command")
            await self.notifier.notify(command["title"], command["body"])
            return {"type": "result", "ok": True}
        if command.get("type") != "focus" or set(command) - {"type", "agent_id", "origin_host", "location"}:
            raise ValueError("unknown helper command")
        location = command["location"]
        if location.get("kind") == "tmux":
            await self.tmux.go_to(TmuxLocation.model_validate(location), origin_host=command["origin_host"], agent_id=command["agent_id"])
        elif location.get("kind") == "firefox":
            await self.firefox.go_to(FirefoxLocation.model_validate(location), origin_host=command["origin_host"])
        else:
            raise ValueError("unsupported focus location")
        return {"type": "result", "ok": True}

    async def serve(self, websocket):
        async for raw in websocket:
            try:
                result = await self.handle(raw)
            except Exception as exc:
                result = {"type": "result", "ok": False, "error": str(exc)}
            await websocket.send(json.dumps(result))

    async def connect(self, server_url: str, helper_id: str, capabilities: list[str] | None = None):
        """Connect outbound to the server and process commands until closed."""
        async with websockets.connect(server_url) as websocket:
            await websocket.send(json.dumps({"type": "register", "helper_id": helper_id,
                                              "capabilities": capabilities or ["dbus"]}))
            await self.serve(websocket)
