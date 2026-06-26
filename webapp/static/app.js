// ---- 简易前端：认证 + 上传 + 进度轮询 ----
const $ = (s) => document.querySelector(s);
let authMode = "login";
let pollTimer = null;

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error((data && data.detail) || `请求失败 (${res.status})`);
  return data;
}

// ---------- 认证视图 ----------
document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    authMode = t.dataset.tab;
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
    $("#authSubmit").textContent = authMode === "login" ? "登录" : "注册";
    $("#authMsg").textContent = "";
  })
);

$("#authForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData();
  fd.append("username", $("#f-username").value.trim());
  fd.append("password", $("#f-password").value);
  const btn = $("#authSubmit");
  btn.disabled = true;
  $("#authMsg").className = "msg";
  $("#authMsg").textContent = "处理中…";
  try {
    await api(`/api/${authMode}`, { method: "POST", body: fd });
    await boot();
  } catch (err) {
    $("#authMsg").className = "msg err";
    $("#authMsg").textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

$("#logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" });
  location.reload();
});

// 充值弹窗按钮
$("#payClose").addEventListener("click", closePay);
$("#payBack").addEventListener("click", openPay);
$("#payModal").addEventListener("click", (e) => { if (e.target.id === "payModal") closePay(); });

// 充值记录
const ORDER_STATUS = { paid: "已支付", pending: "待支付", failed: "已关闭" };
$("#ordersBtn").addEventListener("click", async () => {
  const box = $("#ordersList");
  box.innerHTML = "加载中…";
  $("#ordersModal").classList.remove("hidden");
  try {
    const d = await api("/api/orders");
    if (!d.orders.length) {
      box.innerHTML = `<div class="empty">还没有充值记录。</div>`;
      return;
    }
    box.innerHTML = d.orders
      .map((o) => {
        const t = (o.paid_at || o.created_at || "").replace("T", " ").slice(0, 16);
        return `<div class="order-row">
          <div><b>${o.pages} 页</b> · ¥${o.price}</div>
          <div class="order-meta">${t} · <span class="os ${o.status}">${ORDER_STATUS[o.status] || o.status}</span></div>
        </div>`;
      })
      .join("");
  } catch (err) {
    box.innerHTML = `<div class="empty">加载失败：${err.message}</div>`;
  }
});
$("#ordersClose").addEventListener("click", () => $("#ordersModal").classList.add("hidden"));
$("#ordersModal").addEventListener("click", (e) => { if (e.target.id === "ordersModal") $("#ordersModal").classList.add("hidden"); });

// ---------- 充值（微信扫码） ----------
let payPoll = null;

async function openPay(e) {
  if (e) e.preventDefault();
  const d = await api("/api/packs");
  if (!d.pay_enabled) {
    alert("在线支付即将开放，敬请期待。");
    return;
  }
  $("#packList").innerHTML = d.packs
    .map(
      (p) => `<button class="pack" data-i="${p.index}">
        <div class="pack-pages">${p.pages} 页</div>
        <div class="pack-price">¥${p.price}</div>
      </button>`
    )
    .join("");
  $("#packList").querySelectorAll(".pack").forEach((b) =>
    b.addEventListener("click", () => startPay(b.dataset.i))
  );
  $("#packList").classList.remove("hidden");
  $("#payQr").classList.add("hidden");
  $("#payModal").classList.remove("hidden");
}

function closePay() {
  $("#payModal").classList.add("hidden");
  if (payPoll) { clearInterval(payPoll); payPoll = null; }
}

async function startPay(packIndex) {
  const fd = new FormData();
  fd.append("pack", packIndex);
  let r;
  try {
    r = await api("/api/pay/create", { method: "POST", body: fd });
  } catch (err) {
    alert(err.message);
    return;
  }
  $("#qrImg").src = r.qr;
  $("#payAmt").textContent = `¥${r.price}（${r.pages} 页）`;
  $("#payState").textContent = "等待支付…";
  $("#payState").className = "pay-state";
  $("#packList").classList.add("hidden");
  $("#payQr").classList.remove("hidden");
  // 轮询订单状态
  if (payPoll) clearInterval(payPoll);
  payPoll = setInterval(async () => {
    let s;
    try { s = await api(`/api/pay/status/${r.out_trade_no}`); } catch (_) { return; }
    if (s.status === "paid") {
      clearInterval(payPoll); payPoll = null;
      $("#payState").textContent = "✓ 支付成功，页数已到账！";
      $("#payState").className = "pay-state ok";
      renderUser(s);
      setTimeout(closePay, 1600);
    } else if (s.status === "failed") {
      clearInterval(payPoll); payPoll = null;
      $("#payState").textContent = "支付未完成，请重试";
      $("#payState").className = "pay-state err";
    }
  }, 2500);
}

// 落地页「立即购买」深链：/app?buy=N → 直接弹出该套餐支付码
async function maybeAutoBuy() {
  const buy = new URLSearchParams(location.search).get("buy");
  if (buy === null) return;
  history.replaceState(null, "", "/app");
  const d = await api("/api/packs").catch(() => null);
  if (!d || !d.pay_enabled) return;
  const n = Number(buy);
  if (!Number.isInteger(n) || n < 0 || n >= d.packs.length) return;
  $("#payModal").classList.remove("hidden");
  startPay(n);
}

// ---------- 用户/额度 ----------
function renderUser(u) {
  $("#username").textContent = u.username;
  $("#quota").innerHTML =
    `今日免费 <b>${u.free_remaining_today}</b>/${u.free_daily} 页` +
    ` · 页数包余额 <b>${u.credits}</b> 页` +
    ` <a class="buy" id="buyBtn" href="#">充值</a>`;
  const b = $("#buyBtn");
  if (b) b.addEventListener("click", openPay);
  if (u.max_upload_mb) $("#maxmb").textContent = u.max_upload_mb;
}

// ---------- 语言下拉 ----------
async function loadLanguages() {
  const sel = $("#langSelect");
  if (sel.options.length) return;
  try {
    const d = await api("/api/languages");
    sel.innerHTML = d.languages
      .map((l) => `<option value="${l.code}">${l.label}</option>`)
      .join("");
    sel.value = localStorage.getItem("target_lang") || d.default;
  } catch (_) {}
  sel.addEventListener("change", () => localStorage.setItem("target_lang", sel.value));
}

// ---------- 上传 ----------
const drop = $("#drop");
const fileInput = $("#fileInput");
drop.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => handleFiles(fileInput.files));
["dragenter", "dragover"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("drag"); })
);
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("drag"); })
);
drop.addEventListener("drop", (e) => handleFiles(e.dataTransfer.files));

async function handleFiles(files) {
  const pdfs = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) return;
  const msg = $("#uploadMsg");
  const targetLang = $("#langSelect").value || "zh-Hans";
  for (const f of pdfs) {
    msg.className = "msg";
    msg.textContent = `上传中：${f.name} …`;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("target_lang", targetLang);
    try {
      const r = await api("/api/upload", { method: "POST", body: fd });
      renderUser(r);
      msg.className = "msg ok";
      msg.textContent = `已提交：${f.name}（${r.pages} 页）`;
    } catch (err) {
      msg.className = "msg err";
      msg.textContent = `${f.name}：${err.message}`;
    }
  }
  fileInput.value = "";
  refreshJobs();
}

// ---------- 任务列表 ----------
const PHASE_TEXT = { ocr: "解析中", translate: "翻译中", render: "渲染中", done: "完成", failed: "失败" };
const STATUS_TEXT = { queued: "排队中", running: "处理中", done: "已完成", failed: "失败" };

function jobCard(j) {
  let pct = 0;
  if (j.status === "done") pct = 100;
  else if (j.phase === "translate" && j.total) pct = Math.round((j.progress / j.total) * 80) + 10;
  else if (j.phase === "ocr") pct = 6;
  else if (j.phase === "render") pct = 92;
  else if (j.status === "queued") pct = 2;

  const dl = j.status === "done" && j.has_output
    ? `<div class="job-actions"><a class="dl" href="/api/download/${j.id}">⬇ 下载双语 PDF</a></div>` : "";
  return `
    <div class="job">
      <div class="job-top">
        <span class="job-name">${escapeHtml(j.filename)}
          <small style="color:var(--sub)">· ${j.pages} 页 · 译为 ${escapeHtml(j.target_label || "")}</small></span>
        <span class="badge ${j.status}">${STATUS_TEXT[j.status] || j.status}</span>
      </div>
      <div class="bar"><i style="width:${pct}%"></i></div>
      <div class="job-msg">${escapeHtml(j.message || PHASE_TEXT[j.phase] || "")}</div>
      ${dl}
    </div>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function refreshJobs() {
  let data;
  try { data = await api("/api/jobs"); } catch (_) { return; }
  const box = $("#jobs");
  if (!data.jobs.length) {
    box.innerHTML = `<div class="empty">还没有任务，上传一个 PDF 试试。</div>`;
  } else {
    box.innerHTML = data.jobs.map(jobCard).join("");
  }
  const active = data.jobs.some((j) => j.status === "queued" || j.status === "running");
  if (active && !pollTimer) pollTimer = setInterval(refreshJobs, 2500);
  if (!active && pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  // 顺带刷新额度
  try { renderUser(await api("/api/me")); } catch (_) {}
}

// ---------- 启动 ----------
async function boot() {
  try {
    const u = await api("/api/me");
    renderUser(u);
    await loadLanguages();
    $("#authView").classList.add("hidden");
    $("#appView").classList.remove("hidden");
    $("#userbar").classList.remove("hidden");
    refreshJobs();
    maybeAutoBuy();
  } catch (_) {
    $("#authView").classList.remove("hidden");
    $("#appView").classList.add("hidden");
    $("#userbar").classList.add("hidden");
  }
}
boot();
