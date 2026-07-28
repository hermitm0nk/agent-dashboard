# Agent Dashboard

Agent Dashboard is a self-hosted command center for coding-agent sessions. It
collects lifecycle and conversation events from supported agent harnesses,
shows them in a Web UI or TUI, sends notifications, and can focus the tmux pane
where an agent is running.

The current implementation targets a single-user Linux desktop using Hyprland,
foot, and tmux. The dashboard and event APIs are platform-independent; desktop
focus and native notifications are the Linux-specific parts.

## Components

- **Central server:** FastAPI application, Web UI, event history, notification
  rules, and the only SQLite database.
- **Workstation helper:** outbound-only process that connects to the central
  server and executes local `focus` and `notify` commands. It has no database,
  Web UI, or listening port.
- **Harness plugins:** small integrations for Codex, Hermes, OpenCode, and Pi.
  They translate each harness's native lifecycle callbacks into the dashboard's
  common event format.
- **Clients:** the browser UI and Textual TUI read the same API and receive live
  updates through Server-Sent Events.

### Why harness plugins?

The dashboard cannot infer reliably from process state whether an agent is
working, waiting for input, or has produced a new message. Each harness already
knows those transitions and exposes them differently—some call them hooks,
others plugins or extensions. The packages under [`plugins/`](plugins/) adapt
those native callbacks and send best-effort HTTP events to the central server.
A dashboard outage never interrupts an agent.

There is one canonical integration per harness under `plugins/`. The core
`agent_dashboard` Python package does not contain a second set of harness hooks.

## Install

Python 3.13 or newer is required. From a checkout:

```sh
uv sync --extra test
```

Without `uv`, use an existing virtual environment:

```sh
python -m pip install -e ".[test]"
```

## Run the central server

```sh
uv run agent-dashboard server
```

Open <http://127.0.0.1:8000/> or start the terminal UI:

```sh
uv run agent-dashboard tui
```

The default database is
`~/.agent-dashboard/agent-dashboard.db`. Central-server options can be supplied
on the command line or through the environment:

| Purpose | Command-line option | Environment variable | Default |
| --- | --- | --- | --- |
| Logical workstation ID | `--host-id` | `AGENT_DASHBOARD_HOST_ID` | OS hostname |
| Bind address | `--host` | `AGENT_DASHBOARD_BIND_HOST` | `127.0.0.1` |
| Port | `--port` | `AGENT_DASHBOARD_PORT` | `8000` |
| SQLite path | `--db` | `AGENT_DASHBOARD_DB` | `~/.agent-dashboard/agent-dashboard.db` |

Command-line values take precedence. `--reload` enables Uvicorn source reload;
`--no-web` skips the automatic frontend build check.

Verify the process and registered workstations with:

```sh
curl http://127.0.0.1:8000/api/v1/health
```

## Run workstation helpers

A helper is needed on every graphical workstation that should receive native
notifications or focus tmux sessions. Set a unique logical host ID and the
central server URL:

```sh
AGENT_DASHBOARD_HOST_ID=workstation-a \
AGENT_DASHBOARD_MAIN_SERVER=http://dashboard.example:8000 \
uv run agent-dashboard helper
```

The helper opens only an outbound WebSocket and therefore does not create a
database or introduce a local port conflict. For compatibility with earlier
versions, `agent-dashboard server --main-server URL` also selects this
helper-only runtime.

Logical host IDs need not match physical hostnames. This makes a distributed
setup easy to test on one computer:

```sh
# Terminal 1: central server
AGENT_DASHBOARD_HOST_ID=central \
AGENT_DASHBOARD_PORT=8000 \
AGENT_DASHBOARD_DB=/tmp/agent-dashboard-central.db \
uv run agent-dashboard server

# Terminal 2: first helper
AGENT_DASHBOARD_HOST_ID=workstation-a \
AGENT_DASHBOARD_MAIN_SERVER=http://127.0.0.1:8000 \
uv run agent-dashboard helper

# Terminal 3: second helper
AGENT_DASHBOARD_HOST_ID=workstation-b \
AGENT_DASHBOARD_MAIN_SERVER=http://127.0.0.1:8000 \
uv run agent-dashboard helper
```

Harness plugins running on a workstation must use the same
`AGENT_DASHBOARD_HOST_ID`; that identity is how the central server routes focus
and native-notification commands.

## Install harness integrations

Install every locally available harness integration:

```sh
plugins/install-all.sh
```

Or install one from its directory:

```sh
plugins/codex-agent-dashboard/install.sh
plugins/hermes-agent-dashboard/install.sh
plugins/opencode-agent-dashboard/install.sh
plugins/pi-agent-dashboard/install.sh
```

Before starting a harness, configure its destination and identity:

```sh
export AGENT_DASHBOARD_URL=http://127.0.0.1:8000
export AGENT_DASHBOARD_HOST_ID=$(hostname)
```

See [`plugins/README.md`](plugins/README.md) for harness-specific installation
and lifecycle details. `AGENT_DASHBOARD_TOKEN` is accepted by the integrations
for deployments that add authentication in front of the API; the application
itself does not currently authenticate requests.

## How data flows

1. A harness plugin observes a native session callback and posts a normalized
   event to `POST /api/v1/events`.
2. The central server stores the event and latest agent state in SQLite.
3. Notification rules are evaluated and matching deliveries are queued.
4. Web and TUI clients receive the update over SSE.
5. A focus request is routed by the event's `host_id` to the matching connected
   workstation helper over WebSocket.

Helpers accept only structured `focus` and `notify` commands. They do not accept
arbitrary shell commands. The tmux/Hyprland focus behavior is described in
[`docs/hypr-adapter.md`](docs/hypr-adapter.md).

## Development

Run the complete Python and integration test suite:

```sh
uv run pytest
```

Other useful checks:

```sh
uv run pytest tests/test_api.py -q
uv run python -m compileall -q agent_dashboard
```

The React frontend lives in `frontend/`. FastAPI serves its Vite output from
`agent_dashboard/web_dist/` when present and otherwise uses the checked-in
static fallback in `agent_dashboard/web/`.

```sh
cd frontend
npm install
npm run dev
npm run build
```

`npm run dev` proxies API requests to the local FastAPI server. `npm run build`
writes the production assets consumed by the Python package.
