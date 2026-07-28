import asyncio
import base64
import json
import os
import socket
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Response

from .actions import HyprlandAdapter, TmuxAdapter
from .models import AgentEvent, TmuxLocation


def basic_auth_header(username: str | None, password: str | None) -> dict[str, str]:
    """Build the nginx-compatible Basic authorization header."""
    if username is None and password is None:
        return {}
    if not username or password is None:
        raise ValueError("basic auth requires both username and password")
    if ":" in username:
        raise ValueError("basic auth username cannot contain ':'")
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


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
                 tmux: TmuxAdapter | None = None, username: str | None = None,
                 password: str | None = None):
        self.notifier = notifier
        self.auth_headers = basic_auth_header(username, password)
        host = helper_host or os.environ.get("AGENT_DASHBOARD_HOST_ID", socket.gethostname())
        hyprland = HyprlandAdapter()
        self.tmux = tmux or TmuxAdapter(host, hyprland=hyprland)

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
        else:
            raise ValueError("unsupported focus location")
        return {"type": "result", "ok": True}

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
        async with websockets.connect(
            endpoint, additional_headers=self.auth_headers or None,
        ) as websocket:
            await websocket.send(json.dumps({"type": "register", "host_id": host_id}))
            await self.serve(websocket)

    async def connect_forever(self, server_url: str, host_id: str):
        """Reconnect to the central server while this workstation helper runs."""
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


def create_helper_app(helper: WorkstationHelper, *, server_url: str, host_id: str) -> FastAPI:
    """Create the database-free loopback API used by harness plugins."""

    connector_task: asyncio.Task | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        nonlocal connector_task
        connector_task = asyncio.create_task(helper.connect_forever(server_url, host_id))
        yield
        connector_task.cancel()
        await asyncio.gather(connector_task, return_exceptions=True)

    app = FastAPI(title="Agent Dashboard Workstation Helper", version="1", lifespan=lifespan)

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok", "role": "helper", "host_id": host_id}

    @app.post("/api/v1/events")
    async def forward_event(event: AgentEvent):
        endpoint = f"{server_url.rstrip('/')}/api/v1/events"
        # The helper owns workstation identity; plugins cannot accidentally
        # route commands to a different helper through a stale environment.
        event = event.model_copy(update={"host_id": host_id})
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.post(
                    endpoint,
                    content=event.model_dump_json(),
                    headers={"Content-Type": "application/json", **helper.auth_headers},
                )
        except httpx.HTTPError as exc:
            return Response(
                json.dumps({"detail": f"central server unavailable: {exc}"}),
                status_code=502,
                media_type="application/json",
            )
        return Response(
            response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/json"),
        )

    return app


def run_helper(*, server_url: str, host_id: str, host: str = "127.0.0.1",
               port: int = 8000, username: str | None = None,
               password: str | None = None) -> None:
    """Run a loopback event relay and outbound workstation command connection.

    The helper constructs no database. Its local HTTP endpoint exists only so
    harness plugins never need central-server credentials or network access.
    """
    helper = WorkstationHelper(
        DbusNotifier(), helper_host=host_id, username=username, password=password,
    )
    app = create_helper_app(helper, server_url=server_url, host_id=host_id)
    try:
        uvicorn.run(app, host=host, port=port)
    except KeyboardInterrupt:
        pass
