import asyncio
import json
import os
import socket
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response, StreamingResponse
from pathlib import Path
from uuid import UUID

from .db import Database
from .models import AgentEvent, EventAccepted, FocusRequest, NotificationDecision, NotificationRule, Snapshot
from .rules import evaluate
from .helper import DbusNotifier, WorkstationHelper


def create_app(database: Database | None = None, *, workstation: WorkstationHelper | None = None,
               host_id: str | None = None, main_server_url: str | None = None) -> FastAPI:
    db = database or Database()
    subscribers: set[asyncio.Queue[dict]] = set()
    workstations: dict[str, WebSocket] = {}
    local_host = host_id or os.environ.get("AGENT_DASHBOARD_HOST_ID", socket.gethostname())
    workstation = workstation or WorkstationHelper(DbusNotifier(), helper_host=local_host)
    main_server_url = main_server_url or os.environ.get("AGENT_DASHBOARD_MAIN_SERVER", "http://127.0.0.1:8000")
    connector_task: asyncio.Task | None = None

    async def disconnect_sse_clients() -> int:
        count = len(subscribers)
        for queue in list(subscribers):
            # Ensure shutdown cannot lose the control message behind queued
            # agent updates.
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait({"type": "disconnect"})
        return count

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """Release long-lived workstation sockets during server shutdown."""
        nonlocal connector_task
        connector_task = asyncio.create_task(workstation.connect_forever(main_server_url, local_host))
        yield
        await disconnect_sse_clients()
        if connector_task:
            connector_task.cancel()
            await asyncio.gather(connector_task, return_exceptions=True)
        sockets = list(workstations.values())
        workstations.clear()
        for websocket in sockets:
            try:
                await websocket.close(code=1001, reason="server shutting down")
            except Exception:
                # The peer may already have gone away.
                pass

    app = FastAPI(title="Agent Dashboard API", version="1", lifespan=lifespan)
    # Exposed for process runners that want to broadcast before initiating
    # their own signal-driven shutdown sequence.
    app.state.disconnect_clients = disconnect_sse_clients

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    @app.websocket("/api/v1/workstations/{host_id}")
    async def workstation_socket(websocket: WebSocket, host_id: str):
        await websocket.accept()
        try:
            registration = await websocket.receive_json()
            if registration.get("type") != "register" or registration.get("host_id") != host_id:
                await websocket.close(code=1008)
                return
            workstations[host_id] = websocket
            await websocket.send_json({"type": "registered", "host_id": host_id})
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if workstations.get(host_id) is websocket:
                workstations.pop(host_id, None)

    @app.post("/api/v1/events", response_model=EventAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def ingest(event: AgentEvent):
        state, inserted = db.record_event_if_new(event)
        if not inserted:
            return {"type": "agent.updated", "agent": state.model_dump(mode="json"), "notifications": []}
        decisions = [NotificationDecision(rule_id=rule.rule_id, action=rule.action, rule_name=rule.name)
                     for rule in evaluate(db.rules(), event, state)]
        payload = {"type": "agent.updated", "agent": state.model_dump(mode="json"),
                   "notifications": [decision.model_dump(mode="json") for decision in decisions]}
        for queue in list(subscribers):
            if not queue.full():
                queue.put_nowait(payload)
        return payload

    @app.get("/api/v1/agents", response_model=Snapshot)
    async def agents():
        return Snapshot(agents=db.snapshot())

    @app.post("/api/v1/agents/{agent_id}/focus", status_code=status.HTTP_202_ACCEPTED)
    async def focus_agent(agent_id: str, request: FocusRequest):
        agent = db.agent(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="agent not found")
        command = {"agent_id": agent.agent_id, "origin_host": agent.host_id,
                   "location": agent.location.model_dump(mode="json")}
        if agent.host_id in workstations:
            try:
                await workstations[agent.host_id].send_json({"type": "focus", **command})
            except (RuntimeError, WebSocketDisconnect) as exc:
                workstations.pop(agent.host_id, None)
                raise HTTPException(status_code=502, detail="remote workstation disconnected") from exc
        else:
            raise HTTPException(status_code=502,
                                detail=f"no workstation server connected for host {agent.host_id}")
        return {"status": "queued"}

    @app.post("/api/v1/workstation/focus", status_code=status.HTTP_202_ACCEPTED)
    async def workstation_focus(command: dict):
        """Execute a focus command on this machine's combined server."""
        if set(command) != {"agent_id", "origin_host", "location"}:
            raise HTTPException(status_code=400, detail="invalid workstation focus command")
        if (not isinstance(command["agent_id"], str) or not isinstance(command["origin_host"], str)
                or not isinstance(command["location"], dict)):
            raise HTTPException(status_code=400, detail="invalid workstation focus command")
        try:
            result = await workstation.focus(agent_id=command["agent_id"],
                                             origin_host=command["origin_host"],
                                             location=command["location"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not result.get("ok", False):
            raise HTTPException(status_code=502, detail=result.get("error", "focus failed"))
        return {"status": "completed"}

    @app.post("/api/v1/clients/disconnect")
    async def disconnect_clients():
        """Ask every TUI and web SSE client to close its connection."""
        count = await disconnect_sse_clients()
        return {"status": "disconnecting", "count": count}

    @app.get("/api/v1/rules", response_model=list[NotificationRule])
    async def rules():
        return db.rules()

    @app.post("/api/v1/rules", response_model=NotificationRule, status_code=status.HTTP_201_CREATED)
    async def save_rule(rule: NotificationRule):
        return db.save_rule(rule)

    @app.delete("/api/v1/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_rule(rule_id: UUID):
        if not db.delete_rule(str(rule_id)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
        return None

    # A Vite build is preferred in production. Keep the checked-in static
    # prototype as a fallback so the API remains usable before frontend
    # dependencies are installed or during package development.
    web_root = Path(__file__).parent / "web"
    built_web_root = Path(__file__).parent / "web_dist"
    served_web_root = built_web_root if (built_web_root / "index.html").is_file() else web_root

    @app.get("/", include_in_schema=False)
    async def web_index():
        return Response((served_web_root / "index.html").read_bytes(), media_type="text/html")

    @app.get("/web/{asset:path}", include_in_schema=False)
    async def web_asset(asset: str):
        candidate = (served_web_root / asset).resolve()
        if served_web_root not in candidate.parents or not candidate.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
        media_type = {".css": "text/css", ".js": "text/javascript"}.get(candidate.suffix)
        return Response(candidate.read_bytes(), media_type=media_type)

    async def events(request: Request) -> AsyncIterator[str]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        subscribers.add(queue)
        try:
            yield "event: ready\ndata: {}\n\n"
            snapshot = Snapshot(agents=db.snapshot()).model_dump(mode="json")
            yield f"event: snapshot\ndata: {json.dumps(snapshot)}\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n"
                    if payload["type"] == "disconnect":
                        return
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            subscribers.discard(queue)

    app.state.sse_events = events

    @app.get("/api/v1/events/stream")
    async def stream(request: Request):
        return StreamingResponse(events(request), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache, no-transform",
                                          "Connection": "keep-alive",
                                          "X-Accel-Buffering": "no"})

    return app


app = create_app(Database(os.environ.get("AGENT_DASHBOARD_DB", ":memory:")))
