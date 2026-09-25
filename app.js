const initials = n => n.split(' ').map(p=>p[0]).join('').slice(0,2).toUpperCase();
const escapeHtml = str => { const d = document.createElement('div'); d.textContent = str; return d.innerHTML; };
const fmtTime = iso => {
  const d = new Date(iso + 'Z');
  return d.toLocaleTimeString([], { hour:'numeric', minute:'2-digit' });
};

let me = null;
let ws = null;
let conversations = [];
let activeConvoId = null;
let activeOtherId = null;
let onlineUsers = new Set();
let typingTimeout = null;

// ---------- Auth screen wiring ----------

document.querySelectorAll('.tab-btn').forEach(btn=>{
  btn.addEventListener('click', ()=>{
    document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    const tab = btn.dataset.tab;
    document.getElementById('login-form').classList.toggle('hidden', tab!=='login');
    document.getElementById('signup-form').classList.toggle('hidden', tab!=='signup');
  });
});

document.getElementById('login-form').addEventListener('submit', async e=>{
  e.preventDefault();
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  errEl.textContent = '';
  try {
    const res = await fetch('/api/login', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error; return; }
    startApp(data);
  } catch { errEl.textContent = 'Could not reach server'; }
});

document.getElementById('signup-form').addEventListener('submit', async e=>{
  e.preventDefault();
  const username = document.getElementById('signup-username').value.trim();
  const password = document.getElementById('signup-password').value;
  const errEl = document.getElementById('signup-error');
  errEl.textContent = '';
  try {
    const res = await fetch('/api/signup', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error; return; }
    startApp(data);
  } catch { errEl.textContent = 'Could not reach server'; }
});

document.getElementById('logout-btn').addEventListener('click', async ()=>{
  await fetch('/api/logout', { method:'POST' });
  location.reload();
});

// ---------- Bootstrap ----------

async function tryResume() {
  try {
    const res = await fetch('/api/me');
    if (res.ok) {
      const data = await res.json();
      startApp(data);
      return;
    }
  } catch {}
  document.getElementById('auth-screen').classList.remove('hidden');
}

function startApp(user) {
  me = user;
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  document.getElementById('me-username').textContent = '@' + me.username;
  connectSocket();
  loadConversations();
}

// ---------- WebSocket ----------

function connectSocket() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.addEventListener('message', ev=>{
    const data = JSON.parse(ev.data);
    if (data.type === 'message') handleIncomingMessage(data.message);
    if (data.type === 'presence') handlePresence(data.userId, data.online);
    if (data.type === 'typing') handleTypingEvent(data);
  });

  ws.addEventListener('close', ()=>{
    setTimeout(connectSocket, 1500);
  });
}

function handleIncomingMessage(msg) {
  const belongsToActive = msg.conversation_id === activeConvoId;
  if (belongsToActive) {
    appendBubble(msg);
    scrollToBottom();
  }
  loadConversations(belongsToActive ? null : msg.conversation_id);
}

function handlePresence(userId, online) {
  if (online) onlineUsers.add(userId); else onlineUsers.delete(userId);
  renderConversations();
  if (activeOtherId === userId) updateChatHeadStatus();
}

function handleTypingEvent(data) {
  if (data.conversationId !== activeConvoId) return;
  const el = document.getElementById('typing-indicator');
  el.textContent = 'typing…';
  el.classList.remove('hidden');
  clearTimeout(typingTimeout);
  typingTimeout = setTimeout(()=> el.classList.add('hidden'), 2000);
}

// ---------- Conversations list ----------

async function loadConversations(flashUnreadId) {
  const res = await fetch('/api/conversations');
  conversations = await res.json();
  renderConversations();
}

function renderConversations() {
  const el = document.getElementById('contacts');
  el.innerHTML = '';
  conversations.forEach(c=>{
    const div = document.createElement('div');
    div.className = 'contact' + (c.conversation_id === activeConvoId ? ' active' : '');
    const online = onlineUsers.has(c.other_id);
    div.innerHTML = `
      <div class="avatar">${initials(c.other_username)}<span class="presence ${online?'online':''}"></span></div>
      <div class="contact-meta">
        <div class="contact-name">${escapeHtml(c.other_username)}</div>
        <div class="contact-preview">${c.last_text ? escapeHtml(c.last_text) : 'Say hello'}</div>
      </div>
      ${c.unread > 0 ? `<div class="unread-badge">${c.unread}</div>` : `<div class="contact-time">${c.last_at ? fmtTime(c.last_at) : ''}</div>`}
    `;
    div.addEventListener('click', ()=> openConversation(c.conversation_id, c.other_id, c.other_username));
    el.appendChild(div);
  });
}

// ---------- User search / start new chat ----------

const searchInput = document.getElementById('user-search');
let searchDebounce = null;
searchInput.addEventListener('input', ()=>{
  clearTimeout(searchDebounce);
  const q = searchInput.value.trim();
  const resultsEl = document.getElementById('user-results');
  if (!q) { resultsEl.innerHTML = ''; return; }
  searchDebounce = setTimeout(async ()=>{
    const res = await fetch('/api/users?q=' + encodeURIComponent(q));
    const users = await res.json();
    resultsEl.innerHTML = '';
    users.forEach(u=>{
      const div = document.createElement('div');
      div.className = 'user-result';
      div.innerHTML = `<div class="avatar" style="width:26px;height:26px;font-size:11px;">${initials(u.username)}</div>@${escapeHtml(u.username)}`;
      div.addEventListener('click', async ()=>{
        const startRes = await fetch('/api/conversations/start', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ otherUserId: u.id })
        });
        const startData = await startRes.json();
        searchInput.value = '';
        resultsEl.innerHTML = '';
        await loadConversations();
        openConversation(startData.conversationId, startData.otherId, startData.otherUsername);
      });
      resultsEl.appendChild(div);
    });
  }, 250);
});

document.addEventListener('click', e=>{
  if (!document.getElementById('new-chat-box').contains(e.target)) {
    document.getElementById('user-results').innerHTML = '';
  }
});

// ---------- Active conversation ----------

async function openConversation(conversationId, otherId, otherUsername) {
  activeConvoId = conversationId;
  activeOtherId = otherId;

  document.getElementById('empty-state').classList.add('hidden');
  document.getElementById('chat-active').classList.remove('hidden');
  document.getElementById('chat-head-name').textContent = '@' + otherUsername;
  document.getElementById('chat-head-avatar').textContent = initials(otherUsername);
  document.getElementById('typing-indicator').classList.add('hidden');
  updateChatHeadStatus();

  renderConversations();

  const res = await fetch(`/api/conversations/${conversationId}/messages`);
  const msgs = await res.json();
  const container = document.getElementById('messages');
  container.innerHTML = '';
  msgs.forEach(appendBubble);
  scrollToBottom();
  loadConversations();
}

function updateChatHeadStatus() {
  const online = onlineUsers.has(activeOtherId);
  document.getElementById('chat-head-status').textContent = online ? 'online' : 'offline';
}

function appendBubble(msg) {
  const row = document.createElement('div');
  row.className = 'msg-row ' + (msg.sender_id === me.id ? 'me' : 'them');
  row.innerHTML = `
    <div>
      <div class="bubble">${escapeHtml(msg.text)}</div>
      <div class="msg-time">${fmtTime(msg.created_at)}</div>
    </div>
  `;
  document.getElementById('messages').appendChild(row);
}

function scrollToBottom() {
  const el = document.getElementById('messages');
  el.scrollTop = el.scrollHeight;
}

// ---------- Composer ----------

const input = document.getElementById('msg-input');
const sendBtn = document.getElementById('send-btn');

function send() {
  const text = input.value.trim();
  if (!text || !activeConvoId || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type:'message', conversationId: activeConvoId, text }));
  input.value = '';
  input.style.height = 'auto';
}

sendBtn.addEventListener('click', send);
input.addEventListener('keydown', e=>{
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
input.addEventListener('input', ()=>{
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  if (activeConvoId && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type:'typing', conversationId: activeConvoId }));
  }
});

tryResume();
