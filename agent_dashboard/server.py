import os
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

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


def _ensure_frontend_built(no_web: bool) -> None:
    """Build frontend assets with Vite if ``web_dist/`` is missing.

    Skips the check entirely when ``no_web`` is ``True``.
    """
    if no_web:
        return

    web_dist = Path(__file__).parent / "web_dist"
    if web_dist.is_dir():
        return

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    print("frontend build output not found — running Vite build...", flush=True)
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            check=True,
            capture_output=True,
            text=True,
        )
        print(result.stdout, end="", flush=True)
    except FileNotFoundError:
        print(
            "warning: npm not found on PATH — frontend build skipped, "
            "falling back to static prototype",
            flush=True,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stdout, end="", file=sys.stderr, flush=True)
        print(exc.stderr, end="", file=sys.stderr, flush=True)
        print(
            "warning: frontend build failed — falling back to static prototype",
            flush=True,
        )


def run_server(*, host: str, port: int, reload: bool, no_web: bool = False) -> None:
    """Run the dashboard with its shutdown-aware Uvicorn server.

    Parameters
    ----------
    host, port, reload
        Standard uvicorn configuration.
    no_web
        When ``True``, skip the frontend build check and don't serve the web UI.
    """
    _ensure_frontend_built(no_web)
    os.environ.setdefault("AGENT_DASHBOARD_MAIN_SERVER", f"http://127.0.0.1:{port}")
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
