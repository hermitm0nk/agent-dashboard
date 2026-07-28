import json
import subprocess
from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "plugins/opencode-agent-dashboard/src/index.ts"


def test_opencode_plugin_correlates_native_messages_and_session_metadata():
    script = f"""
globalThis.fetch = async (_url, options) => {{
  globalThis.events.push(JSON.parse(options.body));
  return {{ ok: true }};
}};
globalThis.events = [];
const {{ AgentDashboardPlugin }} = await import({json.dumps(PLUGIN.as_uri())});
const plugin = await AgentDashboardPlugin({{ directory: "/fallback" }});
const startup = globalThis.events[0];
await plugin.event({{ event: {{ type: "session.created", properties: {{
  info: {{ id: "s1", directory: "/work/project", title: "Fix tests" }}
}} }} }});
await plugin.event({{ event: {{ type: "message.updated", properties: {{
  info: {{ id: "u1", sessionID: "s1", role: "user",
    model: {{ providerID: "openai", modelID: "gpt-5" }}, variant: "high" }}
}} }} }});
await plugin.event({{ event: {{ type: "message.part.updated", properties: {{
  part: {{ id: "up1", messageID: "u1", sessionID: "s1", type: "text", text: "Please fix it" }}
}} }} }});
await plugin.event({{ event: {{ type: "session.status", properties: {{
  sessionID: "s1", status: {{ type: "busy" }}
}} }} }});
await plugin.event({{ event: {{ type: "message.updated", properties: {{
  info: {{ id: "a1", sessionID: "s1", role: "assistant",
    providerID: "openai", modelID: "gpt-5", time: {{ completed: 1 }} }}
}} }} }});
await plugin.event({{ event: {{ type: "message.part.updated", properties: {{
  part: {{ id: "ap1", messageID: "a1", sessionID: "s1", type: "text",
    text: "Fixed", time: {{ end: 1 }} }}
}} }} }});
await plugin.event({{ event: {{ type: "session.idle", properties: {{ sessionID: "s1" }} }} }});
process.stdout.write(JSON.stringify(globalThis.events));
"""
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        text=True, capture_output=True, check=True,
    )
    events = json.loads(result.stdout)
    assert [event["event_type"] for event in events] == [
        "waiting_for_input", "waiting_for_input", "message", "working",
        "message", "waiting_for_input",
    ]
    assert events[0]["session_id"].startswith("opencode-")
    assert events[1]["session_id"] == "s1"
    assert events[1]["agent_id"] == events[0]["agent_id"]
    assert events[2]["message_role"] == "user"
    assert events[2]["message"] == "Please fix it"
    assert events[2]["model"] == "openai/gpt-5"
    assert events[2]["effort"] == "high"
    assert events[4]["message_role"] == "assistant"
    assert events[1]["working_dir"] == "/work/project"
    assert events[1]["chat_title"] == "Fix tests"


def test_opencode_plugin_surfaces_permissions_and_questions_until_resolved():
    script = f"""
globalThis.fetch = async (_url, options) => {{
  globalThis.events.push(JSON.parse(options.body));
  return {{ ok: true }};
}};
globalThis.events = [];
const {{ AgentDashboardPlugin }} = await import({json.dumps(PLUGIN.as_uri())});
const plugin = await AgentDashboardPlugin({{ directory: "/work" }});
await plugin.event({{ event: {{ type: "permission.asked", properties: {{
  id: "perm-1", sessionID: "s1", permission: "bash",
  patterns: ["git push origin main"], metadata: {{ command: "git push origin main" }}
}} }} }});
await plugin.event({{ event: {{ type: "session.status", properties: {{
  sessionID: "s1", status: {{ type: "busy" }}
}} }} }});
await plugin.event({{ event: {{ type: "question.asked", properties: {{
  id: "question-1", sessionID: "s1",
  questions: [
    {{ header: "Deploy", question: "Which environment should I deploy to?" }},
    {{ question: "Proceed immediately?" }}
  ]
}} }} }});
await plugin.event({{ event: {{ type: "permission.replied", properties: {{
  requestID: "perm-1", sessionID: "s1", reply: "once"
}} }} }});
await plugin.event({{ event: {{ type: "session.idle", properties: {{ sessionID: "s1" }} }} }});
await plugin.event({{ event: {{ type: "question.rejected", properties: {{
  requestID: "question-1", sessionID: "s1"
}} }} }});
process.stdout.write(JSON.stringify(globalThis.events));
"""
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        text=True, capture_output=True, check=True,
    )
    events = json.loads(result.stdout)
    session_events = [event for event in events if event["session_id"] == "s1"]
    assert [event["event_type"] for event in session_events] == [
        "waiting_for_input", "waiting_for_input", "waiting_for_input", "working",
    ]
    assert session_events[1]["message"] == (
        "Approval required for bash: git push origin main"
    )
    assert session_events[2]["message"] == (
        "Input required: Which environment should I deploy to?\nProceed immediately?"
    )
