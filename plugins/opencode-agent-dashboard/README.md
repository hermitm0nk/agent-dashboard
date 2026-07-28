# Agent Dashboard for OpenCode

OpenCode plugin package that sends native session lifecycle, readiness,
user/assistant messages, model, reasoning variant, title, and working directory
to a self-hosted Agent Dashboard. Delivery is best effort and never blocks
OpenCode.

Native permission prompts and agent questions are reported as explicit
`waiting_for_input` events with their actionable details. The session remains
in that state until every pending permission or question has been resolved.

```sh
./install.sh
```

Set `AGENT_DASHBOARD_URL` to the local workstation helper and optionally set
`AGENT_DASHBOARD_HOST_ID` before starting OpenCode.
