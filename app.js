// Misrtal Pro — Claude Code style frontend

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

let sessionId = null;
let running = false;
let attachments = [];
let changes = [];

const messagesEl = $('#messages');
const inputEl = $('#input');
const sendBtn = $('#sendBtn');
const thinkingStream = $('#thinkingStream');
const fileTree = $('#fileTree');
const changesList = $('#changesList');
const statusPill = $('#statusPill');
const planModal = $('#planModal');
const planBody = $('#planBody');
const chatTitle = $('#chatTitle');

function setStatus(s) {
  statusPill.textContent = s;
  statusPill.className = 'status-pill ' + (s === 'idle' ? '' : s);
}
function now() {
  return new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function scroll() { messagesEl.scrollTop = messagesEl.scrollHeight; }

function addThinking(text, kind='') {
  const empty = thinkingStream.querySelector('.empty-state');
  if (empty) empty.remove();
  const el = document.createElement('div');
  el.className = `thinking-item ${kind}`;
  el.innerHTML = `<div class="t-time">${now()}</div><div class="t-text">${esc(text)}</div>`;
  thinkingStream.appendChild(el);
  thinkingStream.scrollTop = thinkingStream.scrollHeight;
}

function addMsg(role, text) {
  const w = messagesEl.querySelector('.welcome');
  if (w) w.remove();
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.innerHTML = `<div class="role">${role==='user'?'Ты':'Misrtal'}</div>
    <div class="bubble"><div class="content-text">${esc(text)}</div></div>`;
  messagesEl.appendChild(div);
  scroll();
}

function addStep(kind, title, body='', stats=null) {
  const icons = { thinking:'💭', tool:'🔧', file:'📄', error:'⚠️' };
  const st = stats ? `<div class="diff-stats"><span class="add">+${stats.add||0}</span><span class="del">−${stats.del||0}</span></div>` : '';
  const div = document.createElement('div');
  div.className = `agent-step ${kind}`;
  div.innerHTML = `<div class="step-header"><span class="step-icon">${icons[kind]||'•'}</span><span>${esc(title)}</span></div>
    ${body?`<div class="step-body">${esc(body)}</div>`:''}${st}`;
  messagesEl.appendChild(div);
  scroll();
}

function addChange(c) {
  changes.unshift(c);
  changesList.innerHTML = changes.map(x => `
    <div class="change-card">
      <div class="change-header">
        <span class="filename">${esc(x.path)}</span>
        <div class="stats"><span class="a">+${x.add||0}</span><span class="d">−${x.del||0}</span></div>
      </div>
      <div class="diff-preview"><pre style="margin:0;white-space:pre-wrap;font-size:12px;font-family:var(--mono)">${esc((x.preview||'').slice(0,1500))}</pre>
        ${x.cloud_url?`<div style="padding:8px 0 0;font-size:12px"><a href="${esc(x.cloud_url)}" target="_blank" style="color:#06b6d4">☁ Cloudinary</a></div>`:''}
      </div>
    </div>`).join('');
  document.querySelector('[data-tab="changes"]').click();
}

async function refreshFiles() {
  try {
    const r = await fetch('/api/files');
    const d = await r.json();
    if (!d.files.length) {
      fileTree.innerHTML = '<div class="empty-state">Нет файлов. Агент создаст или прикрепи свои.</div>';
      return;
    }
    fileTree.innerHTML = d.files.map(f => `
      <div class="file-item" data-path="${esc(f.path)}">
        <span class="icon">📄</span>
        <span class="name">${esc(f.path)}</span>
        <span class="badge">${(f.size/1024).toFixed(1)}kb</span>
      </div>`).join('');
    $$('.file-item').forEach(el => {
      el.onclick = async () => {
        const r = await fetch('/api/file?path='+encodeURIComponent(el.dataset.path));
        const d = await r.json();
        const pre = document.createElement('div');
        pre.className = 'agent-step file';
        pre.innerHTML = `<div class="step-header"><span class="step-icon">📄</span><span>${esc(d.path)}</span></div>
          <div class="step-body">${esc((d.content||'').slice(0,4000))}</div>`;
        messagesEl.appendChild(pre);
        scroll();
      };
    });
  } catch(e) { console.error(e); }
}

function showPlan(plan, summary) {
  planBody.innerHTML = (summary?`<p style="color:var(--text-muted);margin-bottom:12px">${esc(summary)}</p>`:'') +
    plan.map((s,i) => `<div class="plan-step"><div class="plan-num">${i+1}</div><div class="plan-text">${esc(s)}</div></div>`).join('');
  planModal.classList.add('open');
}
function hidePlan() { planModal.classList.remove('open'); }

async function send() {
  const text = inputEl.value.trim();
  if (!text || running) return;
  running = true;
  sendBtn.disabled = true;
  inputEl.value = '';
  inputEl.style.height = 'auto';
  addMsg('user', text);
  setStatus('thinking');
  addThinking('Отправляю задачу…');
  if (text.length > 20) chatTitle.textContent = text.slice(0,40)+(text.length>40?'…':'');

  try {
    if (attachments.length) {
      const fd = new FormData();
      attachments.forEach(a => fd.append('files', a.file));
      await fetch('/api/upload', { method:'POST', body: fd });
      addThinking('Загружено: '+attachments.map(a=>a.name).join(', '));
      attachments = [];
      renderAtt();
    }
    const r = await fetch('/api/start', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ message: text, session_id: sessionId })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || 'start failed');
    sessionId = data.session_id;
    if (data.demo) addThinking('⚠️ Нет API-ключа — демо-план', 'tool');
    setStatus('planning');
    showPlan(data.plan, data.summary);
  } catch(e) {
    addMsg('assistant', 'Ошибка: '+e.message);
    setStatus('idle');
    running = false;
    sendBtn.disabled = false;
  }
}

async function acceptPlan() {
  hidePlan();
  if (!sessionId) return;
  setStatus('running');
  addMsg('assistant', 'План принят. Агент работает…');
  addThinking('Выполняю план…', 'tool');
  try {
    const r = await fetch('/api/run', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ session_id: sessionId })
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'run failed');
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream:true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        if (!part.trim()) continue;
        let ev='message', data='';
        for (const line of part.split('\n')) {
          if (line.startsWith('event:')) ev = line.slice(6).trim();
          if (line.startsWith('data:')) data = line.slice(5).trim();
        }
        let p; try { p = JSON.parse(data); } catch { p = { text: data }; }
        handle(ev, p);
      }
    }
  } catch(e) {
    addMsg('assistant', 'Ошибка: '+e.message);
    addThinking('Ошибка: '+e.message);
  }
  setStatus('done');
  await refreshFiles();
  setTimeout(()=>setStatus('idle'), 2000);
  running = false;
  sendBtn.disabled = false;
}

function handle(ev, d) {
  switch(ev) {
    case 'thinking': addThinking(d.text||''); break;
    case 'message': if (d.text) addMsg('assistant', d.text); break;
    case 'tool_call':
      addStep('tool', d.name, JSON.stringify(d.args, null, 2));
      addThinking(`🔧 ${d.name}`, 'tool');
      break;
    case 'tool_result':
      addStep('tool', `← ${d.name}`, (d.result||'').slice(0,800));
      break;
    case 'file_change':
      addStep('file', d.path, `action: ${d.action}`, { add:d.add, del:d.del });
      addChange(d);
      addThinking(`📄 ${d.path}`, 'file');
      break;
    case 'done':
      addMsg('assistant', d.text || 'Готово.');
      addThinking('Агент завершил.');
      break;
    case 'error':
      addMsg('assistant', 'Ошибка: '+(d.text||''));
      break;
    case 'status':
      setStatus(d.status||'running');
      break;
  }
}

function rejectPlan() {
  hidePlan();
  addMsg('assistant', 'План отклонён. Уточни задачу.');
  setStatus('idle');
  running = false;
  sendBtn.disabled = false;
}

function renderAtt() {
  $('#attachments').innerHTML = attachments.map((a,i)=>`
    <div class="attachment-chip">📎 ${esc(a.name)}
      <span class="remove" data-i="${i}">×</span></div>`).join('');
  $$('.attachment-chip .remove').forEach(el => {
    el.onclick = () => { attachments.splice(+el.dataset.i,1); renderAtt(); };
  });
}

inputEl.addEventListener('input', () => {
  sendBtn.disabled = !inputEl.value.trim() || running;
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160)+'px';
});
inputEl.addEventListener('keydown', e => {
  if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
sendBtn.onclick = send;
$('#attachBtn').onclick = () => $('#fileInput').click();
$('#fileInput').onchange = () => {
  for (const f of $('#fileInput').files) attachments.push({ name:f.name, file:f });
  $('#fileInput').value='';
  renderAtt();
};
$('#acceptPlan').onclick = acceptPlan;
$('#rejectPlan').onclick = rejectPlan;
$('#newChatBtn').onclick = () => location.reload();
$('#toggleFilesBtn')?.addEventListener('onclick', ()=>{});
$$('.side-tab').forEach(tab => {
  tab.onclick = () => {
    $$('.side-tab').forEach(t=>t.classList.remove('active'));
    $$('.tab-pane').forEach(p=>p.classList.remove('active'));
    tab.classList.add('active');
    $(`#tab-${tab.dataset.tab}`).classList.add('active');
  };
});
$$('.hint').forEach(btn => {
  btn.onclick = () => {
    inputEl.value = btn.dataset.prompt;
    inputEl.dispatchEvent(new Event('input'));
    inputEl.focus();
  };
});

(async () => {
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    const el = $('#keyText') || document.querySelector('.model-badge');
    if (el) {
      const text = el.querySelector('#keyText') || el;
      if (s.has_key) {
        if ($('#keyText')) $('#keyText').textContent = `Codestral · ${s.model}`;
        document.querySelector('.model-badge .dot').style.background = '#22c55e';
      } else {
        if ($('#keyText')) $('#keyText').textContent = 'NO API KEY';
        document.querySelector('.model-badge .dot').style.background = '#ef4444';
      }
    }
    const hint = $('#keyHint');
    if (hint && !s.has_key) {
      hint.innerHTML = '⚠️ Добавь <code>MISTRAL_API_KEY</code> в Secrets / .env';
    }
  } catch {}
  refreshFiles();
  setStatus('idle');
})();
