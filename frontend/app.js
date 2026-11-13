/* Commerce Copilot 前端：SSE 渲染、卡片、引用、确认弹窗、接管状态 */
const state = {
  token: null,
  userId: "u0001",
  role: "consumer",
  threadId: null,
  pendingAction: null,
  streaming: false,
};

const $ = (id) => document.getElementById(id);
const messagesEl = $("messages");

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* 轻量 markdown：加粗、列表、换行 */
function md(text) {
  let t = esc(text);
  t = t.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  const lines = t.split("\n");
  let html = "", inList = false;
  for (const line of lines) {
    const li = line.match(/^\s*[-•]\s+(.*)$/);
    if (li) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${li[1]}</li>`;
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      if (line.trim()) html += `<p>${line}</p>`;
    }
  }
  if (inList) html += "</ul>";
  return html || "<p></p>";
}

function addMsg(role, text) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role === "user" ? "user" : "bot"}`;
  wrap.innerHTML = `
    <div class="avatar">${role === "user" ? "我" : "AI"}</div>
    <div class="bubble"><div class="body"></div><div class="extra"></div></div>`;
  wrap.querySelector(".body").innerHTML = md(text);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return wrap;
}

function statusLine(wrap, label) {
  let el = wrap.querySelector(".statusline");
  if (!el) {
    el = document.createElement("div");
    el.className = "statusline";
    wrap.querySelector(".bubble").prepend(el);
  }
  el.innerHTML = `<span class="spinner"></span><span class="txt">${esc(label)}</span>`;
}

function renderCards(wrap, cards) {
  if (!cards || !cards.length) return;
  const box = wrap.querySelector(".extra");
  const grid = document.createElement("div");
  grid.className = "cards";
  grid.innerHTML = cards.map((c) => `
    <div class="card">
      <h4>${esc(c.title)}</h4>
      <div class="price">¥${Number(c.price).toFixed(0)}</div>
      <div class="meta">库存 ${c.available_qty} · 评分 ${c.rating} · 30天销 ${c.sales_30d}</div>
      <div class="meta">${esc((c.review || "").slice(0, 42))}…</div>
      <div class="tags">${(c.explain || []).map((e) => `<span class="tag">${esc(e)}</span>`).join("")}</div>
    </div>`).join("");
  box.appendChild(grid);
}

function renderOrder(wrap, order) {
  if (!order) return;
  const box = wrap.querySelector(".extra");
  const st = { PAID: "待发货", SHIPPED: "运输中", SIGNED: "已签收", COMPLETED: "已完成", CANCELLED: "已取消" };
  const el = document.createElement("div");
  el.className = "orderCard";
  el.innerHTML = `
    <div class="rowline"><b>${esc(order.order_no)}</b><span>${st[order.status] || order.status}</span></div>
    <div class="rowline"><span>实付</span><b>¥${Number(order.paid_amount).toFixed(2)}</b></div>
    <div class="rowline"><span>签收</span><b>${esc(order.signed_at || "-")}</b></div>
    <div class="rowline"><span>商品</span><b>${esc((order.items || []).map((i) => i.title).join("、")).slice(0, 40)}</b></div>`;
  box.appendChild(el);
}

function renderCitations(wrap, citations) {
  if (!citations || !citations.length) return;
  const box = wrap.querySelector(".extra");
  const bar = document.createElement("div");
  bar.className = "tools";
  const btn = document.createElement("button");
  btn.className = "linkBtn";
  btn.textContent = `查看引用（${citations.length} 条）`;
  btn.onclick = () => openDrawer(citations);
  bar.appendChild(btn);
  box.appendChild(bar);
}

function renderHandoff(wrap, handoff) {
  if (!handoff || handoff.ticket_id === "-") return;
  const box = wrap.querySelector(".extra");
  const el = document.createElement("div");
  el.className = "handoffBanner";
  el.innerHTML = `已转人工 · 工单 <b>${esc(handoff.ticket_id)}</b> · 状态 ${esc(handoff.status)}（客服可看到本次槽位与工具结果）`;
  box.appendChild(el);
}

function renderConfirm(wrap, action) {
  if (!action) return;
  state.pendingAction = action;
  const box = wrap.querySelector(".extra");
  const el = document.createElement("div");
  el.className = "confirmBanner";
  el.innerHTML = `<span>待确认：退款 ¥${Number(action.amount).toFixed(2)} · 风险 ${esc(action.risk_level)}</span>`;
  const btn = document.createElement("button");
  btn.className = "btn primary";
  btn.textContent = "去确认";
  btn.onclick = () => openModal(action, btn);
  el.appendChild(btn);
  box.appendChild(el);
}

function openDrawer(citations) {
  $("drawerBody").innerHTML = citations.map((c) => `
    <div class="cite">
      <div class="h"><span>${esc(c.doc_id)} · ${esc(c.authority)}</span><span>${esc(c.version)}</span></div>
      <h4>${esc(c.title)}｜${esc(c.section)}</h4>
      <p>${esc(c.excerpt)}</p>
      <div class="h"><span>生效 ${esc(c.effective_at)}</span><span>score ${Number(c.score).toFixed(4)}</span></div>
    </div>`).join("");
  $("drawer").classList.remove("hidden");
}

function openModal(action, triggerBtn) {
  state.modalTrigger = triggerBtn;
  $("modalBody").innerHTML = `
    <div class="kv"><span>订单号</span><b>${esc(action.order_no)}</b></div>
    <div class="kv"><span>拟退款</span><b>¥${Number(action.amount).toFixed(2)}</b></div>
    <div class="kv"><span>规则版本</span><b>${esc(action.rule_version)}</b></div>
    <div class="kv"><span>风险等级</span><b>${esc(action.risk_level)}</b></div>
    <p style="color:#66748a;font-size:12.5px;margin-top:10px">
      金额由规则引擎计算，提交后不可撤回修改；重复点击不会重复提交（幂等键）。
    </p>`;
  $("modal").classList.remove("hidden");
}

async function submitConfirm() {
  const a = state.pendingAction;
  if (!a) return;
  const key = `idem-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  const btn = $("modalOk");
  btn.disabled = true;
  btn.textContent = "提交中…";
  try {
    const res = await fetch("/api/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}` },
      body: JSON.stringify({
        draft_id: a.draft_id,
        idempotency_key: key,
        user_confirmed: true,
        expected_order_version: a.expected_order_version || null,
      }),
    });
    const data = await res.json();
    const wrap = addMsg("bot", "");
    const body = wrap.querySelector(".body");
    if (data.ok) {
      const r = data.result;
      const st = r.status === "CONFLICT" ? "⚠️ 冲突" : "✅ 已提交";
      body.innerHTML = md(
        `**${st}**\n- 申请号：${r.application_id || "-"}\n- 状态：${r.status}${r.idempotent ? "（幂等命中，未重复提交）" : ""}\n- 说明：${r.reason || "已进入审核流程"}`
      );
    } else {
      body.innerHTML = md(`提交失败：${data.message || data.code}`);
    }
  } catch (e) {
    addMsg("bot", `提交异常：${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "确认提交";
    $("modal").classList.add("hidden");
  }
}

/* ---------- SSE ---------- */
function parseSSEBlock(block) {
  let event = "message", data = "";
  block.split("\n").forEach((line) => {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  });
  return { event, data };
}

async function send(text) {
  if (!text.trim() || state.streaming) return;
  state.streaming = true;
  $("send").disabled = true;
  addMsg("user", text);
  $("input").value = "";
  autoGrow();
  const wrap = addMsg("bot", "");
  const body = wrap.querySelector(".body");
  statusLine(wrap, "正在理解你的需求…");
  let buffer = "";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}` },
      body: JSON.stringify({ message: text, thread_id: state.threadId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "请求失败");
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let raw = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      raw += decoder.decode(value, { stream: true });
      const blocks = raw.split("\n\n");
      raw = blocks.pop();
      for (const b of blocks) {
        const { event, data } = parseSSEBlock(b);
        if (!data) continue;
        const obj = JSON.parse(data);
        if (event === "status") {
          statusLine(wrap, obj.label || obj.stage);
          if (obj.thread_id && !state.threadId) {
            state.threadId = obj.thread_id;
            $("threadLabel").textContent = obj.thread_id;
          }
          appendTrace(obj);
        } else if (event === "token") {
          const st = wrap.querySelector(".statusline");
          if (st) st.remove();
          buffer += obj.text;
          body.innerHTML = md(buffer);
          messagesEl.scrollTop = messagesEl.scrollHeight;
        } else if (event === "result") {
          renderCards(wrap, obj.cards);
          renderOrder(wrap, obj.order);
          renderCitations(wrap, obj.citations);
          renderHandoff(wrap, obj.handoff);
          renderConfirm(wrap, obj.pending_action);
          $("traceFoot").textContent = `trace: ${obj.trace_id} · intent: ${obj.intent}`;
          if (obj.thread_id) {
            state.threadId = obj.thread_id;
            $("threadLabel").textContent = obj.thread_id;
          }
        } else if (event === "done") {
          $("latencyFoot").textContent = `总耗时 ${obj.total_ms} ms · 首块 ${obj.ttft_ms} ms · tokens ${obj.tokens_in}/${obj.tokens_out}`;
          refreshMetrics();
        } else if (event === "error") {
          body.innerHTML = md(`❌ ${obj.message}`);
        }
      }
    }
  } catch (e) {
    const st = wrap.querySelector(".statusline");
    if (st) st.remove();
    body.innerHTML = md(`❌ ${e.message}`);
  } finally {
    state.streaming = false;
    $("send").disabled = false;
  }
}

function appendTrace(ev) {
  if ($("traceBar").classList.contains("hidden")) return;
  const el = document.createElement("span");
  el.className = "step";
  el.innerHTML = `<b>${esc(ev.stage || "")}</b> ${esc(ev.label || "")}`;
  $("traceBar").appendChild(el);
}

async function refreshMetrics() {
  try {
    const m = await (await fetch("/api/metrics")).json();
    $("p95State").textContent = `${m.p95_ms} ms`;
    $("reqState").textContent = `${m.requests} / err ${m.errors}`;
  } catch (_) {}
}

async function loadHealth() {
  try {
    const h = await (await fetch("/api/health")).json();
    $("llmState").textContent = h.llm.llm_enabled ? h.llm.model : "规则降级";
    $("embState").textContent = h.embedding_mode;
    $("idxState").textContent = h.product_index.ready ? `${h.product_index.rows} 条` : "未就绪";
  } catch (_) {}
}

async function login() {
  state.role = $("roleSelect").value;
  state.userId = $("userInput").value.trim() || "u0001";
  const res = await fetch(`/api/token?user_id=${encodeURIComponent(state.userId)}&role=${state.role}`);
  const data = await res.json();
  state.token = data.token;
  $("identityHint").textContent = `已登录：${data.user_id}（${state.role}）`;
  addMsg("bot", `已切换为 **${state.userId}**（${state.role}）。可以问我商品、订单、售后或政策问题。`);
}

/* ---------- 交互 ---------- */
function autoGrow() {
  const t = $("input");
  t.style.height = "auto";
  t.style.height = Math.min(120, t.scrollHeight) + "px";
}

$("input").addEventListener("input", autoGrow);
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send($("input").value);
  }
});
$("send").onclick = () => send($("input").value);
$("loginBtn").onclick = login;
$("newThread").onclick = () => {
  state.threadId = null;
  $("threadLabel").textContent = "新会话";
  messagesEl.innerHTML = "";
  addMsg("bot", "新会话已开始。你可以直接描述需求，例如「2000 以内通勤降噪耳机，戴眼镜不夹头」。");
};
$("toggleTrace").onclick = () => $("traceBar").classList.toggle("hidden");
$("closeDrawer").onclick = () => $("drawer").classList.add("hidden");
$("modalCancel").onclick = () => $("modal").classList.add("hidden");
$("modalOk").onclick = submitConfirm;

document.querySelectorAll(".chip").forEach((c) => {
  c.onclick = () => send(c.dataset.q);
});

(async function init() {
  await login();
  await loadHealth();
  await refreshMetrics();
  setInterval(loadHealth, 20000);
})();
