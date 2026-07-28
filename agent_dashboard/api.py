import asyncio
import json
import os
import socket
import re
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response, StreamingResponse
from pathlib import Path
from uuid import UUID

from .db import Database, default_database_path
from .models import (AgentEvent, AgentState, ArchiveRequest, EventAccepted, FocusRequest, NativeNotificationAction,
                     NotificationDecision, NotificationMessage, NotificationRule,
                     NtfyNotificationAction, SeenRequest, Snapshot, WebPushNotificationAction)
from .notifications import (NativeAdapter, NtfyAdapter, NotificationQueue, WebPushAdapter,
                            notification_message)
from .rules import evaluate
from .helper import DbusNotifier, WorkstationHelper


def create_app(database: Database | None = None, *, workstation: WorkstationHelper | None = None,
               host_id: str | None = None, main_server_url: str | None = None) -> FastAPI:
    db = database or Database()
    subscribers: dict[asyncio.Queue[dict], str] = {}
    workstations: dict[str, WebSocket] = {}
    local_host = host_id or os.environ.get("AGENT_DASHBOARD_HOST_ID", socket.gethostname())
    workstation = workstation or WorkstationHelper(DbusNotifier(), helper_host=local_host)
    main_server_url = main_server_url or os.environ.get("AGENT_DASHBOARD_MAIN_SERVER", "http://127.0.0.1:8000")
    connector_task: asyncio.Task | None = None
    delivery_worker: asyncio.Task | None = None
    deliveries = NotificationQueue([])

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
        nonlocal connector_task, delivery_worker
        connector_task = asyncio.create_task(workstation.connect_forever(main_server_url, local_host))
        delivery_worker = asyncio.create_task(delivery_loop())
        yield
        await disconnect_sse_clients()
        if connector_task:
            connector_task.cancel()
            await asyncio.gather(connector_task, return_exceptions=True)
        if delivery_worker:
            delivery_worker.cancel()
            await asyncio.gather(delivery_worker, return_exceptions=True)
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

    async def send_native(message: NotificationMessage, host: str) -> None:
        websocket = workstations.get(host)
        if websocket is None:
            raise RuntimeError(f"no workstation server connected for host {host}")
        await websocket.send_json({"type": "notify", "title": message.title, "body": message.body})

    async def send_webpush(message: NotificationMessage, client_id: str) -> None:
        payload = {"type": "notification", "notification": message.model_dump(mode="json")}
        for queue, connected_client_id in list(subscribers.items()):
            if connected_client_id == client_id and not queue.full():
                queue.put_nowait(payload)

    async def delivery_loop():
        while True:
            if await deliveries.run_once() is None:
                await asyncio.sleep(0.05)

    async def queue_notifications(event: AgentEvent, state, rules: list[NotificationRule]):
        for rule in rules:
            for action in rule.actions:
                if isinstance(action, NativeNotificationAction):
                    for target_host in list(workstations):
                        if re.search(action.hostname_regex, target_host):
                            message = notification_message(event, state, channel="native")
                            await deliveries.enqueue(message, NativeAdapter(
                                lambda item, host=target_host: send_native(item, host)))
                elif isinstance(action, WebPushNotificationAction):
                    for client_id in set(subscribers.values()):
                        if re.search(action.client_ids_regex, client_id):
                            message = notification_message(event, state, channel="webpush")
                            await deliveries.enqueue(message, WebPushAdapter(
                                lambda item, target=client_id: send_webpush(item, target)))
                elif isinstance(action, NtfyNotificationAction):
                    message = notification_message(event, state, channel="ntfy", topic=action.topic)
                    await deliveries.enqueue(message, NtfyAdapter(action.topic, server=str(action.server)))

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
        matched_rules = evaluate(db.rules(), event, state)
        decisions = [NotificationDecision(rule_id=rule.rule_id, rule_name=rule.name, actions=rule.actions)
                     for rule in matched_rules]
        payload = {"type": "agent.updated", "agent": state.model_dump(mode="json"),
                   "event": event.model_dump(mode="json"),
                   "notifications": [decision.model_dump(mode="json") for decision in decisions]}
        for queue in list(subscribers):
            if not queue.full():
                queue.put_nowait(payload)
        await queue_notifications(event, state, matched_rules)
        return payload

    @app.get("/api/v1/agents", response_model=Snapshot)
    async def agents():
        return Snapshot(agents=db.snapshot())

    @app.get("/api/v1/search/agents", response_model=list[str])
    async def search_agents(q: str = Query(min_length=1, max_length=500)):
        return db.search_agent_messages(q)

    @app.get("/api/v1/agents/{agent_id}/events", response_model=list[AgentEvent])
    async def agent_events(agent_id: str):
        if db.agent(agent_id) is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return db.events_for_agent(agent_id)

    async def broadcast_agent(state: AgentState) -> None:
        payload = {"type": "agent.updated", "agent": state.model_dump(mode="json")}
        for queue in list(subscribers):
            if not queue.full():
                queue.put_nowait(payload)

    @app.post("/api/v1/agents/seen-all", response_model=Snapshot)
    async def mark_all_agents_seen():
        agents = db.mark_all_seen()
        for agent in agents:
            await broadcast_agent(agent)
        return Snapshot(agents=agents)

    @app.post("/api/v1/agents/{agent_id}/seen", response_model=AgentState)
    async def set_agent_seen(agent_id: str, request: SeenRequest):
        agent = db.set_seen(agent_id, request.seen)
        if agent is None:
            raise HTTPException(status_code=404, detail="agent not found")
        await broadcast_agent(agent)
        return agent

    @app.post("/api/v1/agents/{agent_id}/archive", response_model=AgentState)
    async def set_agent_archived(agent_id: str, request: ArchiveRequest):
        agent = db.set_archived(agent_id, request.archived)
        if agent is None:
            raise HTTPException(status_code=404, detail="agent not found")
        await broadcast_agent(agent)
        return agent

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

    # A Vite build is preferred in production. The server auto-builds
    # frontend assets on startup when web_dist/ is missing (see
    # server._ensure_frontend_built). The checked-in static prototype
    # in web/ serves as a fallback so the API remains usable before
    # frontend dependencies are installed or during package development.
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
        client_id = getattr(request, "query_params", {}).get("client_id", "anonymous")[:200]
        subscribers[queue] = client_id
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
            subscribers.pop(queue, None)

    app.state.sse_events = events

    @app.get("/api/v1/events/stream")
    async def stream(request: Request):
        return StreamingResponse(events(request), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache, no-transform",
                                          "Connection": "keep-alive",
                                          "X-Accel-Buffering": "no"})

    return app


app = create_app(Database(os.environ.get("AGENT_DASHBOARD_DB") or default_database_path()))
