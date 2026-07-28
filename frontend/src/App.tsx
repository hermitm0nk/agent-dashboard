import { useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, FormEvent, SetStateAction } from "react";
import type { Agent, AgentEvent, AgentStatus, NotificationAction, Rule, RuleMatchers } from "./types";

const statusLabels: Record<AgentStatus, string> = {
  started: "Working", working: "Working", waiting_for_input: "Ready",
  finished: "Finished", error: "Error", stale: "Stale",
};
const matcherLabels: Record<keyof RuleMatchers, string> = {
  type: "Message type", text: "Message text", agent_id: "Agent ID",
  agent_type: "Agent type", host_id: "Origin host", session_id: "Session ID",
  status: "Agent status", working_dir: "Working directory", model: "Model",
  chat_title: "Chat title",
};
const emptyMatchers = (): RuleMatchers => Object.fromEntries(
  Object.keys(matcherLabels).map((key) => [key, null])) as RuleMatchers;
const emptyRule = (): Rule => ({ rule_id: crypto.randomUUID(), name: "", enabled: true, match: emptyMatchers(), actions: [] });

function workingDirName(path: string) {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.at(-1) || path;
}
function agentDisplayName(agent: Agent) {
  const location = agent.location.kind === "tmux" ? `tmux:${agent.location.pane}` : `firefox:${agent.location.window_tab}`;
  return `<${agent.harness}:${workingDirName(agent.working_dir)}@${agent.host_id}/${location}>`;
}
function workingDirectory(path: string) {
  return path.replace(/^\/home\/[^/]+(?=\/|$)/, "~");
}
function harnessBadge(harness: string) {
  return ({ hermes: "H", opencode: "OC", codex: "Cx", pi: "Pi" } as Record<string, string>)[harness.toLowerCase()] || harness.slice(0, 2).toUpperCase();
}
function sessionColor(sessionId: string) {
  let hash = 0;
  for (const character of sessionId) hash = (hash * 31 + character.charCodeAt(0)) | 0;
  return Math.abs(hash) % 8;
}
function eventText(event: AgentEvent) {
  if (event.message) return event.message;
  return event.event_type === "error" ? "Agent reported an error" : "";
}
function eventLabel(event: AgentEvent) {
  if (event.event_type === "error") return "Error";
  return event.message_role === "user" ? "You" : "Agent";
}
function relativeTime(value: string) {
  const seconds = Math.max(0, (Date.now() - Date.parse(value)) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function StatusIndicator({ status }: { status: AgentStatus }) {
  return <span
    className={`status-indicator status-bg-${status}`}
    role="status"
    aria-label={`Agent status: ${statusLabels[status]}`}
    title={statusLabels[status]}
  />;
}

function SeenIcon({ unseen }: { unseen: boolean }) {
  return unseen
    ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.75 6.75h16.5v11.5H3.75z" /><path d="m4.5 7.5 7.5 6 7.5-6" /></svg>
    : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10.25h16v9H4z" /><path d="m5 10.75 7-5 7 5M8.5 14.25l3.5 2.5 3.5-2.5" /></svg>;
}

function ArchiveIcon({ archived }: { archived: boolean }) {
  return archived
    ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 8.5h14v11H5zM4 5h16v3.5H4zM9 13h6" /><path d="m12 2.75-3 3h6z" /></svg>
    : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 8.5h14v11H5zM4 5h16v3.5H4zM9 13h6" /></svg>;
}

function ActionEditor({ action, onChange, onRemove }: { action: NotificationAction; onChange: (action: NotificationAction) => void; onRemove: () => void }) {
  return <fieldset className="channel-card"><legend>{action.type}</legend>
    {action.type === "native" && <label>Hostname regex <input value={action.hostname_regex} onChange={(event) => onChange({ ...action, hostname_regex: event.target.value })} required /></label>}
    {action.type === "webpush" && <label>Client IDs regex <input value={action.client_ids_regex} onChange={(event) => onChange({ ...action, client_ids_regex: event.target.value })} required /></label>}
    {action.type === "ntfy" && <><label>Topic <input value={action.topic} onChange={(event) => onChange({ ...action, topic: event.target.value })} required /></label><label>Server <input value={action.server} onChange={(event) => onChange({ ...action, server: event.target.value })} required /></label></>}
    <button type="button" className="button danger" onClick={onRemove}>Remove action</button>
  </fieldset>;
}

function RulesScreen({ rules, setRules, reportError }: { rules: Rule[]; setRules: Dispatch<SetStateAction<Rule[]>>; reportError: (message: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Rule>(emptyRule());
  function begin(rule?: Rule) { setDraft(rule ? structuredClone(rule) : emptyRule()); setEditing(true); }
  function addAction(type: NotificationAction["type"]) {
    const action: NotificationAction = type === "native" ? { type, hostname_regex: ".*" }
      : type === "webpush" ? { type, client_ids_regex: ".*" }
      : { type, topic: "", server: "https://ntfy.sh" };
    setDraft({ ...draft, actions: [...draft.actions, action] });
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    const response = await fetch("/api/v1/rules", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(draft) });
    if (!response.ok) { const body = await response.json().catch(() => ({})); reportError(body.detail ? JSON.stringify(body.detail) : "Could not save notification rule."); return; }
    const saved = await response.json() as Rule;
    setRules((current) => current.some((rule) => rule.rule_id === saved.rule_id) ? current.map((rule) => rule.rule_id === saved.rule_id ? saved : rule) : [...current, saved]);
    setEditing(false);
  }
  async function remove(rule: Rule) {
    if (!window.confirm(`Delete “${rule.name}”?`)) return;
    const response = await fetch(`/api/v1/rules/${rule.rule_id}`, { method: "DELETE" });
    if (response.ok) setRules((current) => current.filter((item) => item.rule_id !== rule.rule_id)); else reportError("Could not delete notification rule.");
  }
  return <main>
    <section className="hero"><div><p className="eyebrow">NOTIFICATIONS</p><h2>Route messages with rules.</h2><p className="hero-copy">Regexes search within each value; use ^ and $ for an exact match. Every matching rule runs all of its actions.</p></div><button className="button primary" onClick={() => begin()}>New rule</button></section>
    {editing && <form className="panel rule-form expanded" onSubmit={save}>
      <div className="panel-heading"><div><p className="eyebrow">RULE</p><h2>{draft.name || "New notification rule"}</h2></div><label className="check"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} /> Enabled</label></div>
      <label>Rule name <input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required /></label>
      <h3>Match regular expressions</h3><div className="settings-grid">{(Object.keys(matcherLabels) as (keyof RuleMatchers)[]).map((key) => <label key={key}>{matcherLabels[key]} <input value={draft.match[key] || ""} onChange={(event) => setDraft({ ...draft, match: { ...draft.match, [key]: event.target.value || null } })} placeholder="Any" /></label>)}</div>
      <h3>Notification actions</h3><div className="settings-grid">{draft.actions.map((action, index) => <ActionEditor key={index} action={action} onChange={(value) => setDraft({ ...draft, actions: draft.actions.map((item, itemIndex) => itemIndex === index ? value : item) })} onRemove={() => setDraft({ ...draft, actions: draft.actions.filter((_, itemIndex) => itemIndex !== index) })} />)}</div>
      <div className="row-actions"><select defaultValue="" onChange={(event) => { if (event.target.value) addAction(event.target.value as NotificationAction["type"]); event.target.value = ""; }}><option value="">Add action…</option><option value="native">Native</option><option value="webpush">Webpush</option><option value="ntfy">ntfy</option></select><button className="button primary">Save rule</button><button type="button" className="button secondary" onClick={() => setEditing(false)}>Cancel</button></div>
    </form>}
    <section className="panel rules-panel"><div className="panel-heading"><div><p className="eyebrow">CONFIGURATION</p><h2>Notification rules</h2></div><span className="muted">{rules.length} rules</span></div><ul className="rule-list">{rules.map((rule) => <li key={rule.rule_id}><div><span>{rule.name}</span><span className="muted">{rule.enabled ? "enabled" : "disabled"} · {rule.actions.map((action) => action.type).join(", ") || "no actions"}</span><div className="rule-filters">{Object.entries(rule.match).filter(([, value]) => value).map(([key, value]) => `${key}=${value}`).join(" · ") || "matches every message"}</div></div><span className="row-actions"><button className="button secondary" onClick={() => begin(rule)}>Edit</button><button className="button danger" onClick={() => remove(rule)}>Delete</button></span></li>)}</ul></section>
  </main>;
}

export function App() {
  const [screen, setScreen] = useState<"agents" | "rules">("agents");
  const [agents, setAgents] = useState<Record<string, Agent>>({});
  const [rules, setRules] = useState<Rule[]>([]);
  const [filter, setFilter] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [showArchive, setShowArchive] = useState(false);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const selectedAgentRef = useRef("");
  const [connection, setConnection] = useState("Connecting…");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const key = "agent-dashboard-client-id";
    let clientId = localStorage.getItem(key); if (!clientId) { clientId = crypto.randomUUID(); localStorage.setItem(key, clientId); }
    let source: EventSource | undefined; let retry: number | undefined;
    const connect = () => { source = new EventSource(`/api/v1/events/stream?client_id=${encodeURIComponent(clientId!)}`); source.addEventListener("ready", () => setConnection("Connected")); source.addEventListener("snapshot", (event) => { const snapshot = JSON.parse((event as MessageEvent<string>).data) as { agents: Agent[] }; setAgents(Object.fromEntries(snapshot.agents.map((agent) => [agent.agent_id, agent]))); setSelectedAgentId((current) => current || snapshot.agents[0]?.agent_id || ""); }); source.addEventListener("agent.updated", (event) => { const payload = JSON.parse((event as MessageEvent<string>).data) as { agent: Agent; event?: AgentEvent }; setAgents((current) => ({ ...current, [payload.agent.agent_id]: payload.agent })); setSelectedAgentId((current) => current || payload.agent.agent_id); if (payload.event && selectedAgentRef.current === payload.event.agent_id) setEvents((current) => current.some((item) => item.event_id === payload.event!.event_id) ? current : [...current, payload.event!].sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))); }); source.addEventListener("notification", (event) => { const item = (JSON.parse((event as MessageEvent<string>).data) as { notification: { title: string; body: string } }).notification; if ("Notification" in window && Notification.permission === "granted") new Notification(item.title, { body: item.body }); }); source.addEventListener("disconnect", () => source?.close()); source.onerror = () => { setConnection("Reconnecting…"); source?.close(); retry = window.setTimeout(connect, 1000); }; };
    connect(); return () => { source?.close(); if (retry) clearTimeout(retry); };
  }, []);
  useEffect(() => { fetch("/api/v1/rules", { cache: "no-store" }).then((response) => response.json()).then(setRules).catch(() => setError("Could not load notification rules.")); }, []);
  useEffect(() => {
    selectedAgentRef.current = selectedAgentId;
    if (!selectedAgentId) { setEvents([]); return; }
    const controller = new AbortController(); setHistoryLoading(true);
    fetch(`/api/v1/agents/${encodeURIComponent(selectedAgentId)}/events`, { cache: "no-store", signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<AgentEvent[]>; })
      .then(setEvents).catch((reason) => { if (reason.name !== "AbortError") setError("Could not load agent messages."); })
      .finally(() => { if (!controller.signal.aborted) setHistoryLoading(false); });
    return () => controller.abort();
  }, [selectedAgentId]);
  const visibleAgents = useMemo(() => {
    const query = filter.toLowerCase();
    return Object.values(agents)
      .filter((agent) => agent.archived === showArchive)
      .filter((agent) => JSON.stringify(agent).toLowerCase().includes(query))
      .sort((a, b) => {
        const ready = (status: AgentStatus) => status === "waiting_for_input" ? 0 : 1;
        return Number(b.unseen) - Number(a.unseen)
          || ready(a.status) - ready(b.status)
          || Date.parse(b.last_event_at) - Date.parse(a.last_event_at);
      });
  }, [agents, filter, showArchive]);
  const unseenCount = useMemo(
    () => Object.values(agents).filter((agent) => agent.unseen).length,
    [agents],
  );
  useEffect(() => {
    if (!visibleAgents.some((agent) => agent.agent_id === selectedAgentId)) {
      setSelectedAgentId(visibleAgents[0]?.agent_id || "");
    }
  }, [selectedAgentId, visibleAgents]);
  const selectedAgent = agents[selectedAgentId];
  async function enableWebNotifications() { if ("Notification" in window && await Notification.requestPermission() !== "granted") setError("Browser notifications are not enabled."); }
  async function focus(agent: Agent) { const response = await fetch(`/api/v1/agents/${encodeURIComponent(agent.agent_id)}/focus`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }); if (!response.ok) setError(((await response.json()) as { detail?: string }).detail || "Focus failed."); }
  async function setSeen(agent: Agent, seen: boolean) {
    const response = await fetch(`/api/v1/agents/${encodeURIComponent(agent.agent_id)}/seen`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ seen }),
    });
    if (!response.ok) { setError("Could not update seen state."); return; }
    const updated = await response.json() as Agent;
    setAgents((current) => ({ ...current, [updated.agent_id]: updated }));
  }
  async function markAllSeen() {
    const response = await fetch("/api/v1/agents/seen-all", { method: "POST" });
    if (!response.ok) { setError("Could not mark all conversations as seen."); return; }
    const snapshot = await response.json() as { agents: Agent[] };
    setAgents(Object.fromEntries(snapshot.agents.map((agent) => [agent.agent_id, agent])));
  }
  async function setArchived(agent: Agent, archived: boolean) {
    const response = await fetch(`/api/v1/agents/${encodeURIComponent(agent.agent_id)}/archive`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ archived }),
    });
    if (!response.ok) { setError(`Could not ${archived ? "archive" : "restore"} conversation.`); return; }
    const updated = await response.json() as Agent;
    setAgents((current) => ({ ...current, [updated.agent_id]: updated }));
  }
  return <div className="app-shell"><header className="topbar"><div><p className="eyebrow">COMMAND CENTER</p><h1>Agent Dashboard</h1></div><nav className="row-actions"><button className={`button ${screen === "agents" ? "primary" : "secondary"}`} onClick={() => setScreen("agents")}>Agents</button><button className={`button ${screen === "rules" ? "primary" : "secondary"}`} onClick={() => setScreen("rules")}>Notification rules</button><button className="button secondary" onClick={enableWebNotifications}>Enable web notifications</button><span className={`connection-dot ${connection === "Connected" ? "online" : ""}`} />{connection}</nav></header>
    {error && <div className="notice" role="alert">{error}<button onClick={() => setError(null)}>Dismiss</button></div>}
    {screen === "rules" ? <RulesScreen rules={rules} setRules={setRules} reportError={setError} /> : <main className="chat-layout panel">
      <aside className="agent-sidebar"><div className="sidebar-head"><div><p className="eyebrow">CONVERSATIONS</p><h2>{showArchive ? "Archive" : "Agents"}</h2></div><span className="agent-count">{visibleAgents.length}</span></div><div className="archive-toggle"><button className={`button ${!showArchive ? "primary" : "secondary"}`} onClick={() => setShowArchive(false)}>Active</button><button className={`button ${showArchive ? "primary" : "secondary"}`} onClick={() => setShowArchive(true)}>Archive</button></div><div className="inbox-toolbar"><span><i className="unread-dot" />{unseenCount} unseen</span><button className="mark-all-button" disabled={!unseenCount} onClick={markAllSeen}>Mark all as seen</button></div><label className="search"><span>⌕</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search agents" /></label><div className="agent-list">{visibleAgents.map((agent) => <div key={agent.agent_id} role="button" tabIndex={0} className={`agent-item ${agent.unseen ? "unseen" : "seen"} ${agent.agent_id === selectedAgentId ? "selected" : ""}`} onClick={() => setSelectedAgentId(agent.agent_id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedAgentId(agent.agent_id); } }}><span className={`avatar session-color-${sessionColor(agent.session_id)}`}>{harnessBadge(agent.harness)}</span><span className="agent-item-copy"><strong className="agent-workdir" title={agent.working_dir}>{workingDirectory(agent.working_dir)}</strong><span className="agent-model" title={agent.model || "Model unavailable"}>{agent.model || "Model unavailable"}{agent.effort ? ` · ${agent.effort}` : ""}</span><span className="agent-host" title={agent.host_id}>{agent.host_id}</span></span><span className="agent-item-meta"><span className="agent-meta-top"><StatusIndicator status={agent.status} /><time>{relativeTime(agent.last_event_at)}</time></span><span className="item-actions"><button className={`session-action seen-action ${agent.unseen ? "has-unread" : ""}`} aria-label={agent.unseen ? "Mark conversation as seen" : "Mark conversation as unseen"} aria-pressed={!agent.unseen} title={agent.unseen ? "Mark as seen" : "Mark as unseen"} onClick={(event) => { event.stopPropagation(); void setSeen(agent, agent.unseen); }}><SeenIcon unseen={agent.unseen} /></button><button className="session-action archive-action" aria-label={agent.archived ? "Restore conversation" : "Archive conversation"} title={agent.archived ? "Restore from archive" : "Archive conversation"} onClick={(event) => { event.stopPropagation(); void setArchived(agent, !agent.archived); }}><ArchiveIcon archived={agent.archived} /></button></span></span></div>)}{!visibleAgents.length && <div className="empty">No matching agents</div>}</div></aside>
      <section className="conversation">{selectedAgent ? <><header className="conversation-head"><div><h2>{agentDisplayName(selectedAgent)}</h2><span className={`status status-${selectedAgent.status}`} title={statusLabels[selectedAgent.status]} aria-label={`Agent status: ${statusLabels[selectedAgent.status]}`}><i />{selectedAgent.model || selectedAgent.harness}</span></div><div className="row-actions"><button className="button secondary" onClick={() => setArchived(selectedAgent, !selectedAgent.archived)}>{selectedAgent.archived ? "Restore" : "Archive"}</button><button className="button secondary seen-detail-button" onClick={() => setSeen(selectedAgent, selectedAgent.unseen)}>{selectedAgent.unseen ? "Mark as seen" : "Mark as unseen"}</button><button className="button primary" onClick={() => focus(selectedAgent)}>Focus agent</button></div></header><div className="message-list">{historyLoading && <div className="conversation-empty">Loading messages…</div>}{!historyLoading && events.filter((item) => item.event_type === "message" || item.event_type === "error").map((item) => <article className={`message-bubble event-${item.event_type} message-${item.message_role || "system"}`} key={item.event_id}><div className="message-meta"><span>{eventLabel(item)}</span><time>{new Date(item.timestamp).toLocaleString()}</time></div><p>{eventText(item)}</p>{item.model && <small>{item.model}</small>}</article>)}{!historyLoading && !events.some((item) => item.event_type === "message" || item.event_type === "error") && <div className="conversation-empty">No messages recorded for this agent yet.</div>}</div></> : <div className="conversation-empty">Select an agent to see its messages.</div>}</section>
    </main>}
  </div>;
}
