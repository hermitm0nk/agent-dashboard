# Harness hook installation

These opt-in adapters send lifecycle events to the dashboard API and fail
open if the server is unavailable. Set these variables before launching a
harness:

```sh
export AGENT_DASHBOARD_URL=http://127.0.0.1:8000
export AGENT_DASHBOARD_TOKEN=your-hook-token   # when authentication is enabled
export AGENT_DASHBOARD_HOST_ID=$(hostname)
```

Start the dashboard server first, then use one of the harness integrations.

## pi

For one run, load the documented TypeScript extension explicitly:

```sh
pi --extension /absolute/path/to/agent-dashboard/agent_dashboard/hooks/pi.ts
```

Install it globally for future runs:

```sh
agent_dashboard/hooks/install-pi.sh
```

This creates a symlink under `~/.pi/agent/extensions/`. The hook observes
`session_start`, `agent_start`, `message_end`, `agent_end`, and
`session_shutdown`.

## OpenCode

OpenCode automatically loads JavaScript and TypeScript plugins from
`.opencode/plugins/` in a project or `~/.config/opencode/plugins/` globally.

Install globally:

```sh
agent_dashboard/hooks/install-opencode.sh
```

Or install only in the current project:

```sh
mkdir -p .opencode/plugins
ln -sfn "$PWD/agent_dashboard/hooks/opencode.ts" .opencode/plugins/agent-dashboard.ts
opencode
```

The plugin observes `session.created`, `session.status`, `session.idle`,
`session.error`, and `session.deleted`.

## Hermes

Hermes shell hooks are configured in `~/.hermes/config.yaml`. Install the
executable hook and print its configuration block with:

```sh
agent_dashboard/hooks/install-hermes.sh
```

Add the printed `hooks:` block to `~/.hermes/config.yaml`, then run Hermes.
For non-interactive use, set `HERMES_ACCEPT_HOOKS=1` or explicitly approve the
commands. Verify setup with `hermes hooks list` and `hermes hooks doctor`.

The script handles `on_session_start`, `pre_llm_call`, `post_llm_call`, and
`on_session_end`, and prints `{}` on stdout as required by Hermes' shell-hook
protocol.

## Codex CLI

Codex automatically discovers command hooks in `~/.codex/hooks.json`. Install
the hook and persist the dashboard URL with:

```sh
agent_dashboard/hooks/install-codex.sh
```

Pass a non-default server URL as the first argument. The installer places a
`codex` lifecycle wrapper in `~/.local/bin` because Codex does not currently
expose a session-exit command hook. The wrapper reports process start and exit,
while `SessionStart`, `UserPromptSubmit`, and `Stop` report session and turn
state using the same dashboard identity. Ensure `~/.local/bin` precedes the
real Codex binary in `PATH`, set `[features] hooks = true` in
`~/.codex/config.toml`, restart Codex, then use `/hooks` to trust the generated
commands.

## Troubleshooting

```sh
curl http://127.0.0.1:8000/api/v1/agents
```

A missing or unavailable dashboard never blocks a harness. Check harness
stderr/logs for rejected events, then verify the URL, token, and working-dir.
