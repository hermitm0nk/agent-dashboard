import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
from uuid import UUID

from .db import Database
from .models import AgentEvent, EventAccepted, NotificationDecision, NotificationRule, Snapshot
from .rules import evaluate


def create_app(database: Database | None = None) -> FastAPI:
    db = database or Database()
    subscribers: set[asyncio.Queue[dict]] = set()
    app = FastAPI(title="Agent Dashboard API", version="1")

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/v1/events", response_model=EventAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def ingest(event: AgentEvent):
        state = db.record_event(event)
        decisions = [NotificationDecision(rule_id=rule.rule_id, action=rule.action, rule_name=rule.name)
                     for rule in evaluate(db.rules(), event, state)]
        payload = {"type": "agent.updated", "agent": state.model_dump(mode="json"),
                   "notifications": [decision.model_dump(mode="json") for decision in decisions]}
        for queue in list(subscribers):
            if not queue.full():
                queue.put_nowait(payload)
        return payload

    @app.get("/api/v1/agents", response_model=Snapshot)
    def agents():
        return Snapshot(agents=db.snapshot())

    @app.get("/api/v1/rules", response_model=list[NotificationRule])
    def rules():
        return db.rules()

    @app.post("/api/v1/rules", response_model=NotificationRule, status_code=status.HTTP_201_CREATED)
    def save_rule(rule: NotificationRule):
        return db.save_rule(rule)

    @app.delete("/api/v1/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_rule(rule_id: UUID):
        if not db.delete_rule(str(rule_id)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
        return None

    web_root = Path(__file__).parent / "web"

    @app.get("/", include_in_schema=False)
    def web_index():
        return FileResponse(web_root / "index.html")

    @app.get("/web/{asset}", include_in_schema=False)
    def web_asset(asset: str):
        candidate = (web_root / asset).resolve()
        if web_root not in candidate.parents:
            return status.HTTP_404_NOT_FOUND
        return FileResponse(candidate)

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


app = create_app()
