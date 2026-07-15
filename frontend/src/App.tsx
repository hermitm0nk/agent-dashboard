import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import type { Agent, Rule } from "./types";

const statusLabels: Record<Agent["status"], string> = {
  started: "Started", working: "Working", waiting_for_input: "Needs input",
  finished: "Finished", error: "Error", stale: "Stale",
};

function locationLabel(agent: Agent) {
  return agent.location.kind === "tmux"
    ? `tmux:${agent.location.pane}`
    : `Firefox: ${agent.location.title || agent.location.url}`;
}

function relativeTime(value: string) {
  const seconds = Math.max(0, (Date.now() - Date.parse(value)) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function App() {
  const [agents, setAgents] = useState<Record<string, Agent>>({});
  const [rules, setRules] = useState<Rule[]>([]);
  const [filter, setFilter] = useState("");
  const [connection, setConnection] = useState("Connecting…");
  const [ruleName, setRuleName] = useState("");
  const [ruleAction, setRuleAction] = useState<Rule["action"]>("silence");
  const [ruleStatus, setRuleStatus] = useState<Rule["status"]>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let source: EventSource | undefined;
    let retry: number | undefined;
    const connect = () => {
      source = new EventSource("/api/v1/events/stream");
      source.addEventListener("ready", () => setConnection("Connected"));
      source.addEventListener("snapshot", (event) => {
        const snapshot = JSON.parse((event as MessageEvent<string>).data) as { agents: Agent[] };
        setAgents(Object.fromEntries(snapshot.agents.map((agent) => [agent.agent_id, agent])));
      });
      source.addEventListener("agent.updated", (event) => {
        const agent = (JSON.parse((event as MessageEvent<string>).data) as { agent: Agent }).agent;
        setAgents((current) => ({ ...current, [agent.agent_id]: agent }));
      });
      source.addEventListener("disconnect", () => source?.close());
      source.onerror = () => {
        setConnection("Reconnecting…"); source?.close(); retry = window.setTimeout(connect, 1000);
      };
    };
    connect();
    return () => { source?.close(); if (retry) window.clearTimeout(retry); };
  }, []);

  useEffect(() => {
    fetch("/api/v1/rules", { cache: "no-store" })
      .then((response) => response.json() as Promise<Rule[]>)
      .then(setRules)
      .catch(() => setError("Could not load notification rules."));
  }, []);

  const visibleAgents = useMemo(() => {
    const query = filter.toLowerCase();
    return Object.values(agents).filter((agent) => JSON.stringify(agent).toLowerCase().includes(query));
  }, [agents, filter]);

  async function focus(agent: Agent) {
    const response = await fetch(`/api/v1/agents/${encodeURIComponent(agent.agent_id)}/focus`, {
      method: "POST", headers: { "content-type": "application/json" }, body: "{}",
    });
    if (!response.ok) setError(((await response.json()) as { detail?: string }).detail || "Focus failed.");
  }

  async function addRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const rule: Rule = { rule_id: crypto.randomUUID(), name: ruleName, action: ruleAction, status: ruleStatus, enabled: true };
    const response = await fetch("/api/v1/rules", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(rule) });
    if (response.ok) {
      const saved = (await response.json()) as Rule;
      setRules((current) => [...current, saved]); setRuleName(""); setRuleStatus(null);
    }
    else setError("Could not save notification rule.");
  }

  return <div className="app-shell">
    <header className="topbar"><div><p className="eyebrow">COMMAND CENTER</p><h1>Agent Dashboard</h1></div><div className="connection"><span className={`connection-dot ${connection === "Connected" ? "online" : ""}`} />{connection}</div></header>
    <section className="hero"><div><p className="eyebrow">LIVE WORKSPACE</p><h2>Keep every agent in view.</h2><p className="hero-copy">Monitor activity across harnesses and jump to the session that needs you.</p></div><div className="stat"><strong>{visibleAgents.length}</strong><span>visible agents</span></div></section>
    {error && <div className="notice" role="alert">{error}<button onClick={() => setError(null)}>Dismiss</button></div>}
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">SESSIONS</p><h2>Agents</h2></div><label className="search"><span>⌕</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search agents, hosts, status…" /></label></div>
      <div className="table-wrap"><table><thead><tr><th>Agent</th><th>Status</th><th>Harness</th><th>Host</th><th>Latest activity</th><th>Location</th><th /></tr></thead><tbody>
        {visibleAgents.map((agent) => <tr key={agent.agent_id}><td><div className="agent-name">{agent.chat_title || agent.agent_id}</div><div className="muted">{agent.agent_id}</div></td><td><span className={`status status-${agent.status}`}><i />{statusLabels[agent.status]}</span></td><td>{agent.harness}</td><td className="muted">{agent.host_id}</td><td><div className="activity">{agent.last_message || agent.last_event_type}</div><div className="muted">{relativeTime(agent.last_event_at)}</div></td><td className="muted location">{locationLabel(agent)}</td><td><button className="button secondary" onClick={() => focus(agent)}>Focus</button></td></tr>)}
        {!visibleAgents.length && <tr><td className="empty" colSpan={7}>No matching agents</td></tr>}
      </tbody></table></div>
    </section>
    <section className="panel rules-panel"><div className="panel-heading"><div><p className="eyebrow">AUTOMATION</p><h2>Notification rules</h2></div></div><form className="rule-form" onSubmit={addRule}><input value={ruleName} onChange={(event) => setRuleName(event.target.value)} placeholder="Rule name" required /><select value={ruleAction} onChange={(event) => setRuleAction(event.target.value as Rule["action"])}><option value="silence">Silence</option><option value="notify">Notify</option></select><select value={ruleStatus || ""} onChange={(event) => setRuleStatus((event.target.value || null) as Rule["status"])}><option value="">Any status</option><option value="working">Working</option><option value="waiting_for_input">Needs input</option><option value="finished">Finished</option><option value="error">Error</option></select><button className="button primary">Add rule</button></form><ul className="rule-list">{rules.map((rule) => <li key={rule.rule_id}><span>{rule.name}</span><span className="muted">{rule.action} · {rule.status ? statusLabels[rule.status] : "any status"}</span></li>)}</ul></section>
  </div>;
}
