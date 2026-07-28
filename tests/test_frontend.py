import json
import subprocess
from pathlib import Path
from uuid import UUID


ID_MODULE = Path(__file__).parents[1] / "frontend/src/id.ts"
NAVIGATION_MODULE = Path(__file__).parents[1] / "frontend/src/navigation.ts"


def test_frontend_uuid_fallback_works_without_secure_context():
    script = f"""
const {{ randomUuid }} = await import({json.dumps(ID_MODULE.as_uri())});
const deterministic = {{
  getRandomValues(values) {{
    for (let index = 0; index < values.length; index += 1) values[index] = index;
    return values;
  }},
}};
process.stdout.write(randomUuid(deterministic));
"""
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        text=True, capture_output=True, check=True,
    )

    identifier = UUID(result.stdout)
    assert identifier.version == 4
    assert identifier.variant == "specified in RFC 4122"


def test_frontend_uuid_prefers_native_secure_context_api():
    script = f"""
const {{ randomUuid }} = await import({json.dumps(ID_MODULE.as_uri())});
process.stdout.write(randomUuid({{ randomUUID: () => "native-id" }}));
"""
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        text=True, capture_output=True, check=True,
    )

    assert result.stdout == "native-id"


def test_frontend_browser_navigation_round_trips_views_and_agent_ids():
    script = f"""
const {{ apiUrl, dashboardUrl, parseDashboardLocation }} = await import({json.dumps(NAVIGATION_MODULE.as_uri())});
const cases = [
  ["", {{ screen: "agents", agentId: "" }}, "/web/#top"],
  ["?view=rules", {{ screen: "rules", agentId: "" }}, "/web/?view=rules#top"],
  ["?agent=host%2Fsession+one", {{ screen: "agents", agentId: "host/session one" }},
    "/web/?agent=host%2Fsession+one#top"],
];
for (const [search, expected, url] of cases) {{
  const parsed = parseDashboardLocation(search);
  if (JSON.stringify(parsed) !== JSON.stringify(expected)) throw new Error(JSON.stringify(parsed));
  if (dashboardUrl("/web/", parsed, "#top") !== url) throw new Error(dashboardUrl("/web/", parsed, "#top"));
}}
if (apiUrl("/api/v1/agents", "https://example.test/agent-dashboard/") !==
    "https://example.test/agent-dashboard/api/v1/agents") {{
  throw new Error("API deployment prefix was discarded");
}}
"""
    subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        text=True, capture_output=True, check=True,
    )
