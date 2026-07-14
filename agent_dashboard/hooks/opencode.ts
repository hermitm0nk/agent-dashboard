/** OpenCode plugin that forwards session lifecycle events to Agent Dashboard. */
import { hostname } from "node:os";
type DashboardEvent = {
  event_id: string; agent_id: string; session_id: string;
  event_type: "started" | "working" | "waiting_for_input" | "message" | "finished" | "error";
  timestamp: string; host_id: string; working_dir: string; harness: "opencode";
  location: { kind: "tmux"; pane: string };
  message?: string;
};

function safe(value: string | undefined, fallback: string): string {
  const result = (value ?? fallback).replace(/[^A-Za-z0-9_.:$@%-]/g, "_");
  return result || fallback;
}

export const AgentDashboardPlugin = async ({ directory }) => {
  const endpoint = `${(process.env.AGENT_DASHBOARD_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "")}/api/v1/events`;
  const location = { kind: "tmux" as const, pane: safe(process.env.TMUX_PANE, "unknown") };
  const startedSessions = new Set<string>();
  const finishedSessions = new Set<string>();
  // The plugin is initialized before OpenCode has emitted an event containing a
  // session ID. Use a process-scoped ID so the TUI is visible immediately, then
  // retire it as soon as the real session is known.
  const startupSessionId = `opencode-${safe(process.env.HOSTNAME ?? hostname(), "host")}-${process.pid}`;

  async function send(sessionId: string, eventType: DashboardEvent["event_type"], message?: string) {
    const event: DashboardEvent = { event_id: crypto.randomUUID(), agent_id: sessionId, session_id: sessionId,
      event_type: eventType, timestamp: new Date().toISOString(),
      host_id: (process.env.AGENT_DASHBOARD_HOST_ID && process.env.AGENT_DASHBOARD_HOST_ID !== "unknown-host")
        ? process.env.AGENT_DASHBOARD_HOST_ID : (process.env.HOSTNAME ?? hostname()),
      working_dir: directory, harness: "opencode", location, ...(message ? { message } : {}) };
    try {
      const response = await fetch(endpoint, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(event), signal: AbortSignal.timeout(2000) });
      if (!response.ok) console.error(`agent-dashboard: event rejected (${response.status})`);
    } catch { /* Dashboard connectivity must never interrupt OpenCode. */ }
  }

  function sendSync(sessionId: string, eventType: DashboardEvent["event_type"]) {
    const event: DashboardEvent = { event_id: crypto.randomUUID(), agent_id: sessionId, session_id: sessionId,
      event_type: eventType, timestamp: new Date().toISOString(),
      host_id: (process.env.AGENT_DASHBOARD_HOST_ID && process.env.AGENT_DASHBOARD_HOST_ID !== "unknown-host")
        ? process.env.AGENT_DASHBOARD_HOST_ID : (process.env.HOSTNAME ?? hostname()),
      working_dir: directory, harness: "opencode", location };
    try {
      Bun.spawnSync(["curl", "-sS", "-X", "POST", "-H", "content-type: application/json",
        "--data-raw", JSON.stringify(event), endpoint]);
    } catch { /* shutdown delivery is best effort */ }
  }

  async function ensureStarted(sessionId: string) {
    if (startedSessions.has(sessionId)) return;
    if (sessionId !== startupSessionId && !finishedSessions.has(startupSessionId)) {
      finishedSessions.add(startupSessionId);
      await send(startupSessionId, "finished");
    }
    startedSessions.add(sessionId);
    await send(sessionId, "started");
  }

  async function finishAll() {
    for (const sessionId of startedSessions) {
      if (!finishedSessions.has(sessionId)) {
        finishedSessions.add(sessionId);
        await send(sessionId, "finished");
      }
    }
  }

  await ensureStarted(startupSessionId);

  // `dispose` is OpenCode's plugin-lifecycle shutdown hook. The synchronous
  // process exit fallback covers older OpenCode releases without taking over
  // their signal handling.
  process.once("exit", () => {
    for (const sessionId of startedSessions) {
      if (!finishedSessions.has(sessionId)) sendSync(sessionId, "finished");
    }
  });

  return {
    dispose: finishAll,
    event: async ({ event }) => {
    const properties = (event as { properties?: Record<string, unknown> }).properties ?? {};
    const info = properties.info as Record<string, unknown> | undefined;
    const sessionId = String(properties.sessionID ?? properties.session_id ?? properties.id
      ?? info?.sessionID ?? info?.session_id ?? info?.id ?? "opencode-session");
    if (event.type === "server.instance.disposed") {
      await finishAll();
    } else if (event.type === "tui.command.execute" &&
        ["app.exit", "exit", "quit", "q"].includes(String(properties.command ?? ""))) {
      await finishAll();
    } else if (event.type.startsWith("session.") || event.type.startsWith("message.")) {
      // Startup events can be emitted before a plugin subscribes. The first
      // event carrying a session ID is therefore also the session start.
      await ensureStarted(sessionId);
      if (event.type === "session.created") return;
      if (event.type === "session.status") {
        const statusValue = properties.status;
        const status = typeof statusValue === "string" ? statusValue
          : (statusValue as { type?: string } | undefined)?.type;
        await send(sessionId, status === "idle" ? "waiting_for_input" : "working");
      } else if (event.type === "session.idle") {
        await send(sessionId, "waiting_for_input");
      } else if (event.type === "session.error") {
        await send(sessionId, "error");
      } else if (event.type === "session.deleted") {
        finishedSessions.add(sessionId);
        await send(sessionId, "finished");
      } else if (event.type === "message.updated") {
        const messageInfo = properties.info as { role?: string; content?: unknown } | undefined;
        if (messageInfo?.role === "assistant") {
          const content = Array.isArray(messageInfo.content)
            ? messageInfo.content.filter((part): part is { type?: string; text?: string } => typeof part === "object" && part !== null)
                .filter(part => part.type === "text").map(part => part.text ?? "").join("\n").slice(-10000)
            : undefined;
          if (content) await send(sessionId, "message", content);
        }
      }
    }
  } };
};
