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
      .filter((agent) => showArchive || agent.status !== "finished")
      .filter((agent) => JSON.stringify(agent).toLowerCase().includes(query))
      .sort((a, b) => {
        const ready = (status: AgentStatus) => status === "waiting_for_input" ? 0 : 1;
        return ready(a.status) - ready(b.status) || Date.parse(b.last_event_at) - Date.parse(a.last_event_at);
      });
  }, [agents, filter, showArchive]);
  useEffect(() => {
    if (!visibleAgents.some((agent) => agent.agent_id === selectedAgentId)) {
      setSelectedAgentId(visibleAgents[0]?.agent_id || "");
    }
  }, [selectedAgentId, visibleAgents]);
  const selectedAgent = agents[selectedAgentId];
  async function enableWebNotifications() { if ("Notification" in window && await Notification.requestPermission() !== "granted") setError("Browser notifications are not enabled."); }
  async function focus(agent: Agent) { const response = await fetch(`/api/v1/agents/${encodeURIComponent(agent.agent_id)}/focus`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }); if (!response.ok) setError(((await response.json()) as { detail?: string }).detail || "Focus failed."); }
  return <div className="app-shell"><header className="topbar"><div><p className="eyebrow">COMMAND CENTER</p><h1>Agent Dashboard</h1></div><nav className="row-actions"><button className={`button ${screen === "agents" ? "primary" : "secondary"}`} onClick={() => setScreen("agents")}>Agents</button><button className={`button ${screen === "rules" ? "primary" : "secondary"}`} onClick={() => setScreen("rules")}>Notification rules</button><button className="button secondary" onClick={enableWebNotifications}>Enable web notifications</button><span className={`connection-dot ${connection === "Connected" ? "online" : ""}`} />{connection}</nav></header>
    {error && <div className="notice" role="alert">{error}<button onClick={() => setError(null)}>Dismiss</button></div>}
    {screen === "rules" ? <RulesScreen rules={rules} setRules={setRules} reportError={setError} /> : <main className="chat-layout panel">
      <aside className="agent-sidebar"><div className="sidebar-head"><div><p className="eyebrow">CONVERSATIONS</p><h2>{showArchive ? "Archive" : "Agents"}</h2></div><span className="agent-count">{visibleAgents.length}</span></div><div className="archive-toggle"><button className={`button ${!showArchive ? "primary" : "secondary"}`} onClick={() => setShowArchive(false)}>Active</button><button className={`button ${showArchive ? "primary" : "secondary"}`} onClick={() => setShowArchive(true)}>Archive</button></div><label className="search"><span>⌕</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search agents" /></label><div className="agent-list">{visibleAgents.map((agent) => <button key={agent.agent_id} className={`agent-item ${agent.agent_id === selectedAgentId ? "selected" : ""}`} onClick={() => setSelectedAgentId(agent.agent_id)}><span className={`avatar status-bg-${agent.status}`}>{agent.harness.slice(0, 2).toUpperCase()}</span><span className="agent-item-copy"><strong>{agentDisplayName(agent)}</strong><span>{agent.last_message || statusLabels[agent.status]}</span></span><span className="agent-item-meta"><time>{relativeTime(agent.last_event_at)}</time><i className={`state-dot status-bg-${agent.status}`} /></span></button>)}{!visibleAgents.length && <div className="empty">No matching agents</div>}</div></aside>
      <section className="conversation">{selectedAgent ? <><header className="conversation-head"><div><h2>{agentDisplayName(selectedAgent)}</h2><span className={`status status-${selectedAgent.status}`}><i />{statusLabels[selectedAgent.status]} · {selectedAgent.model || selectedAgent.harness}</span></div><button className="button primary" onClick={() => focus(selectedAgent)}>Focus agent</button></header><div className="message-list">{historyLoading && <div className="conversation-empty">Loading messages…</div>}{!historyLoading && events.filter((item) => item.event_type === "message" || item.event_type === "error").map((item) => <article className={`message-bubble event-${item.event_type} message-${item.message_role || "system"}`} key={item.event_id}><div className="message-meta"><span>{eventLabel(item)}</span><time>{new Date(item.timestamp).toLocaleString()}</time></div><p>{eventText(item)}</p>{item.model && <small>{item.model}</small>}</article>)}{!historyLoading && !events.some((item) => item.event_type === "message" || item.event_type === "error") && <div className="conversation-empty">No messages recorded for this agent yet.</div>}</div></> : <div className="conversation-empty">Select an agent to see its messages.</div>}</section>
    </main>}
  </div>;
}
