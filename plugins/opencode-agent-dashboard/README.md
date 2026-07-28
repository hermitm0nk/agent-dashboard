# Agent Dashboard for OpenCode

OpenCode plugin package that sends native session lifecycle, readiness,
user/assistant messages, model, reasoning variant, title, and working directory
to a self-hosted Agent Dashboard. Delivery is best effort and never blocks
OpenCode.

```sh
./install.sh
```

Set `AGENT_DASHBOARD_URL`, and optionally `AGENT_DASHBOARD_TOKEN` and
`AGENT_DASHBOARD_HOST_ID`, before starting OpenCode.
