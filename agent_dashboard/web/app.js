const agents = new Map();
const rules = new Map();
const table = document.querySelector('#agents');
const filter = document.querySelector('#filter');

function renderAgents() {
  const query = filter.value.toLowerCase();
  table.replaceChildren();
  [...agents.values()].filter(a => JSON.stringify(a).toLowerCase().includes(query)).forEach(a => {
    const row = document.createElement('tr');
    const loc = a.location.kind === 'tmux' ? `tmux:${a.location.session}/${a.location.window}.${a.location.pane}` : `Firefox: ${a.location.title || a.location.url}`;
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
  const [snapshot, configured] = await Promise.all([fetch('/api/v1/agents'), fetch('/api/v1/rules')]);
  (await snapshot.json()).agents.forEach(a => agents.set(a.agent_id, a));
  (await configured.json()).forEach(r => rules.set(r.rule_id, r)); renderAgents(); renderRules();
}
filter.addEventListener('input', renderAgents);
document.querySelector('#rule-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = new FormData(event.target);
  const rule = { rule_id: crypto.randomUUID(), name: form.get('name'), action: form.get('action'), status: form.get('status') || null };
  const response = await fetch('/api/v1/rules', { method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(rule) });
  if (response.ok) { const saved = await response.json(); rules.set(saved.rule_id, saved); renderRules(); event.target.reset(); }
});
const stream = new EventSource('/api/v1/events/stream');
stream.addEventListener('ready', () => document.querySelector('#connection').textContent = 'Connected');
stream.addEventListener('agent.updated', event => { const payload = JSON.parse(event.data); agents.set(payload.agent.agent_id, payload.agent); renderAgents(); });
stream.addEventListener('disconnect', () => { stream.close(); document.querySelector('#connection').textContent = 'Disconnected by server'; });
stream.onerror = () => document.querySelector('#connection').textContent = 'Reconnecting…';
load().catch(() => document.querySelector('#connection').textContent = 'Offline');
