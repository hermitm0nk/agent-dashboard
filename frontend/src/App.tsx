import { useEffect, useMemo, useState } from "react";
import type { Dispatch, FormEvent, SetStateAction } from "react";
import type { Agent, AgentStatus, NotificationAction, Rule, RuleMatchers } from "./types";

const statusLabels: Record<AgentStatus, string> = {
  started: "Started", working: "Working", waiting_for_input: "Needs input",
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

function locationLabel(agent: Agent) {
  return agent.location.kind === "tmux" ? `tmux:${agent.location.pane}` : `Firefox: ${agent.location.title || agent.location.url}`;
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
  const [connection, setConnection] = useState("Connecting…");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const key = "agent-dashboard-client-id";
    let clientId = localStorage.getItem(key); if (!clientId) { clientId = crypto.randomUUID(); localStorage.setItem(key, clientId); }
    let source: EventSource | undefined; let retry: number | undefined;
    const connect = () => { source = new EventSource(`/api/v1/events/stream?client_id=${encodeURIComponent(clientId!)}`); source.addEventListener("ready", () => setConnection("Connected")); source.addEventListener("snapshot", (event) => { const snapshot = JSON.parse((event as MessageEvent<string>).data) as { agents: Agent[] }; setAgents(Object.fromEntries(snapshot.agents.map((agent) => [agent.agent_id, agent]))); }); source.addEventListener("agent.updated", (event) => { const agent = (JSON.parse((event as MessageEvent<string>).data) as { agent: Agent }).agent; setAgents((current) => ({ ...current, [agent.agent_id]: agent })); }); source.addEventListener("notification", (event) => { const item = (JSON.parse((event as MessageEvent<string>).data) as { notification: { title: string; body: string } }).notification; if ("Notification" in window && Notification.permission === "granted") new Notification(item.title, { body: item.body }); }); source.addEventListener("disconnect", () => source?.close()); source.onerror = () => { setConnection("Reconnecting…"); source?.close(); retry = window.setTimeout(connect, 1000); }; };
    connect(); return () => { source?.close(); if (retry) clearTimeout(retry); };
  }, []);
  useEffect(() => { fetch("/api/v1/rules", { cache: "no-store" }).then((response) => response.json()).then(setRules).catch(() => setError("Could not load notification rules.")); }, []);
  const visibleAgents = useMemo(() => { const query = filter.toLowerCase(); return Object.values(agents).filter((agent) => JSON.stringify(agent).toLowerCase().includes(query)); }, [agents, filter]);
  async function enableWebNotifications() { if ("Notification" in window && await Notification.requestPermission() !== "granted") setError("Browser notifications are not enabled."); }
  async function focus(agent: Agent) { const response = await fetch(`/api/v1/agents/${encodeURIComponent(agent.agent_id)}/focus`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" }); if (!response.ok) setError(((await response.json()) as { detail?: string }).detail || "Focus failed."); }
  return <div className="app-shell"><header className="topbar"><div><p className="eyebrow">COMMAND CENTER</p><h1>Agent Dashboard</h1></div><nav className="row-actions"><button className={`button ${screen === "agents" ? "primary" : "secondary"}`} onClick={() => setScreen("agents")}>Agents</button><button className={`button ${screen === "rules" ? "primary" : "secondary"}`} onClick={() => setScreen("rules")}>Notification rules</button><button className="button secondary" onClick={enableWebNotifications}>Enable web notifications</button><span className={`connection-dot ${connection === "Connected" ? "online" : ""}`} />{connection}</nav></header>
    {error && <div className="notice" role="alert">{error}<button onClick={() => setError(null)}>Dismiss</button></div>}
    {screen === "rules" ? <RulesScreen rules={rules} setRules={setRules} reportError={setError} /> : <main><section className="hero"><div><p className="eyebrow">LIVE WORKSPACE</p><h2>Keep every agent in view.</h2><p className="hero-copy">Monitor activity across harnesses and jump to the session that needs you.</p></div><div className="stat"><strong>{visibleAgents.length}</strong><span>visible agents</span></div></section><section className="panel"><div className="panel-heading"><div><p className="eyebrow">SESSIONS</p><h2>Agents</h2></div><label className="search"><span>⌕</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search agents, hosts, status…" /></label></div><div className="table-wrap"><table><thead><tr><th>Agent</th><th>Status</th><th>Harness</th><th>Host</th><th>Latest activity</th><th>Location</th><th /></tr></thead><tbody>{visibleAgents.map((agent) => <tr key={agent.agent_id}><td><div className="agent-name">{agent.chat_title || agent.agent_id}</div><div className="muted">{agent.agent_id}</div></td><td><span className={`status status-${agent.status}`}><i />{statusLabels[agent.status]}</span></td><td>{agent.harness}</td><td className="muted">{agent.host_id}</td><td><div className="activity">{agent.last_message || agent.last_event_type}</div><div className="muted">{relativeTime(agent.last_event_at)}</div></td><td className="muted location">{locationLabel(agent)}</td><td><button className="button secondary" onClick={() => focus(agent)}>Focus</button></td></tr>)}{!visibleAgents.length && <tr><td className="empty" colSpan={7}>No matching agents</td></tr>}</tbody></table></div></section></main>}
  </div>;
}
