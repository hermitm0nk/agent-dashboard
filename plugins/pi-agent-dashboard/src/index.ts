/**
 * Pi extension for Agent Dashboard.
 *
 * Install with:
 *   pi install /path/to/plugins/pi-agent-dashboard
 *
 * The extension follows Pi's documented session/agent/message lifecycle and
 * deliberately treats dashboard delivery as best effort: a dashboard outage
 * must never interrupt the agent.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { hostname } from "node:os";

type DashboardEvent = {
  event_id: string;
  agent_id: string;
  session_id: string;
  event_type: "started" | "working" | "waiting_for_input" | "message" | "finished" | "error";
  timestamp: string;
  host_id: string;
  harness: "pi";
  working_dir: string;
  location: { kind: "tmux"; pane: string };
  model?: string;
  effort?: string;
  chat_title?: string;
  message_role?: "user" | "assistant";
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
  const normalized = (value ?? fallback).replace(/[^A-Za-z0-9_.:$@%-]/g, "_");
  return normalized || fallback;
}

export default function (pi: ExtensionAPI) {
  const endpoint = (process.env.AGENT_DASHBOARD_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "") + "/api/v1/events";
  const token = process.env.AGENT_DASHBOARD_TOKEN;
  const configuredHost = process.env.AGENT_DASHBOARD_HOST_ID ?? process.env.HOSTNAME;
  const hostId = configuredHost && configuredHost !== "unknown-host" ? configuredHost : hostname();
  const location = { kind: "tmux" as const, pane: safeIdentifier(process.env.TMUX_PANE, "unknown") };
  let currentSession = "pi-ephemeral";

  async function send(ctx: { cwd?: string; thinkingLevel?: string }, eventType: DashboardEvent["event_type"], extra: Partial<DashboardEvent> = {}) {
    const event: DashboardEvent = {
      event_id: id(), agent_id: currentSession, session_id: currentSession,
      event_type: eventType, timestamp: new Date().toISOString(), host_id: hostId,
      working_dir: ctx.cwd ?? process.cwd(), harness: "pi", location,
      ...(ctx.thinkingLevel ? { effort: ctx.thinkingLevel } : {}), ...extra,
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
    // A new Pi session is idle until the user submits the first prompt.
    await send(ctx, "waiting_for_input");
  });
  pi.on("agent_start", async (_event, ctx) => send(ctx, "working"));
  pi.on("message_end", async (event, ctx) => {
    const content = event.message.content
      .filter((part): part is { type: "text"; text: string } => part.type === "text")
      .map((part) => part.text).join("\n").slice(-10000);
    if (!content) return;
    const role = event.message.role === "user" || event.message.role === "assistant"
      ? event.message.role : undefined;
    await send(ctx, "message", { message: content, message_role: role, model: ctx.model?.id });
  });
  pi.on("agent_end", async (_event, ctx) => send(ctx, "waiting_for_input"));
  pi.on("session_shutdown", async (_event, ctx) => send(ctx, "finished"));
}
