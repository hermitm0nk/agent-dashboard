# Harness plugins

Each supported harness integration is a self-contained package under this
directory. Its `install.sh` lives beside its package metadata and source.

Install or update every plugin whose harness is currently available with:

```sh
plugins/install-all.sh
```

The script skips missing harnesses without failing and prints an
installed/skipped/failed summary. Pass the local workstation-helper URL as its
first argument, or set `AGENT_DASHBOARD_URL`, to apply the same URL to every
installer.

Set connection variables before launching a harness:

```sh
export AGENT_DASHBOARD_URL=http://127.0.0.1:8000
export AGENT_DASHBOARD_HOST_ID=$(hostname)     # optional
```

Plugins always communicate with the helper on the same workstation. They do not
connect to the central server and must not receive its Basic Auth credentials.
The helper owns central authentication, event forwarding, and incoming command
delivery.

## Pi

`pi-agent-dashboard/` is an npm-format Pi package with a `pi.extensions`
manifest. Install the local package with:

```sh
plugins/pi-agent-dashboard/install.sh
```

It observes `session_start`, `agent_start`, `message_end`, `agent_end`, and
`session_shutdown`.

## OpenCode

`opencode-agent-dashboard/` is an npm-format OpenCode plugin. Install the local
package globally with:

```sh
plugins/opencode-agent-dashboard/install.sh
```

For a published build, use `opencode plugin agent-dashboard-opencode -g`.

## Hermes

`hermes-agent-dashboard/` is a Python package with a
`hermes_agent.plugins` entry point. Install it into the Hermes environment and
enable it with:

```sh
plugins/hermes-agent-dashboard/install.sh
```

Pass a non-default dashboard URL as the first argument. The package is
discoverable in every Hermes profile; enable it separately in profiles where
it should run with `hermes -p PROFILE plugins enable
--no-allow-tool-override agent-dashboard`.

## Codex

`codex-agent-dashboard/` is a standard Codex plugin with
`.codex-plugin/plugin.json` and bundled `hooks/hooks.json`. Install it with:

```sh
plugins/codex-agent-dashboard/install.sh
```

The installer copies the package to the recommended personal plugin location,
`~/.codex/plugins/agent-dashboard/`, and merges its entry into
`~/.agents/plugins/marketplace.json` without discarding existing marketplace
metadata or plugins. It also installs a `codex` lifecycle wrapper under
`~/.local/bin`, because Codex does not expose a process-exit hook.

Ensure `~/.local/bin` precedes the real Codex binary in `PATH`, enable hooks in
`~/.codex/config.toml`, restart Codex, and trust the plugin commands in
`/hooks`.

Codex does not currently forward approval requests or `request_user_input`
through its external plugin hooks, so those states cannot be reported reliably
to the dashboard by this integration. As a local mitigation, enable Codex's
native terminal notification without replacing any notification types you
already use:

```toml
[tui]
notifications = ["approval-requested", "agent-turn-complete"]
```

This makes the Codex terminal signal when it needs approval, but it is not a
remote dashboard notification. The integration deliberately does not infer
approvals from terminal output or transcript internals because those formats
are not a stable event contract.

## Troubleshooting

```sh
curl http://127.0.0.1:8000/api/v1/agents
```

Dashboard delivery is best effort and never blocks a harness. Check harness
stderr or logs for rejected events, then verify the URL, host ID, and working
directory settings.
