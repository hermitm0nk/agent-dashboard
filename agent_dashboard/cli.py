import argparse
import os
from importlib.metadata import version


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"port must be an integer, got {value!r}"
        ) from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-dashboard")
    parser.add_argument("--version", action="version", version=version("agent-dashboard"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    tui = subparsers.add_parser("tui", help="open the terminal dashboard")
    tui.add_argument("--url", default="http://127.0.0.1:8000", help="dashboard server URL")
    helper = subparsers.add_parser(
        "helper", help="connect this workstation to a central dashboard server",
    )
    helper.add_argument(
        "--host-id", default=os.environ.get("AGENT_DASHBOARD_HOST_ID"),
        help="logical workstation ID (default: AGENT_DASHBOARD_HOST_ID or OS hostname)",
    )
    helper.add_argument(
        "--main-server", default=os.environ.get("AGENT_DASHBOARD_MAIN_SERVER"),
        help="central dashboard URL (default: AGENT_DASHBOARD_MAIN_SERVER)",
    )
    server = subparsers.add_parser("server", help="run the dashboard API and web server")
    server.add_argument(
        "--host", default=os.environ.get("AGENT_DASHBOARD_BIND_HOST", "127.0.0.1"),
        help="bind address (default: AGENT_DASHBOARD_BIND_HOST or 127.0.0.1)",
    )
    server.add_argument(
        "--port", type=_port, default=os.environ.get("AGENT_DASHBOARD_PORT", "8000"),
        help="bind port (default: AGENT_DASHBOARD_PORT or 8000)",
    )
    server.add_argument("--reload", action="store_true", help="reload on source changes (development)")
    server.add_argument(
        "--db", default=os.environ.get("AGENT_DASHBOARD_DB"),
        help="SQLite path (default: AGENT_DASHBOARD_DB or ~/.agent-dashboard/agent-dashboard.db)",
    )
    server.add_argument(
        "--host-id", default=os.environ.get("AGENT_DASHBOARD_HOST_ID"),
        help="logical workstation ID (default: AGENT_DASHBOARD_HOST_ID or OS hostname)",
    )
    server.add_argument(
        "--main-server", default=os.environ.get("AGENT_DASHBOARD_MAIN_SERVER"),
        help="central dashboard URL; when set, run as an outbound-only workstation helper",
    )
    server.add_argument("--no-web", action="store_true",
                        help="skip auto-build of frontend assets (useful when you have already built or "
                             "don't need the web UI)")
    args = parser.parse_args()
    if args.command == "tui":
        from .tui import DashboardApp
        DashboardApp(base_url=args.url).run()
    elif args.command == "helper":
        if not args.main_server:
            parser.error(
                "helper requires --main-server or AGENT_DASHBOARD_MAIN_SERVER"
            )
        from .helper import run_helper

        run_helper(
            server_url=args.main_server,
            host_id=args.host_id or __import__("socket").gethostname(),
        )
    elif args.command == "server":
        if args.host_id:
            os.environ["AGENT_DASHBOARD_HOST_ID"] = args.host_id
        if args.main_server:
            # Compatibility for installations that predate the explicit
            # ``helper`` command.
            from .helper import run_helper

            run_helper(
                server_url=args.main_server,
                host_id=args.host_id or __import__("socket").gethostname(),
            )
            return
        from .server import run_server
        if args.db:
            os.environ["AGENT_DASHBOARD_DB"] = args.db
        server_options = {"host": args.host, "port": args.port, "reload": args.reload}
        if args.no_web:
            server_options["no_web"] = True
        run_server(**server_options)
