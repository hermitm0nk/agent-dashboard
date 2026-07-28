# Agent Dashboard

## Quickstart

Agent Dashboard requires Python 3.13 or newer. The recommended development
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

The quickstart persists state in `~/.agent-dashboard/agent-dashboard.db`.
To choose a different database path:

```sh
uv run agent-dashboard server --db ~/.local/state/agent-dashboard/dashboard.db
```

For development, add `--reload` to restart the server when Python files change.

For distributed use, run each remote workstation server with a host identity and
main-server URL, such as `agent-dashboard server --host-id laptop
--main-server http://dashboard.example:8000`. The server connects outbound over
WebSocket and remains available for focus commands.

Open <http://127.0.0.1:8000/> for the web dashboard. To use the terminal UI
instead, run this in another terminal:

```sh
uv run agent-dashboard tui
```

The TUI is keyboard-first. Use `j`/`k` to move, `g`/`G` for first/last,
`Ctrl+d`/`Ctrl+u` for half-page movement, `Enter` or `l` to open a session,
`/` to search session metadata and BM25-ranked message history, and `h`, `Esc`,
or `Backspace` to return. Session actions use uppercase
mnemonics: `F` focus, `S` seen/unseen, `A` archive/restore, `X` switch
Active/Archive, `M` mark all seen, and `R` reload.

### Web UI development

The Web UI source lives in `frontend/` and is built with Vite. FastAPI serves
the generated assets from `agent_dashboard/web_dist/`; the old static page is
kept as a fallback until a frontend build exists.

```sh
cd frontend
npm install
npm run dev       # proxies /api to a local FastAPI server
npm run build     # writes agent_dashboard/web_dist/
```

Run `uv run agent-dashboard --help` at any time to see all available commands.
The server performs workstation actions in its own graphical session. A local
dashboard focuses local windows in-process; a central server forwards a remote
focus request to the combined server on the target host. Use
`POST /api/v1/clients/disconnect` to ask connected TUI and Web UI clients to
close their SSE connections.

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

Use `server --db PATH` or `AGENT_DASHBOARD_DB` to override the default database.

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
  - Harness support: OpenCode, Hermes, Pi agent and OpenAI Codex CLI
- Quick goto agent link/button/option in the UI. The supported backend is tmux.
  If the session is hidden, the workstation helper opens a fresh foot window
  attached to it. If the agent is on a remote host, it can open an SSH tmux
  connection in a new terminal window.
- Notification display even when command center is minimized/not active.
  Generic regex rules route matching messages to any number of D-Bus, WebPush,
  or ntfy actions.

## Architecture

### Overview

The first implementation targets a single-user Linux desktop running Wayland,
Hyprland, foot and tmux. It consists of a server, thin
harness-specific hooks, a TUI and a Web UI. Each server also performs actions
that require access to its own graphical and login session.

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
5. When a user selects "go to agent", the server executes locally or forwards
   the request to the server on the agent's host.

### Central server

Run one FastAPI server process. It provides a versioned JSON HTTP API for agent
events, snapshots, rules, subscriptions and go-to requests. The TUI and Web UI
load snapshots over HTTP and receive subsequent changes through Server-Sent
Events (SSE). SSE is the only UI update transport.

The server process includes the workstation action service. Remote workstation
servers connect outbound over WebSocket, register their host ID, and wait for
commands; local actions are dispatched in-process.

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
window and pane IDs. Hooks use a two-second HTTP timeout and never block or fail
the agent
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
local programs directly. Focus requests contain only the agent ID; the server
routes them from the agent's host ID to its local or remote workstation server.
Browser notifications use the web channel and are shown for connected dashboard clients.

### Notifications

Model notification delivery behind one interface, with adapters for:

- D-Bus desktop notifications, executed by the workstation server in the user's graphical
  session;
- Web notifications, sent by the central server to connected browser clients; and
- ntfy, sent by the central server through its HTTP API.

The server evaluates notification rules once, before invoking adapters. A rule
has two parts: a match object and an action list. Every non-empty match field is
a regular expression searched within the attribute; all fields must match. Use
`^` and `$` when an exact full-string match is required. Available message
attributes include type, text, agent ID, agent type (harness), origin host,
session ID, status, working directory, model, and chat title. An empty match
object matches every message. Every action on every matching rule is executed,
so a rule may deliver through multiple backends or contain multiple actions of
the same backend.
Store a small delivery record or deduplication key so repeated heartbeats do not
produce repeated notifications. Delivery errors should be visible in logs and
status screens but should not affect agent state updates.

Actions are typed objects. A `native` action has a `hostname_regex` and sends to
every connected workstation whose ID matches. A `webpush` action has a
`client_ids_regex` and sends to every connected browser client ID that matches;
the Web UI persists its generated client ID in browser local storage. An `ntfy`
action specifies its topic and may override the ntfy server. Target regexes use
the same substring-search semantics and can be anchored for exact matching.

There are no default channel settings and no per-agent overrides. Those cases
are generic rules: use an empty match object for a default route or an
`agent_id` regex for one or more agents. Rules are managed through
`GET`/`POST /api/v1/rules` and `DELETE /api/v1/rules/{rule_id}` and have their
own configuration screen in the Web UI. `GET /api/v1/notification-history`
returns every persisted event with the values available to rule matching, and
`POST /api/v1/rules/preview` applies draft matchers to that history. The editor
uses both endpoints to highlight past events that the current draft would have
matched.

### Go-to-agent actions and workstation server

Switching tmux panes, opening a terminal and starting SSH require access to the
user's desktop session. Run the same Python server as
a Hyprland-session systemd user service on every workstation where actions are
needed. A central server forwards remote requests to that workstation server.

The workstation server receives a typed go-to command containing the agent ID,
origin host and location, then performs the action in its own graphical session.

#### tmux, foot and SSH

Hooks running inside tmux record the host plus tmux session, window and pane
IDs. They do not treat the agent process PID as a terminal-window identity:
tmux sessions survive terminal clients, so that relationship is not stable.

For an agent on the workstation server's host, the server uses `tmux list-clients` to find a
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
the origin host differs from the workstation server's host, open
`foot --title=agent-dashboard:<agent-id> ssh -t <host> tmux attach-session -t
<session>`, then select the recorded target. Reuse an existing tagged foot
window for that agent when one exists. Validate host names and tmux identifiers
and pass them as subprocess argument arrays; never interpolate them into shell
commands.

Commands are structured requests, not arbitrary shell strings received from
the network. The workstation server allowlists action types and executable
templates, validates identifiers, and rejects unknown fields. This keeps the
action service small and limits its authority.

### Storage

Use SQLite as the server's persistent storage. It is a good fit for agent
metadata, latest status, notification rules, WebPush subscriptions, workstation
registrations and event and delivery history. SQLite is the selected production
database for this implementation, not a development substitute for another
database. It has no separate service to operate and is sufficient because there
is one server writer.

Use WAL mode, enable foreign keys, set a five-second busy timeout, keep
transactions short and apply numbered SQL migrations on startup. Only the
server opens the database. Hooks and UIs use the API.

Keep active SSE streams, workstation WebSockets and bounded delivery queues in
process memory. Do not use Redis, PostgreSQL or another message broker. Retain
agent events and delivery records for 30 days and prune them daily. Retain
current agent state, rules and subscriptions until explicitly deleted.

### Security and deployment

Use a separate random bearer token for every hook installation and workstation server, and
store only token hashes in SQLite. Use secure, HTTP-only, same-site session
cookies for the Web app. The initial administrator password comes from an
environment variable and is replaced with a stored password hash on first
login.
Do not expose message contents unless the harness supplies them and the user has
enabled that collection. TLS should terminate at the server or a small reverse
proxy whenever traffic crosses a trusted local network.

For a local-only setup, all components run on one machine: one server and SQLite
file, Web assets served by that server, and TUI/Web clients. Distributed setups
run hooks beside agents with a central server forwarding actions to combined
servers on remote workstations. Install each server as a systemd user service.
Do not add containers, Redis,
PostgreSQL or a separate Web server to the first implementation.

### Suggested implementation order

1. Define the normalized event and agent models, then implement the server,
   SQLite schema and HTTP/SSE API.
2. Add one harness hook and the TUI to validate the end-to-end state flow.
3. Add the Web UI and notification rule evaluation.
4. Add ntfy and WebPush, followed by workstation actions and D-Bus.
5. Add tmux and SSH action adapters, then the remaining harness hooks.

This order establishes the shared core early while leaving OS- and
harness-specific integrations as incremental, independently testable adapters.
