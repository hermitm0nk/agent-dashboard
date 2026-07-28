import json
from uuid import uuid4

import httpx
import pytest

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

        history = await client.get("/api/v1/agents/agent-1/events")
        assert history.status_code == 200
        assert history.json()[0]["event_id"] == str(event.event_id)


@pytest.mark.asyncio
async def test_sse_stream_starts_with_ready_event(app):
    class DisconnectedRequest:
        async def is_disconnected(self):
            return True

    stream = app.state.sse_events(DisconnectedRequest())
    assert await stream.__anext__() == "event: ready\ndata: {}\n\n"
    snapshot = await stream.__anext__()
    assert snapshot == 'event: snapshot\ndata: {"agents": []}\n\n'
    await stream.aclose()


@pytest.mark.asyncio
async def test_sse_stream_publishes_agent_updates(app):
    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    stream = app.state.sse_events(ConnectedRequest())
    assert await stream.__anext__() == "event: ready\ndata: {}\n\n"
    await stream.__anext__()  # initial snapshot
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        event = make_event(event_id=uuid4(), event_type="working")
        assert (await client.post("/api/v1/events", json=event.model_dump(mode="json"))).status_code == 202
    update = await stream.__anext__()
    assert update.startswith("event: agent.updated\ndata: ")
    assert json.loads(update.split("data: ", 1)[1])["agent"]["status"] == "working"
    await stream.aclose()


@pytest.mark.asyncio
async def test_sse_response_disables_proxy_buffering(app):
    class DisconnectedRequest:
        async def is_disconnected(self):
            return True

    route = next(route for route in app.routes if route.path == "/api/v1/events/stream")
    response = await route.endpoint(DisconnectedRequest())
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"


@pytest.mark.asyncio
async def test_server_can_disconnect_sse_clients(app):
    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    stream = app.state.sse_events(ConnectedRequest())
    assert await stream.__anext__() == "event: ready\ndata: {}\n\n"
    await stream.__anext__()  # initial snapshot
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/clients/disconnect")
        assert response.status_code == 200
        assert response.json()["count"] == 1
    assert await stream.__anext__() == "event: disconnect\ndata: {\"type\": \"disconnect\"}\n\n"
    await stream.aclose()


@pytest.mark.asyncio
async def test_server_shutdown_disconnects_sse_clients(app):
    class ConnectedRequest:
        async def is_disconnected(self):
            return False

    async with app.router.lifespan_context(app):
        stream = app.state.sse_events(ConnectedRequest())
        assert await stream.__anext__() == "event: ready\ndata: {}\n\n"
        await stream.__anext__()  # initial snapshot
    assert await stream.__anext__() == "event: disconnect\ndata: {\"type\": \"disconnect\"}\n\n"
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

        rule = NotificationRule(rule_id=uuid4(), name="Need attention",
                                match={"status": "waiting_for_input"},
                                actions=[{"type": "webpush", "client_ids_regex": ".*"}])
        assert (await client.post("/api/v1/rules", json=rule.model_dump(mode="json"))).status_code == 201
        event = make_event(event_id=uuid4(), event_type="waiting_for_input")
        response = await client.post("/api/v1/events", json=event.model_dump(mode="json"))
        assert response.status_code == 202
        assert response.json()["notifications"][0]["actions"][0]["type"] == "webpush"


@pytest.mark.asyncio
async def test_local_focus_requires_the_workstation_websocket(monkeypatch, database):
    from agent_dashboard import api
    calls = []

    class Workstation:
        async def focus(self, **command):
            calls.append(command)
            return {"type": "result", "ok": True}

    monkeypatch.setattr(api.socket, "gethostname", lambda: "host-1")
    application = api.create_app(database, workstation=Workstation())
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        event = make_event(event_id=uuid4(), event_type="working")
        assert (await client.post("/api/v1/events", json=event.model_dump(mode="json"))).status_code == 202
        response = await client.post("/api/v1/agents/agent-1/focus", json={})
    assert response.status_code == 502
    assert calls == []


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


@pytest.mark.asyncio
async def test_seen_state_requires_explicit_api_action(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        event = make_event(event_id=uuid4(), event_type="message",
                           message_role="assistant", message="Update")
        ingested = await client.post("/api/v1/events", json=event.model_dump(mode="json"))
        assert ingested.json()["agent"]["unseen"] is True

        # Reading history does not implicitly mark the conversation seen.
        assert (await client.get("/api/v1/agents/agent-1/events")).status_code == 200
        assert (await client.get("/api/v1/agents")).json()["agents"][0]["unseen"] is True

        seen = await client.post("/api/v1/agents/agent-1/seen", json={"seen": True})
        assert seen.status_code == 200
        assert seen.json()["unseen"] is False
        unseen = await client.post("/api/v1/agents/agent-1/seen", json={"seen": False})
        assert unseen.json()["unseen"] is True
        all_seen = await client.post("/api/v1/agents/seen-all")
        assert all_seen.status_code == 200
        assert all_seen.json()["agents"][0]["unseen"] is False


@pytest.mark.asyncio
async def test_agent_can_be_archived_and_restored_explicitly(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        event = make_event(event_id=uuid4(), event_type="working")
        await client.post("/api/v1/events", json=event.model_dump(mode="json"))
        archived = await client.post("/api/v1/agents/agent-1/archive", json={"archived": True})
        assert archived.status_code == 200
        assert archived.json()["archived"] is True
        restored = await client.post("/api/v1/agents/agent-1/archive", json={"archived": False})
        assert restored.status_code == 200
        assert restored.json()["archived"] is False


@pytest.mark.asyncio
async def test_agent_message_search_returns_bm25_ranked_sessions(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for agent_id, message in (
            ("focused", "rare phrase rare phrase rare phrase"),
            ("broad", "rare phrase mixed with several unrelated words"),
        ):
            event = make_event(
                event_id=uuid4(), agent_id=agent_id, session_id=f"{agent_id}-session",
                event_type="message", message_role="assistant", message=message,
            )
            await client.post("/api/v1/events", json=event.model_dump(mode="json"))
        response = await client.get("/api/v1/search/agents", params={"q": "rare phrase"})
        assert response.status_code == 200
        assert response.json() == ["focused", "broad"]
