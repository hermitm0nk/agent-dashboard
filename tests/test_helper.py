import json
from types import SimpleNamespace

import httpx
import pytest

from agent_dashboard.helper import (
    DbusNotifier,
    WorkstationHelper,
    basic_auth_header,
    create_helper_app,
)
from tests.test_models import make_event


@pytest.mark.asyncio
async def test_helper_allows_only_notification_command():
    calls = []

    async def runner(*args):
        calls.append(args)

    helper = WorkstationHelper(DbusNotifier(runner))
    result = await helper.handle(json.dumps({"type": "notify", "title": "Agent", "body": "Ready"}))
    assert result == {"type": "result", "ok": True}
    assert calls == [("notify-send", "--app-name", "Agent Dashboard", "--", "Agent", "Ready")]


@pytest.mark.asyncio
async def test_helper_rejects_unknown_fields():
    helper = WorkstationHelper(DbusNotifier(lambda *_: None))
    with pytest.raises(ValueError):
        await helper.handle('{"type":"exec","command":"rm -rf /"}')


def test_basic_auth_header_is_nginx_compatible():
    assert basic_auth_header("dashboard", "correct horse") == {
        "Authorization": "Basic ZGFzaGJvYXJkOmNvcnJlY3QgaG9yc2U="
    }
    assert basic_auth_header(None, None) == {}
    with pytest.raises(ValueError):
        basic_auth_header("dashboard", None)
    with pytest.raises(ValueError):
        basic_auth_header("invalid:user", "secret")


@pytest.mark.asyncio
async def test_helper_websocket_uses_basic_auth(monkeypatch):
    captured = {}

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send(self, raw):
            captured.setdefault("sent", []).append(json.loads(raw))

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    def connect(endpoint, **kwargs):
        captured["endpoint"] = endpoint
        captured["headers"] = kwargs["additional_headers"]
        return Connection()

    monkeypatch.setattr("agent_dashboard.helper.websockets.connect", connect)
    helper = WorkstationHelper(
        DbusNotifier(lambda *_: None),
        username="dashboard",
        password="correct horse",
    )

    await helper.connect("https://dashboard.example", "workstation-a")

    assert captured["endpoint"] == (
        "wss://dashboard.example/api/v1/workstations/workstation-a"
    )
    assert captured["headers"] == basic_auth_header("dashboard", "correct horse")
    assert captured["sent"] == [{"type": "register", "host_id": "workstation-a"}]


@pytest.mark.asyncio
async def test_helper_forwards_local_plugin_events_with_basic_auth(monkeypatch):
    captured = {}
    real_async_client = httpx.AsyncClient

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, endpoint, **kwargs):
            captured.update(endpoint=endpoint, **kwargs)
            return SimpleNamespace(
                content=b'{"type":"agent.updated"}',
                status_code=202,
                headers={"content-type": "application/json"},
            )

    monkeypatch.setattr("agent_dashboard.helper.httpx.AsyncClient", lambda **_kwargs: Client())
    helper = WorkstationHelper(
        DbusNotifier(lambda *_: None),
        helper_host="workstation-a",
        username="dashboard",
        password="correct horse",
    )
    app = create_helper_app(
        helper,
        server_url="https://dashboard.example",
        host_id="workstation-a",
    )
    transport = httpx.ASGITransport(app=app)
    async with real_async_client(transport=transport, base_url="http://helper") as client:
        response = await client.post(
            "/api/v1/events",
            json=make_event(host_id="stale-plugin-host").model_dump(mode="json"),
        )

    assert response.status_code == 202
    assert captured["endpoint"] == "https://dashboard.example/api/v1/events"
    assert captured["headers"]["Authorization"] == basic_auth_header(
        "dashboard", "correct horse",
    )["Authorization"]
    assert json.loads(captured["content"])["host_id"] == "workstation-a"


def test_helper_runner_starts_database_free_local_relay(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "agent_dashboard.helper.uvicorn.run",
        lambda app, **kwargs: calls.append((app, kwargs)),
    )

    from agent_dashboard.helper import run_helper
    run_helper(
        server_url="https://central.test",
        host_id="workstation-a",
        host="127.0.0.1",
        port=8010,
        username="dashboard",
        password="secret",
    )

    assert calls[0][1] == {"host": "127.0.0.1", "port": 8010}
    assert calls[0][0].title == "Agent Dashboard Workstation Helper"
