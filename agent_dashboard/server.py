from collections.abc import Awaitable, Callable

import uvicorn


class DashboardServer(uvicorn.Server):
    """Uvicorn server that releases dashboard streams before draining requests."""

    def _disconnect_clients(self) -> Callable[[], Awaitable[int]] | None:
        application = self.config.loaded_app
        # Uvicorn may wrap the FastAPI application in proxy-header and ASGI
        # compatibility middleware. Walk through those wrappers to its state.
        while not hasattr(application, "state") and hasattr(application, "app"):
            application = application.app
        state = getattr(application, "state", None)
        return getattr(state, "disconnect_clients", None)

    async def shutdown(self, sockets=None) -> None:
        disconnect_clients = self._disconnect_clients()
        if disconnect_clients is not None:
            await disconnect_clients()
        await super().shutdown(sockets=sockets)


def run_server(*, host: str, port: int, reload: bool) -> None:
    """Run the dashboard with its shutdown-aware Uvicorn server."""
    config = uvicorn.Config("agent_dashboard.api:app", host=host, port=port, reload=reload)
    server = DashboardServer(config)
    try:
        if config.should_reload:
            from uvicorn.supervisors import ChangeReload

            socket = config.bind_socket()
            ChangeReload(config, target=server.run, sockets=[socket]).run()
        else:
            server.run()
    except KeyboardInterrupt:
        # Match uvicorn.run(): Ctrl+C is a normal server exit, not an error.
        pass
