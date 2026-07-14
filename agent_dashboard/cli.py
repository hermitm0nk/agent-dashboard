import argparse
import os
from importlib.metadata import version


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-dashboard")
    parser.add_argument("--version", action="version", version=version("agent-dashboard"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    tui = subparsers.add_parser("tui", help="open the terminal dashboard")
    tui.add_argument("--url", default="http://127.0.0.1:8000", help="dashboard server URL")
    server = subparsers.add_parser("server", help="run the dashboard API and web server")
    server.add_argument("--host", default="127.0.0.1", help="bind address")
    server.add_argument("--port", type=int, default=8000, help="bind port")
    server.add_argument("--reload", action="store_true", help="reload on source changes (development)")
    server.add_argument("--db", help="SQLite database path (defaults to an in-memory database)")
    args = parser.parse_args()
    if args.command == "tui":
        from .tui import DashboardApp
        DashboardApp(base_url=args.url).run()
    elif args.command == "server":
        import uvicorn
        if args.db:
            os.environ["AGENT_DASHBOARD_DB"] = args.db
        uvicorn.run("agent_dashboard.api:app", host=args.host, port=args.port, reload=args.reload,
                    timeout_graceful_shutdown=2)
