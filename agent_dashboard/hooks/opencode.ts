/** OpenCode plugin that forwards session lifecycle events to Agent Dashboard. */
type DashboardEvent = {
  event_id: string; agent_id: string; session_id: string;
  event_type: "started" | "working" | "waiting_for_input" | "message" | "finished" | "error";
  timestamp: string; host_id: string; working_dir: string;
  location: { kind: "tmux"; session: string; window: string; pane: string };
  message?: string;
};

function safe(value: string | undefined, fallback: string): string {
  const result = (value ?? fallback).replace(/[^A-Za-z0-9_.:-]/g, "_");
  return result || fallback;
}

export const AgentDashboardPlugin = async ({ directory }) => {
  const endpoint = `${(process.env.AGENT_DASHBOARD_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "")}/api/v1/events`;
  const location = { kind: "tmux" as const, session: safe(process.env.TMUX_SESSION, "unknown"),
    window: safe(process.env.TMUX_WINDOW, "unknown"), pane: safe(process.env.TMUX_PANE, "unknown") };

  async function send(sessionId: string, eventType: DashboardEvent["event_type"], message?: string) {
    const event: DashboardEvent = { event_id: crypto.randomUUID(), agent_id: sessionId, session_id: sessionId,
      event_type: eventType, timestamp: new Date().toISOString(),
      host_id: process.env.AGENT_DASHBOARD_HOST_ID ?? process.env.HOSTNAME ?? "unknown-host",
      working_dir: directory, location, ...(message ? { message } : {}) };
    try {
      const response = await fetch(endpoint, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(event), signal: AbortSignal.timeout(2000) });
      if (!response.ok) console.error(`agent-dashboard: event rejected (${response.status})`);
    } catch { /* Dashboard connectivity must never interrupt OpenCode. */ }
  }

  return { event: async ({ event }) => {
    const properties = (event as { properties?: Record<string, unknown> }).properties ?? {};
    const sessionId = String(properties.sessionID ?? properties.session_id ?? properties.id ?? "opencode-session");
    if (event.type === "session.created") await send(sessionId, "started");
    else if (event.type === "session.status") await send(sessionId, "working");
    else if (event.type === "session.idle") await send(sessionId, "waiting_for_input");
    else if (event.type === "session.error") await send(sessionId, "error");
    else if (event.type === "session.deleted") await send(sessionId, "finished");
  } };
};
