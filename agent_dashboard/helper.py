import asyncio
import json
import os
import socket
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from .actions import FirefoxAdapter, HyprlandAdapter, TmuxAdapter
from .models import FirefoxLocation, TmuxLocation


class DbusNotifier:
    """Send desktop notifications through the user's session bus."""

    name = "dbus"

    def __init__(self, runner: Callable[..., Awaitable[Any]] | None = None,
                 *, app_name: str = "Agent Dashboard"):
        self.runner = runner or self._run
        self.app_name = app_name

    async def _run(self, *args: str):
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE)
        await process.communicate()
        if process.returncode:
            raise RuntimeError(f"notify-send exited with {process.returncode}")

    async def notify(self, title: str, body: str):
        await self.runner("notify-send", "--app-name", self.app_name, "--", title, body)


class WorkstationHelper:
    """Outbound-only helper command dispatcher with a strict allowlist."""

    allowed = {"notify", "focus"}

    def __init__(self, notifier: DbusNotifier, *, helper_host: str | None = None,
                 tmux: TmuxAdapter | None = None, firefox: FirefoxAdapter | None = None):
        self.notifier = notifier
        host = helper_host or os.environ.get("AGENT_DASHBOARD_HOST_ID", socket.gethostname())
        hyprland = HyprlandAdapter()
        self.tmux = tmux or TmuxAdapter(host, hyprland=hyprland)
        self.firefox = firefox or FirefoxAdapter(helper_host=host, hyprland=hyprland)

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

    async def focus(self, *, agent_id: str, origin_host: str, location: dict[str, Any]) -> dict[str, Any]:
        """Execute a focus command locally for the combined server endpoint."""
        return await self.handle(json.dumps({"type": "focus", "agent_id": agent_id,
                                             "origin_host": origin_host, "location": location}))

    async def serve(self, websocket):
        async for raw in websocket:
            try:
                command = json.loads(raw)
                if command.get("type") == "registered":
                    continue
                result = await self.handle(json.dumps(command))
            except Exception as exc:
                result = {"type": "result", "ok": False, "error": str(exc)}
            await websocket.send(json.dumps(result))

    async def connect(self, server_url: str, host_id: str):
        """Connect to the main server and process workstation commands."""
        endpoint = server_url.rstrip("/").replace("https://", "wss://").replace("http://", "ws://")
        endpoint = f"{endpoint}/api/v1/workstations/{host_id}"
        async with websockets.connect(endpoint) as websocket:
            await websocket.send(json.dumps({"type": "register", "host_id": host_id}))
            await self.serve(websocket)

    async def connect_forever(self, server_url: str, host_id: str):
        """Reconnect to the main server while this workstation server runs."""
        delay = 1.0
        while True:
            try:
                await self.connect(server_url, host_id)
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
