const agents = new Map();
const rules = new Map();
const table = document.querySelector('#agents');
const filter = document.querySelector('#filter');

function randomUuid() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0'));
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`;
}

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
    const loc = `tmux:${a.location.pane}`;
    [a.agent_id, a.status, a.harness, a.host_id, a.last_message || a.last_event_type, loc].forEach((value, i) => {
      const cell = document.createElement('td'); cell.textContent = value;
      if (i === 1) cell.className = `status-${a.status}`; row.append(cell);
    });
    const focus = document.createElement('button'); focus.textContent = 'Focus';
    focus.onclick = async () => {
      const response = await fetch(`api/v1/agents/${encodeURIComponent(a.agent_id)}/focus`, {method: 'POST', headers: {'content-type': 'application/json'}, body: '{}'});
      if (!response.ok) alert((await response.json()).detail || 'Focus failed');
    };
    const action = document.createElement('td'); action.append(focus); row.append(action); table.append(row);
  });
  if (!table.children.length) { const row = document.createElement('tr'); row.innerHTML = '<td colspan="5">No matching agents</td>'; table.append(row); }
}
function renderRules() {
  const list = document.querySelector('#rules'); list.replaceChildren();
  rules.forEach(rule => { const item = document.createElement('li'); const match = Object.entries(rule.match).filter(([, value]) => value).map(([key, value]) => `${key}=${value}`).join(', ') || 'all messages'; item.textContent = `${rule.name}: ${rule.actions.map(action => action.type).join(', ') || 'no actions'} (${match})`; list.append(item); });
}
async function load() {
  const configured = await fetch('api/v1/rules', { cache: 'no-store' });
  (await configured.json()).forEach(r => rules.set(r.rule_id, r));
  renderRules();
}
filter.addEventListener('input', renderAgents);
document.querySelector('#agents-nav').onclick = () => { document.querySelector('#agents-screen').hidden = false; document.querySelector('#rules-screen').hidden = true; };
document.querySelector('#rules-nav').onclick = () => { document.querySelector('#agents-screen').hidden = true; document.querySelector('#rules-screen').hidden = false; };
let stream;
function connectStream() {
  let clientId = localStorage.getItem('agent-dashboard-client-id');
  if (!clientId) { clientId = randomUuid(); localStorage.setItem('agent-dashboard-client-id', clientId); }
  stream = new EventSource(`api/v1/events/stream?client_id=${encodeURIComponent(clientId)}`);
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
