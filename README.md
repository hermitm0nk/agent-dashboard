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
- **Workstation helper:** database-free local relay. Harness plugins post events
  to its loopback API; it forwards them to the central server and receives
  `focus` and `notify` commands.
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
those native callbacks and send best-effort HTTP events to the helper on the
same workstation. Plugins never connect to the central server and never hold
central-server credentials. A dashboard outage never interrupts an agent.

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

A helper is needed on every workstation that runs harness plugins or should
receive native notifications and focus commands. Set a unique logical host ID
and the central server URL:

```sh
AGENT_DASHBOARD_HOST_ID=workstation-a \
AGENT_DASHBOARD_MAIN_SERVER=https://dashboard.example \
AGENT_DASHBOARD_BASIC_AUTH_USERNAME=workstation-a \
AGENT_DASHBOARD_BASIC_AUTH_PASSWORD='a-long-random-password' \
uv run agent-dashboard helper
```

The helper listens on `127.0.0.1:8000` by default for local plugin events. It
forwards those events over HTTP(S) and receives commands over WebSocket/WSS. It
does not create a database or expose its local API to the network. Use
`--host`, `--port`, `AGENT_DASHBOARD_HELPER_HOST`, or
`AGENT_DASHBOARD_HELPER_PORT` to change the local listener. For compatibility,
`agent-dashboard server --main-server URL` also selects the helper runtime.

### Authentication boundary

The helper is the only remote component that authenticates to the central
server. Harness plugins always talk to the loopback helper without credentials.
This keeps the central password out of agent processes and plugin configuration.

When nginx Basic Auth protects the central server, configure both
`AGENT_DASHBOARD_BASIC_AUTH_USERNAME` and
`AGENT_DASHBOARD_BASIC_AUTH_PASSWORD` on each helper. The helper sends the Basic
header while forwarding events and during the WebSocket handshake. Prefer the
password environment variable over the CLI option so it is not visible in
process listings.

Use HTTPS, bind Uvicorn to loopback behind nginx, and protect both HTTP and
WebSocket routes. Configure nginx WebSocket upgrade forwarding. A distinct
nginx user/password per workstation allows individual revocation, although
Basic Auth still does not cryptographically bind the claimed `host_id`.

A minimal nginx shape is:

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name dashboard.example;

    # Configure ssl_certificate and ssl_certificate_key here.
    auth_basic "Agent Dashboard";
    auth_basic_user_file /etc/nginx/agent-dashboard.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 75s;
    }
}
```

Run the central server on its default loopback bind address so port 8000 cannot
bypass nginx.

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
uv run agent-dashboard helper --port 8001

# Terminal 3: second helper
AGENT_DASHBOARD_HOST_ID=workstation-b \
AGENT_DASHBOARD_MAIN_SERVER=http://127.0.0.1:8000 \
uv run agent-dashboard helper --port 8002
```

The helper is authoritative for forwarded event `host_id` values; stale plugin
environment cannot route commands to a different workstation. In this
one-computer example, point plugin `AGENT_DASHBOARD_URL` values at
`http://127.0.0.1:8001` and `http://127.0.0.1:8002`, respectively.

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

Before starting a harness, configure its local helper and identity:

```sh
export AGENT_DASHBOARD_URL=http://127.0.0.1:8000
export AGENT_DASHBOARD_HOST_ID=$(hostname)
```

See [`plugins/README.md`](plugins/README.md) for harness-specific installation
and lifecycle details. Do not put central-server Basic Auth credentials in
harness environments.

## How data flows

1. A harness plugin posts a normalized event to the local helper's
   `POST /api/v1/events`.
2. The helper forwards it to the authenticated central endpoint.
3. The central server stores the event and latest state in SQLite, evaluates
   notification rules, and updates Web/TUI clients over SSE.
4. A focus or native-notification command is routed by `host_id` to the helper's
   authenticated WebSocket.

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
