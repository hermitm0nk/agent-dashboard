import json
import subprocess
from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "plugins/pi-agent-dashboard/src/index.ts"


def test_pi_plugin_reports_native_lifecycle_and_messages():
    script = f"""
globalThis.fetch = async (_url, options) => {{
  globalThis.events.push(JSON.parse(options.body));
  return {{ ok: true }};
}};
globalThis.events = [];
globalThis.handlers = {{}};
const pi = {{ on: (name, callback) => globalThis.handlers[name] = callback }};
const module = await import({json.dumps(PLUGIN.as_uri())});
module.default(pi);
const ctx = {{
  cwd: "/work/project",
  thinkingLevel: "high",
  model: {{ id: "model-1" }},
  sessionManager: {{ getSessionFile: () => "/sessions/pi-session-1.jsonl" }},
}};
await globalThis.handlers.session_start({{}}, ctx);
await globalThis.handlers.agent_start({{}}, ctx);
await globalThis.handlers.message_end({{
  message: {{ role: "user", content: [{{ type: "text", text: "Continue" }}] }},
}}, ctx);
await globalThis.handlers.message_end({{
  message: {{ role: "assistant", content: [
    {{ type: "thinking", thinking: "internal" }},
    {{ type: "text", text: "Done" }},
  ] }},
}}, ctx);
await globalThis.handlers.agent_end({{}}, ctx);
await globalThis.handlers.session_shutdown({{}}, ctx);
process.stdout.write(JSON.stringify(globalThis.events));
"""
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        text=True, capture_output=True, check=True,
        env={"AGENT_DASHBOARD_HOST_ID": "workstation-a", "TMUX_PANE": "%2"},
    )

    events = json.loads(result.stdout)
    assert [event["event_type"] for event in events] == [
        "waiting_for_input", "working", "message", "message",
        "waiting_for_input", "finished",
    ]
    assert all(event["session_id"] == "pi-session-1" for event in events)
    assert all(event["host_id"] == "workstation-a" for event in events)
    assert events[2]["message_role"] == "user"
    assert events[2]["message"] == "Continue"
    assert events[3]["message_role"] == "assistant"
    assert events[3]["message"] == "Done"
    assert events[3]["model"] == "model-1"
    assert events[3]["effort"] == "high"
    assert events[3]["location"] == {"kind": "tmux", "pane": "%2"}
