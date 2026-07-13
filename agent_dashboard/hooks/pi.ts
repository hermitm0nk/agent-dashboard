/**
 * Pi extension for Agent Dashboard.
 *
 * Install/run with:
 *   pi -e /path/to/agent_dashboard/hooks/pi.ts
 *
 * The extension follows Pi's documented session/agent/message lifecycle and
 * deliberately treats dashboard delivery as best effort: a dashboard outage
 * must never interrupt the agent.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type DashboardEvent = {
  event_id: string;
  agent_id: string;
  session_id: string;
  event_type: "started" | "working" | "waiting_for_input" | "message" | "finished" | "error";
  timestamp: string;
  host_id: string;
  working_dir: string;
  location: { kind: "tmux"; session: string; window: string; pane: string };
  model?: string;
  chat_title?: string;
  message?: string;
};

function id(): string {
  return crypto.randomUUID();
}

function sessionId(ctx: { sessionManager: { getSessionFile(): string | undefined } }): string {
  const file = ctx.sessionManager.getSessionFile();
  return file ? file.split("/").pop()!.replace(/\.jsonl$/, "") : "pi-ephemeral";
}

function safeIdentifier(value: string | undefined, fallback: string): string {
  const normalized = (value ?? fallback).replace(/[^A-Za-z0-9_.:-]/g, "_");
  return normalized || fallback;
}

export default function (pi: ExtensionAPI) {
  const endpoint = (process.env.AGENT_DASHBOARD_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "") + "/api/v1/events";
  const token = process.env.AGENT_DASHBOARD_TOKEN;
  const hostId = process.env.AGENT_DASHBOARD_HOST_ID ?? process.env.HOSTNAME ?? "unknown-host";
  const location = {
    kind: "tmux" as const,
    session: safeIdentifier(process.env.TMUX_SESSION, "unknown"),
    window: safeIdentifier(process.env.TMUX_WINDOW, "unknown"),
    pane: safeIdentifier(process.env.TMUX_PANE, "unknown"),
  };
  let currentSession = "pi-ephemeral";

  async function send(ctx: { cwd?: string }, eventType: DashboardEvent["event_type"], extra: Partial<DashboardEvent> = {}) {
    const event: DashboardEvent = {
      event_id: id(), agent_id: currentSession, session_id: currentSession,
      event_type: eventType, timestamp: new Date().toISOString(), host_id: hostId,
      working_dir: ctx.cwd ?? process.cwd(), location, ...extra,
    };
    try {
      const response = await fetch(endpoint, {
        method: "POST", headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify(event), signal: AbortSignal.timeout(2000),
      });
      if (!response.ok) console.error(`agent-dashboard: event rejected (${response.status}): ${await response.text()}`);
    } catch {
      // Dashboard connectivity is optional and must not affect Pi.
    }
  }

  pi.on("session_start", async (_event, ctx) => {
    currentSession = sessionId(ctx);
    await send(ctx, "started");
  });
  pi.on("agent_start", async (_event, ctx) => send(ctx, "working"));
  pi.on("message_end", async (event, ctx) => {
    if (event.message.role !== "assistant") return;
    const content = event.message.content
      .filter((part): part is { type: "text"; text: string } => part.type === "text")
      .map((part) => part.text).join("\n").slice(-10000);
    await send(ctx, "message", { message: content, model: ctx.model?.id });
  });
  pi.on("agent_end", async (_event, ctx) => send(ctx, "waiting_for_input"));
  pi.on("session_shutdown", async (_event, ctx) => send(ctx, "finished"));
}
