let sessionId = "";
let sessions = [];
let sending = false;

function genId() {
  return "s_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
}

function newSession() {
  sessionId = genId();
  sessions.unshift({ id: sessionId, title: "新对话" });
  renderSessions();
  clearMessages();
  document.getElementById("chat-input").focus();
}

function renderSessions() {
  const list = document.getElementById("session-list");
  list.innerHTML = "";
  for (const s of sessions) {
    const active = s.id === sessionId ? "active" : "";
    list.innerHTML += `<div class="session-item ${active}" onclick="switchSession('${s.id}')">${s.title}</div>`;
  }
}

function switchSession(id) {
  sessionId = id;
  renderSessions();
  clearMessages();
}

function clearMessages() {
  const box = document.getElementById("chat-messages");
  box.innerHTML = `<div class="empty-state" id="empty-state">
    <div class="icon">💬</div><p>开始一个新的对话</p>
    <p style="font-size:12px">输入任务，多智能体团队将协作完成</p></div>`;
}

function addMessage(role, content) {
  const box = document.getElementById("chat-messages");
  const empty = document.getElementById("empty-state");
  if (empty) empty.remove();

  const div = document.createElement("div");
  div.className = "msg msg-" + role;
  div.innerHTML = simpleMarkdown(content);
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function addStatus(text) {
  const box = document.getElementById("chat-messages");
  const empty = document.getElementById("empty-state");
  if (empty) empty.remove();

  const div = document.createElement("div");
  div.className = "msg msg-system";
  div.id = "status-msg";
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function updateStatus(text) {
  const el = document.getElementById("status-msg");
  if (el) el.textContent = text;
}

function removeStatus() {
  const el = document.getElementById("status-msg");
  if (el) el.remove();
}

function simpleMarkdown(text) {
  return text
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.*?)\*/g, "<em>$1</em>")
    .replace(/`(.*?)`/g, "<code>$1</code>")
    .replace(/---/g, "<hr style=\'border:none;border-top:1px solid var(--border);margin:8px 0\'>")
    .replace(/\n/g, "<br>");
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}

function handleKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

async function sendMessage() {
  if (sending) return;
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;

  if (!sessionId) newSession();

  input.value = "";
  input.style.height = "auto";
  sending = true;
  updateSendBtn(true);

  addMessage("user", text);
  addStatus("⚡ 正在思考中，请稍候...");

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 120000);

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId, max_iterations: 2 }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    const data = await res.json();
    removeStatus();

    if (data.error) {
      addMessage("assistant", "❌ " + data.reply);
    } else {
      sessionId = data.session_id;
      const session = sessions.find((s) => s.id === sessionId);
      if (session && text.length > 0) {
        session.title = text.slice(0, 30) + (text.length > 30 ? "..." : "");
      }
      renderSessions();
      addMessage("assistant", data.reply || "（无回复）");
    }
  } catch (err) {
    removeStatus();
    if (err.name === "AbortError") {
      addMessage("assistant", "❌ 请求超时（120秒），请稍后重试或减少迭代次数。");
    } else {
      addMessage("assistant", "❌ 请求失败: " + err.message);
    }
  } finally {
    sending = false;
    updateSendBtn(false);
  }
}

function updateSendBtn(disabled) {
  document.getElementById("send-btn").disabled = disabled;
}

async function clearChat() {
  if (!sessionId) return;
  await fetch("/api/chat/clear/" + sessionId, { method: "POST" });
  sessions = sessions.filter((s) => s.id !== sessionId);
  sessionId = "";
  renderSessions();
  clearMessages();
  toast("对话已清空", "success");
}

function toast(msg, type) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast toast-" + (type || "success");
  el.style.display = "block";
  setTimeout(function() { el.style.display = "none"; }, 2500);
}

renderSessions();
