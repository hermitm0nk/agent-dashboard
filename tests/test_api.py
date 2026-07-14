import json
import sys
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_models import make_event
from agent_dashboard.models import NotificationRule


@pytest.mark.asyncio
async def test_event_ingestion_and_snapshot_e2e(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        event = make_event(event_id=uuid4(), event_type="waiting_for_input")
        response = await client.post("/api/v1/events", json=event.model_dump(mode="json"))
        assert response.status_code == 202
        assert response.json()["agent"]["status"] == "waiting_for_input"

        snapshot = await client.get("/api/v1/agents")
        assert snapshot.status_code == 200
        assert snapshot.json()["agents"][0]["agent_id"] == "agent-1"


@pytest.mark.asyncio
async def test_sse_stream_starts_with_ready_event(app):
    class DisconnectedRequest:
        async def is_disconnected(self):
            return True

    stream = app.state.sse_events(DisconnectedRequest())
    assert await stream.__anext__() == "event: ready\ndata: {}\n\n"
    await stream.aclose()


@pytest.mark.asyncio
async def test_web_ui_and_notification_rules_e2e(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/")
        assert page.status_code == 200
        assert "Agent Dashboard" in page.text
        assert (await client.get("/web/app.js")).status_code == 200
        assert (await client.get("/web/missing.js")).status_code == 404

        rule = NotificationRule(rule_id=uuid4(), name="Need attention", action="silence",
                                status="waiting_for_input")
        assert (await client.post("/api/v1/rules", json=rule.model_dump(mode="json"))).status_code == 201
        event = make_event(event_id=uuid4(), event_type="waiting_for_input")
        response = await client.post("/api/v1/events", json=event.model_dump(mode="json"))
        assert response.status_code == 202
        assert response.json()["notifications"][0]["action"] == "silence"


@pytest.mark.skipif(sys.version_info >= (3, 13), reason="legacy Starlette TestClient deadlocks on WebSocket teardown")
def test_helper_websocket_registration_e2e(app):
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/helpers/helper-1") as socket:
            socket.send_json({"type": "register", "helper_id": "helper-1", "capabilities": ["dbus"]})
            assert socket.receive_json() == {"type": "registered", "helper_id": "helper-1"}
            socket.close()


@pytest.mark.asyncio
async def test_duplicate_event_is_idempotent(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        event = make_event(event_id=uuid4(), event_type="waiting_for_input")
        body = event.model_dump(mode="json")
        assert (await client.post("/api/v1/events", json=body)).status_code == 202
        duplicate = await client.post("/api/v1/events", json=body)
        assert duplicate.status_code == 202
        assert duplicate.json()["notifications"] == []
