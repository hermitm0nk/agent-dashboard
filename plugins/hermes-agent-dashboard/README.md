# Hermes Agent Dashboard plugin

This is a local-only Python distribution that connects Hermes Agent lifecycle
events to Agent Dashboard. It is not intended for publication to PyPI.
It reports ready/working state, both sides of the conversation, model, and
reasoning effort. Hermes currently omits effort from lifecycle hook arguments,
so the plugin resolves it through Hermes's model-aware configuration API.

Hermes discovers the plugin from its installed package metadata:

```toml
[project.entry-points."hermes_agent.plugins"]
agent-dashboard = "hermes_agent_dashboard.plugin:register"
```

Install it with the repository-level helper, which selects Hermes's own Python
environment and records the dashboard URL:

```sh
./install.sh http://127.0.0.1:8000
```

The distribution is visible to every Hermes profile. Plugin enablement remains
profile-specific; enable it in another profile with:

```sh
hermes -p PROFILE plugins enable --no-allow-tool-override agent-dashboard
```
