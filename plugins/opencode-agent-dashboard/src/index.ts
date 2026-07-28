/** OpenCode plugin forwarding native session, status, and message events. */
import { hostname } from "node:os";

type EventType = "working" | "waiting_for_input" | "message" | "finished" | "error";
type DashboardEvent = {
  event_id: string;
  agent_id: string;
  session_id: string;
  event_type: EventType;
  timestamp: string;
  host_id: string;
  working_dir: string;
  harness: "opencode";
  location: { kind: "tmux"; pane: string };
  model?: string;
  effort?: string;
  chat_title?: string;
  message_role?: "user" | "assistant";
  message?: string;
};
type MessageInfo = {
  id?: string;
  sessionID?: string;
  role?: "user" | "assistant";
  providerID?: string;
  modelID?: string;
  model?: { providerID?: string; modelID?: string };
  variant?: string;
  mode?: string;
  time?: { completed?: number };
};
type TextPart = {
  id?: string;
  messageID?: string;
  sessionID?: string;
  type?: string;
  text?: string;
  time?: { end?: number };
};

const EFFORTS = new Set(["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]);

function safe(value: string | undefined, fallback: string): string {
  const result = (value ?? fallback).replace(/[^A-Za-z0-9_.:$@%-]/g, "_");
  return result || fallback;
}

function modelName(info: MessageInfo): string | undefined {
  const provider = info.providerID ?? info.model?.providerID;
  const model = info.modelID ?? info.model?.modelID;
  return provider && model ? `${provider}/${model}` : model;
}

function effortName(info: MessageInfo): string | undefined {
  if (info.variant) return info.variant;
  return info.mode && EFFORTS.has(info.mode.toLowerCase()) ? info.mode : undefined;
}

export const AgentDashboardPlugin = async ({ directory }: { directory: string }) => {
  const endpoint = `${(process.env.AGENT_DASHBOARD_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "")}/api/v1/events`;
  const token = process.env.AGENT_DASHBOARD_TOKEN;
  const location = { kind: "tmux" as const, pane: safe(process.env.TMUX_PANE, "unknown") };
  const sessions = new Map<string, { directory?: string; title?: string }>();
  const active = new Set<string>();
  const finished = new Set<string>();
  const dashboardIds = new Map<string, string>();
  const messages = new Map<string, MessageInfo>();
  const parts = new Map<string, Map<string, string>>();
  const sentMessages = new Set<string>();
  const startupSessionId = `opencode-${safe(process.env.HOSTNAME ?? hostname(), "host")}-${process.pid}`;
  let startupClaimed = false;

  async function send(sessionId: string, eventType: EventType, extra: Partial<DashboardEvent> = {}) {
    const session = sessions.get(sessionId);
    const agentId = dashboardIds.get(sessionId) ?? sessionId;
    const event: DashboardEvent = {
      event_id: crypto.randomUUID(),
      agent_id: agentId,
      session_id: sessionId,
      event_type: eventType,
      timestamp: new Date().toISOString(),
      host_id: (process.env.AGENT_DASHBOARD_HOST_ID && process.env.AGENT_DASHBOARD_HOST_ID !== "unknown-host")
        ? process.env.AGENT_DASHBOARD_HOST_ID : (process.env.HOSTNAME ?? hostname()),
      working_dir: session?.directory ?? directory,
      harness: "opencode",
      location,
      ...(session?.title ? { chat_title: session.title } : {}),
      ...extra,
    };
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          ...(token ? { authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(event),
        signal: AbortSignal.timeout(2000),
      });
      if (!response.ok) console.error(`agent-dashboard: event rejected (${response.status})`);
    } catch {
      // Dashboard connectivity must never interrupt OpenCode.
    }
  }

  async function ensureSession(sessionId: string) {
    if (active.has(sessionId)) return;
    if (sessionId !== startupSessionId && !startupClaimed && active.has(startupSessionId)) {
      // OpenCode does not allocate a native session until the first prompt.
      // Reuse the startup card's dashboard identity for that first session so
      // it is visible immediately without creating a second archived card.
      startupClaimed = true;
      dashboardIds.set(sessionId, startupSessionId);
      active.delete(startupSessionId);
    } else if (!dashboardIds.has(sessionId)) {
      dashboardIds.set(sessionId, sessionId);
    }
    active.add(sessionId);
    finished.delete(sessionId);
    await send(sessionId, "waiting_for_input");
  }

  async function flushMessage(messageId: string, force = false) {
    if (sentMessages.has(messageId)) return;
    const info = messages.get(messageId);
    const textParts = parts.get(messageId);
    if (!info?.sessionID || !info.role || !textParts?.size) return;
    if (info.role === "assistant" && !force && !info.time?.completed) return;
    const text = [...textParts.values()].filter(Boolean).join("\n").slice(-10000);
    if (!text) return;
    sentMessages.add(messageId);
    await send(info.sessionID, "message", {
      message: text,
      message_role: info.role,
      model: modelName(info),
      effort: effortName(info),
    });
  }

  async function finish(sessionId: string) {
    if (finished.has(sessionId)) return;
    finished.add(sessionId);
    active.delete(sessionId);
    await send(sessionId, "finished");
  }

  async function finishAll() {
    await Promise.all([...active].map(finish));
  }

  sessions.set(startupSessionId, { directory });
  dashboardIds.set(startupSessionId, startupSessionId);
  await ensureSession(startupSessionId);

  return {
    dispose: finishAll,
    event: async ({ event }: { event: { type: string; properties?: Record<string, unknown> } }) => {
      const properties = event.properties ?? {};
      const info = properties.info as Record<string, unknown> | undefined;
      const part = properties.part as TextPart | undefined;
      const sessionId = String(
        properties.sessionID ?? properties.session_id ?? part?.sessionID
        ?? info?.sessionID ?? info?.session_id ?? info?.id ?? "",
      );

      if (event.type === "server.instance.disposed") {
        await finishAll();
        return;
      }
      if (!sessionId) return;

      if (event.type === "session.created" || event.type === "session.updated") {
        sessions.set(sessionId, {
          directory: typeof info?.directory === "string" ? info.directory : directory,
          title: typeof info?.title === "string" ? info.title : undefined,
        });
      }
      await ensureSession(sessionId);

      if (event.type === "session.status") {
        const statusValue = properties.status;
        const status = typeof statusValue === "string"
          ? statusValue : (statusValue as { type?: string } | undefined)?.type;
        await send(sessionId, status === "idle" ? "waiting_for_input" : "working");
      } else if (event.type === "session.idle") {
        for (const [messageId, message] of messages) {
          if (message.sessionID === sessionId) await flushMessage(messageId, true);
        }
        await send(sessionId, "waiting_for_input");
      } else if (event.type === "session.error") {
        const error = properties.error as { data?: { message?: string }; message?: string } | undefined;
        await send(sessionId, "error", { message: error?.data?.message ?? error?.message });
      } else if (event.type === "session.deleted") {
        await finish(sessionId);
      } else if (event.type === "message.updated") {
        const message = properties.info as MessageInfo | undefined;
        if (!message?.id) return;
        messages.set(message.id, message);
        await flushMessage(message.id, message.role === "user" || Boolean(message.time?.completed));
      } else if (event.type === "message.part.updated" && part?.type === "text" && part.messageID) {
        const messageParts = parts.get(part.messageID) ?? new Map<string, string>();
        messageParts.set(part.id ?? "text", part.text ?? "");
        parts.set(part.messageID, messageParts);
        const message = messages.get(part.messageID);
        await flushMessage(
          part.messageID,
          message?.role === "user" || part.time?.end !== undefined,
        );
      }
    },
  };
};
