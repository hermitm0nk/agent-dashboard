import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.responses import StreamingResponse

from .db import Database
from .models import AgentEvent, Snapshot


def create_app(database: Database | None = None) -> FastAPI:
    db = database or Database()
    subscribers: set[asyncio.Queue[dict]] = set()
    app = FastAPI(title="Agent Dashboard API", version="1")

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/v1/events", response_model=None, status_code=status.HTTP_202_ACCEPTED)
    async def ingest(event: AgentEvent):
        state = db.record_event(event)
        payload = {"type": "agent.updated", "agent": state.model_dump(mode="json")}
        for queue in list(subscribers):
            if not queue.full():
                queue.put_nowait(payload)
        return payload

    @app.get("/api/v1/agents", response_model=Snapshot)
    def agents():
        return Snapshot(agents=db.snapshot())

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
