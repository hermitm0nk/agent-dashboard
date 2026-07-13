import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-dashboard")
    subparsers = parser.add_subparsers(dest="command", required=True)
    tui = subparsers.add_parser("tui", help="open the terminal dashboard")
    tui.add_argument("--url", default="http://127.0.0.1:8000", help="dashboard server URL")
    args = parser.parse_args()
    if args.command == "tui":
        from .tui import DashboardApp
        DashboardApp(base_url=args.url).run()
