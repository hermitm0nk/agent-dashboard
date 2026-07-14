# Agent Dashboard

## Quickstart

Agent Dashboard requires Python 3.11 or newer. The recommended development
workflow uses [`uv`](https://docs.astral.sh/uv/). From a checkout, install the
runtime and test dependencies with:

```sh
uv sync --extra test
```

If you do not use `uv`, install the package and its test extras in an existing
virtual environment with `python -m pip install -e ".[test]"`.

Start the API server in one terminal:

```sh
uv run agent-dashboard server
```

The quickstart uses an in-memory database. For a persistent local dashboard,
choose a database path:

```sh
mkdir -p ~/.local/state/agent-dashboard
uv run agent-dashboard server --db ~/.local/state/agent-dashboard/dashboard.db
```

For development, add `--reload` to restart the server when Python files change.

Open <http://127.0.0.1:8000/> for the web dashboard. To use the terminal UI
instead, run this in another terminal:

```sh
uv run agent-dashboard tui
```

Run `uv run agent-dashboard --help` at any time to see all available commands.
Set `AGENT_DASHBOARD_HELPER_ID` to the ID of the connected workstation helper;
selecting a row in the TUI then requests focus for its tmux pane or Firefox tab.
When exactly one helper is connected, the ID can be omitted. The web UI has
the same action through its **Focus** button; enter the helper ID only when
multiple helpers are connected.

Configure a harness hook to send events to the server before starting your
agent. The hook adapters use these variables:

```sh
export AGENT_DASHBOARD_URL=http://127.0.0.1:8000
export AGENT_DASHBOARD_HOST_ID=$(hostname)
```

Install the adapter for your harness using the instructions in
[`agent_dashboard/hooks/README.md`](agent_dashboard/hooks/README.md). Verify
that the server is running with:

```sh
curl http://127.0.0.1:8000/api/v1/health
```

### Common development commands

```sh
# run the full test suite
uv run pytest

# run one test file while iterating
uv run pytest tests/test_api.py -q

# compile-check the package
uv run python -m compileall -q agent_dashboard
```

The default database is in-memory, which is convenient for a quick demo; use
`server --db PATH` when agent state must survive restarts.

## Goals

### Command center

Managing multiple agents is hard, especially when they use different harnesses 
or distributed across multiple computers or virtual machines. There is no single 
control center that presents high-level information across all the different 
agents the user is running. As a consequence, time is wasted groping through 
myriads of tmux panes, terminal tabs, browser tabs and ssh sessions. This 
fatigue is real and drains productivity and joy.

### Async work

Modern agentic loops take a lot of time to execute, so working with them 
effectively requires asynchronous approach. Many harnesses like Hermes 
agent/opencode/pi agent don't have convenient integrated notifications for the 
moments when agents need attention or input. Hence time is wasted because agents 
stall waiting for user's action. This saps gains from concurrently running 
multiple agents and multitasking, making time needed to get the results even 
longer. The cure is good centralized notification unified across all agents 
precisely at the moment a task is ready or an input is needed.

## Features

- Two UIs: TUI and Web app. Each display command center with a list of agents, 
  their status (working, waiting for input) and, possibly, last few messages. 
  Ancillary information: agent type, model, git/working dir, host, chat title, - 
  also there. 
- Client-server architecture so that both local and remote (or distributed) 
  agents are supported. Use http so that agents running in a browser can sent 
  data (about their state) as well
- For each supported harness project has hooks that integrate with the server
  - Harness support: opencode, hermes, pi agent
- Quick goto agent link/button/option in the UI. Supported backends: firefox 
  browser (window and tab activation), tmux. If the session in tmux is hidden, 
  opens fresh window with it. Same for browser. If the agent is on the remote 
  host, and no connected ssh terminal exist, run ssh to connect to the host from 
  a new terminal window.
- Notification display even when command center is minimized/not active. 
  Supports silencing notifications for specific agents or agent types (with 
  rules). Backends: D-Bus notifications, WebPush, ntfy.

## Architecture

### Overview

The first implementation targets a single-user Linux desktop running Wayland,
Hyprland, foot, tmux and Firefox. It consists of a central server, thin
harness-specific hooks, a TUI, a Web UI and one workstation helper per desktop.
The server is the source of truth. The helper performs actions that require
access to the current graphical and login session.

Implement the project in Python 3. FastAPI provides the HTTP, SSE and WebSocket
endpoints, Pydantic defines the wire models, the standard-library `sqlite3`
module provides persistence, and Textual provides the TUI. Build the Web UI as
static HTML, CSS and JavaScript served by FastAPI. This avoids a second runtime
and build system during prototyping.

Harnesses, notification paths and go-to actions are adapters behind typed
Python interfaces. The shared core owns state transitions and routing; adapters
only translate external formats or perform platform-specific effects.

The normal data flow is:

1. A harness hook sends an HTTP event to the server.
2. The server validates and normalizes it, updates the agent's current state,
   and records it in the event history.
3. The server evaluates notification rules and invokes the configured delivery
   adapters.
4. Connected UIs receive the updated state immediately.
5. When a user selects "go to agent", the server routes the request to a helper
   on the workstation that can focus or open the agent.

### Central server

Run one FastAPI server process. It provides a versioned JSON HTTP API for agent
events, snapshots, rules, subscriptions and go-to requests. The TUI and Web UI
load snapshots over HTTP and receive subsequent changes through Server-Sent
Events (SSE). SSE is the only UI update transport.

Each workstation helper maintains one authenticated outbound WebSocket to the
server. The WebSocket carries server-to-helper commands and helper-to-server
results. This is the only helper command transport, so workstations expose no
inbound control ports.

The server owns normalization, current-state calculation, stale-agent timeout
handling, notification rule evaluation and backend selection. Slow external
calls such as ntfy delivery do not block event ingestion. Put them on a bounded
in-process `asyncio.Queue`, use three delivery attempts with exponential
backoff, and record the final result. No external message broker is used.

### Agent integration hooks

Provide a thin adapter for each supported harness: OpenCode, Hermes and pi
agent. Hooks translate native lifecycle callbacks into a small shared event
format rather than containing dashboard logic. Useful event types include
`started`, `working`, `waiting_for_input`, `message`, `finished` and `error`.

Every event includes a stable agent/session ID, harness type, timestamp, host
ID, working directory and a typed location. A tmux location contains session,
window and pane IDs. A Firefox location contains the `window.tab` ID, URL and
title. Hooks use a two-second HTTP timeout and never block or fail the agent
when the dashboard is unavailable. Send a heartbeat every 30 seconds while
active; the server marks an agent stale after 90 seconds without an event.

Keep the wire format harness-neutral and versioned. Shared hook code provides
HTTP transport, configuration and host identification; each adapter only
extracts fields from its harness.

### User interfaces

The TUI and Web app are clients of the same API and should not implement their
own agent-state or notification logic. Both load an initial snapshot over HTTP,
then subscribe to the SSE stream for incremental changes. They expose the same
main concepts: agent list, status and recent activity, filters, notification
rules, and a go-to action.

The TUI is a Textual application and the Web UI is static HTML, CSS and
JavaScript served by FastAPI from the same origin as the API. Neither UI invokes
local programs directly. Each UI obtains the ID of the helper on its workstation
and includes it in go-to requests, so the server knows which desktop must
execute the action. Browser notifications use WebPush and do not require the
page to remain open.

The helper writes its ID to
`$XDG_RUNTIME_DIR/agent-dashboard/helper-id`; the TUI reads that file. Pair the
Web UI by running `agent-dashboard-helper open`. The helper requests a one-time
pairing URL from the server and opens it in Firefox; the server binds that
browser session cookie to the helper ID. A manually opened, unpaired Web UI can
view agents but disables go-to actions until it is paired.

### Notifications

Model notification delivery behind one interface, with adapters for:

- D-Bus desktop notifications, executed by the helper in the user's graphical
  session;
- WebPush, sent by the central server using stored browser subscriptions; and
- ntfy, sent by the central server through its HTTP API.

The server evaluates silence and routing rules once, before invoking adapters.
Rules can match fields such as agent ID, harness type, host, status and time.
Store a small delivery record or deduplication key so repeated heartbeats do not
produce repeated notifications. Delivery errors should be visible in logs and
status screens but should not affect agent state updates.

### Go-to-agent actions and host helper

Focusing a Firefox tab, switching tmux panes, opening a terminal and starting
SSH require access to the user's desktop session. Run the Python helper as a
Hyprland-session systemd user service on every workstation where the dashboard
is used. Go-to actions and D-Bus notifications require this helper.

The helper registers its host ID and capabilities, then waits on its outbound
WebSocket. A go-to command contains the agent ID, origin host and a typed tmux or
Firefox location. The server always sends it to the helper associated with the
UI that requested the action, never to the host on which the agent originated.

#### tmux, foot and SSH

Hooks running inside tmux record the host plus tmux session, window and pane
IDs. They do not treat the agent process PID as a terminal-window identity:
tmux sessions survive terminal clients, so that relationship is not stable.

For an agent on the helper's host, the helper uses `tmux list-clients` to find a
client attached to the recorded session and reads its `client_pid` and
`client_tty`. It walks the client PID's process ancestry and matches it against
the PID of a foot client returned by `hyprctl -j clients`. It then:

1. Runs `tmux switch-client -c <client_tty> -t
   <session>:<window>.<pane>`.
2. Focuses the matching foot address with `hyprctl dispatch focuswindow
   address:<address>`.
3. Verifies that the active Hyprland window has that address.

Cache the mapping only while both the tmux client and Hyprland address exist. If
PID matching fails, configure tmux with `set-titles on` and a
`set-titles-string` containing a unique dashboard prefix and tmux session ID,
then find the foot client by that exact title. Titles are the fallback, not the
primary identity.

If no client is attached, open `foot --title=agent-dashboard:<agent-id> tmux
attach-session -t <session>` and then select the recorded window and pane. If
the origin host differs from the helper's host, open
`foot --title=agent-dashboard:<agent-id> ssh -t <host> tmux attach-session -t
<session>`, then select the recorded target. Reuse an existing tagged foot
window for that agent when one exists. Validate host names and tmux identifiers
and pass them as subprocess argument arrays; never interpolate them into shell
commands.

#### Firefox and Tridactyl

The Firefox adapter uses the existing Tridactyl remote files in
`/tmp/tridactyl-remote`. `tab-list` is a TSV file whose columns are `window.tab`
ID, title and URL. `tab-command` contains one `window.tab` ID, such as `1.2`.
Both files belong to the Firefox instance in the current user's desktop
session.

For an agent whose origin host is the helper's host, the helper performs this
exact sequence:

1. Parse `tab-list` and locate the recorded `window.tab` ID. If that ID is no
   longer present, match the recorded URL exactly and use the title only to
   break ties.
2. Atomically replace `tab-command` with the selected `window.tab` ID followed
   by a newline.
3. Find a Firefox client in `hyprctl -j clients` and focus its address with
   `hyprctl dispatch focuswindow address:<address>`.
4. Verify that Firefox is active, then send `<M-F12>` with `wtype -M alt -k F12
   -m alt`.
5. The Firefox extension reads `tab-command` and invokes Tridactyl's tab
   command, which focuses the correct Firefox window and tab.

If neither the ID nor URL is present, or if the origin host differs from the
helper's host, run `firefox --new-window <recorded-url>`. Wait for the new
Firefox client to appear in the Hyprland IPC client list and focus it. Only
allow `http` and `https` URLs.

Commands are structured requests, not arbitrary shell strings received from
the network. The helper allowlists action types and executable templates,
validates identifiers, and rejects unknown fields. This keeps the helper small
and limits its authority.

### Storage

Use SQLite as the server's persistent storage. It is a good fit for agent
metadata, latest status, notification rules, WebPush subscriptions, helper
registrations and event and delivery history. SQLite is the selected production
database for this implementation, not a development substitute for another
database. It has no separate service to operate and is sufficient because there
is one server writer.

Use WAL mode, enable foreign keys, set a five-second busy timeout, keep
transactions short and apply numbered SQL migrations on startup. Only the
server opens the database. Hooks, helpers and UIs use the API.

Keep active SSE streams, helper WebSockets and bounded delivery queues in
process memory. Do not use Redis, PostgreSQL or another message broker. Retain
agent events and delivery records for 30 days and prune them daily. Retain
current agent state, rules and subscriptions until explicitly deleted.

### Security and deployment

Use a separate random bearer token for every hook installation and helper, and
store only token hashes in SQLite. Use secure, HTTP-only, same-site session
cookies for the Web app. The initial administrator password comes from an
environment variable and is replaced with a stored password hash on first
login.
Do not expose message contents unless the harness supplies them and the user has
enabled that collection. TLS should terminate at the server or a small reverse
proxy whenever traffic crosses a trusted local network.

For a local-only setup, all components run on one machine: one server and SQLite
file, Web assets served by that server, a TUI client and a helper. Distributed
setups run hooks beside agents but still use one central server. Install the
server and helper as systemd user services. Do not add containers, Redis,
PostgreSQL or a separate Web server to the first implementation.

### Suggested implementation order

1. Define the normalized event and agent models, then implement the server,
   SQLite schema and HTTP/SSE API.
2. Add one harness hook and the TUI to validate the end-to-end state flow.
3. Add the Web UI and notification rule evaluation.
4. Add ntfy and WebPush, followed by the workstation helper and D-Bus.
5. Add tmux, Firefox and SSH action adapters, then the remaining harness hooks.

This order establishes the shared core early while leaving OS- and
harness-specific integrations as incremental, independently testable adapters.
