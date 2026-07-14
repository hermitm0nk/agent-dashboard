import asyncio
import json
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import Response, StreamingResponse
from pathlib import Path
from uuid import UUID

from .db import Database
from .models import AgentEvent, EventAccepted, FocusRequest, NotificationDecision, NotificationRule, Snapshot
from .rules import evaluate


def create_app(database: Database | None = None) -> FastAPI:
    db = database or Database()
    subscribers: set[asyncio.Queue[dict]] = set()
    helpers: dict[str, WebSocket] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """Release long-lived helper sockets during server shutdown."""
        yield
        sockets = list(helpers.values())
        helpers.clear()
        for websocket in sockets:
            try:
                await websocket.close(code=1001, reason="server shutting down")
            except Exception:
                # The peer may already have gone away.
                pass

    app = FastAPI(title="Agent Dashboard API", version="1", lifespan=lifespan)

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    @app.websocket("/api/v1/helpers/{helper_id}")
    async def helper_socket(websocket: WebSocket, helper_id: str):
        await websocket.accept()
        helpers[helper_id] = websocket
        try:
            registration = await websocket.receive_json()
            if registration.get("type") != "register" or registration.get("helper_id") != helper_id:
                await websocket.close(code=1008)
                return
            await websocket.send_json({"type": "registered", "helper_id": helper_id})
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if helpers.get(helper_id) is websocket:
                helpers.pop(helper_id, None)

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
        helper_id = request.helper_id
        if helper_id is None:
            if len(helpers) != 1:
                raise HTTPException(status_code=400, detail="helper_id is required when multiple helpers are connected")
            helper_id = next(iter(helpers))
        helper = helpers.get(helper_id)
        if helper is None:
            raise HTTPException(status_code=409, detail="helper is not connected")
        await helper.send_json({"type": "focus", "agent_id": agent.agent_id,
                                "origin_host": agent.host_id,
                                "location": agent.location.model_dump(mode="json")})
        return {"status": "queued"}

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

    web_root = Path(__file__).parent / "web"

    @app.get("/", include_in_schema=False)
    async def web_index():
        return Response((web_root / "index.html").read_bytes(), media_type="text/html")

    @app.get("/web/{asset}", include_in_schema=False)
    async def web_asset(asset: str):
        candidate = (web_root / asset).resolve()
        if web_root not in candidate.parents or not candidate.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
        media_type = {".css": "text/css", ".js": "text/javascript"}.get(candidate.suffix)
        return Response(candidate.read_bytes(), media_type=media_type)

    async def events(request: Request) -> AsyncIterator[str]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        subscribers.add(queue)
        try:
            yield "event: ready\ndata: {}\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            subscribers.discard(queue)

    app.state.sse_events = events

    @app.get("/api/v1/events/stream")
    async def stream(request: Request):
        return StreamingResponse(events(request), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

    return app


app = create_app(Database(os.environ.get("AGENT_DASHBOARD_DB", ":memory:")))
