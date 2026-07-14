const agents = new Map();
const rules = new Map();
const table = document.querySelector('#agents');
const filter = document.querySelector('#filter');

function upsertAgent(agent) {
  const current = agents.get(agent.agent_id);
  if (!current || !current.last_event_at || !agent.last_event_at ||
      Date.parse(agent.last_event_at) >= Date.parse(current.last_event_at)) {
    agents.set(agent.agent_id, agent);
  }
}

function renderAgents() {
  const query = filter.value.toLowerCase();
  table.replaceChildren();
  [...agents.values()].filter(a => JSON.stringify(a).toLowerCase().includes(query)).forEach(a => {
    const row = document.createElement('tr');
    const loc = a.location.kind === 'tmux' ? `tmux:${a.location.pane}` : `Firefox: ${a.location.title || a.location.url}`;
    [a.agent_id, a.status, a.harness, a.host_id, a.last_message || a.last_event_type, loc].forEach((value, i) => {
      const cell = document.createElement('td'); cell.textContent = value;
      if (i === 1) cell.className = `status-${a.status}`; row.append(cell);
    });
    const focus = document.createElement('button'); focus.textContent = 'Focus';
    focus.onclick = async () => {
      const response = await fetch(`/api/v1/agents/${encodeURIComponent(a.agent_id)}/focus`, {method: 'POST', headers: {'content-type': 'application/json'}, body: '{}'});
      if (!response.ok) alert((await response.json()).detail || 'Focus failed');
    };
    const action = document.createElement('td'); action.append(focus); row.append(action); table.append(row);
  });
  if (!table.children.length) { const row = document.createElement('tr'); row.innerHTML = '<td colspan="5">No matching agents</td>'; table.append(row); }
}
function renderRules() {
  const list = document.querySelector('#rules'); list.replaceChildren();
  rules.forEach(rule => { const item = document.createElement('li'); item.textContent = `${rule.name}: ${rule.action} (${rule.status || 'any status'})`; list.append(item); });
}
async function load() {
  const configured = await fetch('/api/v1/rules', { cache: 'no-store' });
  (await configured.json()).forEach(r => rules.set(r.rule_id, r));
  renderRules();
}
filter.addEventListener('input', renderAgents);
document.querySelector('#rule-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = new FormData(event.target);
  const rule = { rule_id: crypto.randomUUID(), name: form.get('name'), action: form.get('action'), status: form.get('status') || null };
  const response = await fetch('/api/v1/rules', { method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(rule) });
  if (response.ok) { const saved = await response.json(); rules.set(saved.rule_id, saved); renderRules(); event.target.reset(); }
});
let stream;
function connectStream() {
  stream = new EventSource('/api/v1/events/stream');
  stream.addEventListener('ready', () => {
    document.querySelector('#connection').textContent = 'Connected';
  });
  stream.addEventListener('snapshot', event => {
    agents.clear();
    JSON.parse(event.data).agents.forEach(upsertAgent);
    renderAgents();
  });
  stream.addEventListener('agent.updated', event => {
    const payload = JSON.parse(event.data); upsertAgent(payload.agent); renderAgents();
  });
  stream.addEventListener('disconnect', () => {
    stream.close();
    document.querySelector('#connection').textContent = 'Reconnecting…';
    setTimeout(connectStream, 1000);
  });
  stream.onerror = () => document.querySelector('#connection').textContent = 'Reconnecting…';
}
connectStream();
load().catch(() => document.querySelector('#connection').textContent = 'Offline');
