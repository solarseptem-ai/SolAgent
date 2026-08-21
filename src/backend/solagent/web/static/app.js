const state = {
  messages: [],
  isStreaming: false,
  currentAssistantMsg: null,
  currentToolMsg: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function init() {
  loadConfig();
  setInterval(refreshMetrics, 10000);
  refreshMetrics();

  $('#send-btn').addEventListener('click', sendMessage);
  $('#user-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  $$('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
  });
}

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    const cfg = await res.json();
    renderConfig(cfg);

    const agentSelect = $('#agent-select');
    agentSelect.innerHTML = '<option value="">Default Agent</option>';
    cfg.agents.forEach(a => {
      agentSelect.innerHTML += `<option value="${a.name}">${a.name} (${a.mode})</option>`;
    });

    const templateSelect = $('#template-select');
    templateSelect.innerHTML = '<option value="">No Template</option>';
    cfg.prompt_templates.forEach(t => {
      templateSelect.innerHTML += `<option value="${t}">${t}</option>`;
    });
  } catch (e) {
    console.error('Failed to load config:', e);
  }
}

function renderConfig(cfg) {
  const el = $('#config-content');
  el.innerHTML = `
    <div class="config-section">
      <h3>Defaults</h3>
      <p style="font-size:13px">Model: <code>${cfg.default_model}</code> | Mode: <code>${cfg.default_mode}</code></p>
    </div>
    <div class="config-section">
      <h3>Providers (${cfg.providers.length})</h3>
      <table class="config-table">
        <tr><th>Name</th><th>Default Model</th><th>Models</th></tr>
        ${cfg.providers.map(p => `<tr><td>${p.name}</td><td><code>${p.default_model}</code></td><td>${(p.models||[]).join(', ')}</td></tr>`).join('')}
      </table>
    </div>
    <div class="config-section">
      <h3>Agents (${cfg.agents.length})</h3>
      <table class="config-table">
        <tr><th>Name</th><th>Model</th><th>Mode</th><th>Tools</th></tr>
        ${cfg.agents.map(a => `<tr><td>${a.name}</td><td><code>${a.model}</code></td><td>${a.mode}</td><td>${(a.tools||[]).join(', ')}</td></tr>`).join('')}
      </table>
    </div>
    <div class="config-section">
      <h3>Prompt Templates (${cfg.prompt_templates.length})</h3>
      <div class="mode-list">${cfg.prompt_templates.map(t => `<span class="mode-tag">${t}</span>`).join('')}</div>
    </div>
  `;
}

async function refreshMetrics() {
  try {
    const res = await fetch('/api/metrics');
    const m = await res.json();
    $('#metric-requests').textContent = m.total_requests;
    $('#metric-input-tokens').textContent = (m.total_tokens?.input || 0).toLocaleString();
    $('#metric-output-tokens').textContent = (m.total_tokens?.output || 0).toLocaleString();
    $('#metric-providers').textContent = m.active_providers;
    $('#agent-modes').innerHTML = (m.agent_modes || []).map(m => `<span class="mode-tag">${m}</span>`).join('');
  } catch (e) {}
}

function switchView(view) {
  $$('.view').forEach(v => v.classList.remove('active'));
  $$('.nav-btn').forEach(b => b.classList.remove('active'));
  $(`#view-${view}`).classList.add('active');
  $(`.nav-btn[data-view="${view}"]`).classList.add('active');
  if (view === 'dashboard') refreshMetrics();
  if (view === 'config') loadConfig();
  if (view === 'learning') loadLearning();
}

async function sendMessage() {
  const input = $('#user-input');
  const text = input.value.trim();
  if (!text || state.isStreaming) return;

  input.value = '';
  input.focus();
  state.isStreaming = true;
  $('#send-btn').disabled = true;

  addMessage('user', text);
  state.messages.push({ role: 'user', content: text });

  const useStream = $('#stream-toggle').checked;
  const agentName = $('#agent-select').value;
  const mode = $('#mode-select').value;
  const template = $('#template-select').value;

  if (useStream) {
    await sendStreaming(text, agentName, mode, template);
  } else {
    await sendNonStreaming(text, agentName, mode, template);
  }

  state.isStreaming = false;
  $('#send-btn').disabled = false;
}

async function sendStreaming(text, agentName, mode, template) {
  state.currentAssistantMsg = null;
  state.currentToolMsg = null;

  const params = new URLSearchParams({ message: text });
  if (agentName) params.set('agent_name', agentName);
  if (mode) params.set('mode', mode);
  if (template) params.set('prompt_template', template);

  try {
    const res = await fetch(`/api/agents/stream?${params}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          handleStreamEvent(data);
        } catch (e) {}
      }
    }
    if (buf.startsWith('data: ')) {
      try { handleStreamEvent(JSON.parse(buf.slice(6))); } catch (e) {}
    }
  } catch (e) {
    addMessage('error', `Connection error: ${e.message}`);
  }

  finishStreaming();
}

function handleStreamEvent(data) {
  if (data.tool_calls && data.tool_calls.length > 0) {
    for (const tc of data.tool_calls) {
      addMessage('tool', `[Tool: ${tc.name || tc.id}]`);
    }
  }
  if (data.content) {
    if (!state.currentAssistantMsg) {
      state.currentAssistantMsg = addMessage('assistant', '');
    }
    state.currentAssistantMsg.textContent += data.content;
    scrollToBottom();
  }
  if (data.tool_results && data.tool_results.length > 0) {
    for (const tr of data.tool_results) {
      const preview = (tr.output || '').slice(0, 200);
      if (preview) addMessage('tool', `[Result] ${preview}`);
    }
  }
  if (data.is_final) {
    finishStreaming();
  }
}

function finishStreaming() {
  if (state.currentAssistantMsg) {
    state.messages.push({ role: 'assistant', content: state.currentAssistantMsg.textContent });
    state.currentAssistantMsg = null;
  }
  scrollToBottom();
}

async function sendNonStreaming(text, agentName, mode, template) {
  try {
    const res = await fetch('/api/agents/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages: state.messages,
        agent_name: agentName || '',
        mode: mode || '',
        stream: false,
        prompt_template: template || '',
      }),
    });
    const data = await res.json();
    if (data.error) {
      addMessage('error', data.error);
    } else {
      addMessage('assistant', data.content);
      state.messages.push({ role: 'assistant', content: data.content });
    }
  } catch (e) {
    addMessage('error', `Request failed: ${e.message}`);
  }
}

function addMessage(role, content) {
  const el = document.createElement('div');
  el.className = `message ${role}`;
  el.textContent = content;
  $('#messages').appendChild(el);
  scrollToBottom();
  return el;
}

function scrollToBottom() {
  const msgs = $('#messages');
  msgs.scrollTop = msgs.scrollHeight;
}

function checkHealth() {
  fetch('/api/health')
    .then(r => r.json())
    .then(() => {
      $('#status').textContent = 'Connected';
      $('#status').className = 'status connected';
    })
    .catch(() => {
      $('#status').textContent = 'Disconnected';
      $('#status').className = 'status disconnected';
    });
}

setInterval(checkHealth, 5000);
checkHealth();
init();

async function loadLearning() {
    const [scoreRes, expRes, stratRes] = await Promise.all([
        fetch('/api/learning/score'),
        fetch('/api/learning/experiences?limit=50'),
        fetch('/api/learning/strategies'),
    ]);
    const score = await scoreRes.json();
    const exp = await expRes.json();
    const strat = await stratRes.json();

    document.getElementById('learning-score').textContent = Math.round(score.overall * 100) + '%';
    document.getElementById('score-success').textContent = Math.round(score.breakdown.task_success * 100) + '%';
    document.getElementById('score-tool').textContent = Math.round(score.breakdown.tool_efficiency * 100) + '%';
    document.getElementById('score-token').textContent = Math.round(score.breakdown.token_efficiency * 100) + '%';
    document.getElementById('score-learning').textContent = Math.round(score.breakdown.learning_score * 100) + '%';

    document.getElementById('exp-count').textContent = exp.total;
    document.getElementById('strat-count').textContent = strat.total;

    renderExpTags(exp.tags_distribution);
    renderExpList(exp.experiences);
    renderStratStatus(strat.status_distribution);
    renderStratList(strat.strategies);

    document.getElementById('reflect-info').textContent =
        'Last: ' + (score.last_reflection || 'never') + ' | Next: ' + (score.next_reflection_eta || '--');
}

function renderExpTags(dist) {
    const el = document.getElementById('exp-tags');
    el.innerHTML = Object.entries(dist).map(([tag, count]) =>
        `<span class="tag tag-${tag}">${tag}: ${count}</span>`
    ).join(' ');
}

function renderExpList(experiences) {
    const el = document.getElementById('exp-list');
    el.innerHTML = experiences.slice(0, 20).map(e =>
        `<div class="list-item">
            <span class="tag tag-${e.tag}">${e.tag}</span>
            <span class="task">${e.task_signature}</span>
            <span class="score">${Math.round(e.score * 100)}%</span>
        </div>`
    ).join('');
}

function renderStratStatus(dist) {
    const el = document.getElementById('strat-status');
    el.innerHTML = Object.entries(dist).map(([status, count]) =>
        `<span class="tag tag-${status}">${status}: ${count}</span>`
    ).join(' ');
}

function renderStratList(strategies) {
    const el = document.getElementById('strat-list');
    el.innerHTML = strategies.map(s =>
        `<div class="list-item">
            <span class="status">${s.status}</span>
            <span class="desc">${s.description}</span>
            <span class="rate">${Math.round(s.success_rate * 100)}% (${s.use_count})</span>
        </div>`
    ).join('');
}

async function triggerReflection() {
    await fetch('/api/learning/reflect', { method: 'POST' });
    loadLearning();
}