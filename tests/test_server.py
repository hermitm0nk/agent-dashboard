from types import SimpleNamespace

import pytest

from agent_dashboard.server import DashboardServer, run_server


@pytest.mark.asyncio
async def test_shutdown_disconnects_streams_before_uvicorn_waits(monkeypatch):
    order = []

    async def disconnect_clients():
        order.append("disconnect")
        return 1

    application = SimpleNamespace(state=SimpleNamespace(disconnect_clients=disconnect_clients))
    server = object.__new__(DashboardServer)
    server.config = SimpleNamespace(loaded_app=SimpleNamespace(app=application))

    async def uvicorn_shutdown(_server, sockets=None):
        order.append("uvicorn")

    monkeypatch.setattr("uvicorn.Server.shutdown", uvicorn_shutdown)
    await server.shutdown()

    assert order == ["disconnect", "uvicorn"]


def test_run_server_treats_keyboard_interrupt_as_normal_exit(monkeypatch):
    monkeypatch.setattr("agent_dashboard.server.DashboardServer.run",
                        lambda _server: (_ for _ in ()).throw(KeyboardInterrupt))

    run_server(host="127.0.0.1", port=8000, reload=False)
