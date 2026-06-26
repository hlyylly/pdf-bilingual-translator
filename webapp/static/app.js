// ---- 简易前端：认证 + 上传 + 进度轮询 ----
const $ = (s) => document.querySelector(s);
let authMode = "login";
let pollTimer = null;

// 捕获邀请码（好友点邀请链接 /app?ref=CODE 进来）
(function captureRef() {
  const ref = new URLSearchParams(location.search).get("ref");
  if (ref) localStorage.setItem("ref", ref.toUpperCase());
})();

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
  if (authMode === "register" && localStorage.getItem("ref")) {
    fd.append("ref", localStorage.getItem("ref"));
  }
  const btn = $("#authSubmit");
  btn.disabled = true;
  $("#authMsg").className = "msg";
  $("#authMsg").textContent = "处理中…";
  try {
    await api(`/api/${authMode}`, { method: "POST", body: fd });
    if (authMode === "register") localStorage.removeItem("ref");
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

// 兑换码
$("#redeemBtn").addEventListener("click", doRedeem);
$("#redeemInput").addEventListener("keydown", (e) => { if (e.key === "Enter") doRedeem(); });

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

// 邀请有礼
$("#refBtn").addEventListener("click", openReferral);
$("#refClose").addEventListener("click", () => $("#refModal").classList.add("hidden"));
$("#refModal").addEventListener("click", (e) => { if (e.target.id === "refModal") $("#refModal").classList.add("hidden"); });

// ---------- 充值（微信扫码） ----------
let payPoll = null;

async function openPay(e) {
  if (e) e.preventDefault();
  $("#redeemMsg").textContent = "";
  $("#payQr").classList.add("hidden");
  $("#redeemBox").classList.remove("hidden");
  $("#packList").classList.remove("hidden");
  $("#payModal").classList.remove("hidden");
  const d = await api("/api/packs").catch(() => ({ packs: [], pay_enabled: false }));
  if (d.pay_enabled && d.packs.length) {
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
  } else {
    $("#packList").innerHTML = `<div class="empty">微信支付维护中，可使用下方兑换码充值。</div>`;
  }
}

async function doRedeem() {
  const code = $("#redeemInput").value.trim();
  const msg = $("#redeemMsg");
  if (!code) { msg.className = "msg err"; msg.textContent = "请输入兑换码"; return; }
  msg.className = "msg";
  msg.textContent = "兑换中…";
  const fd = new FormData();
  fd.append("code", code);
  try {
    const r = await api("/api/redeem", { method: "POST", body: fd });
    msg.className = "msg ok";
    msg.textContent = `✓ 兑换成功，到账 ${r.pages} 页！`;
    $("#redeemInput").value = "";
    renderUser(r);
  } catch (err) {
    msg.className = "msg err";
    msg.textContent = err.message;
  }
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
  $("#redeemBox").classList.add("hidden");
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

// ---------- 邀请有礼 ----------
async function openReferral() {
  $("#refModal").classList.remove("hidden");
  const body = $("#refBody");
  body.innerHTML = "加载中…";
  try {
    const d = await api("/api/referral");
    const link = `${location.origin}/app?ref=${d.code}`;
    body.innerHTML = `
      <p class="ref-rule">把你的专属链接发给好友，<b>好友注册并完成首次充值</b>，你立得 <b class="hl">${d.bonus} 页</b>，多邀多得，上不封顶。</p>
      <div class="ref-linkbox">
        <input id="refLink" type="text" readonly value="${link}" />
        <button id="refCopy" class="btn-copy">复制</button>
      </div>
      <div class="ref-stats">
        <div><b>${d.invited}</b><span>已邀请</span></div>
        <div><b>${d.rewarded}</b><span>已充值</span></div>
        <div><b>${d.earned}</b><span>累计得页</span></div>
      </div>
      <p class="ref-tip">小贴士：发到科研群、同学群、朋友圈，论文翻译刚需，转化率高。</p>`;
    $("#refCopy").addEventListener("click", () => {
      const inp = $("#refLink");
      inp.select();
      navigator.clipboard?.writeText(inp.value);
      $("#refCopy").textContent = "已复制";
      setTimeout(() => ($("#refCopy").textContent = "复制"), 1500);
    });
  } catch (err) {
    body.innerHTML = `<div class="empty">加载失败：${err.message}</div>`;
  }
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
const STATUS_TEXT = { queued: "排队中", running: "处理中", done: "已完成", failed: "失败" };

// 组合各阶段为单调递增的总进度：解析 5-45%，翻译 46-95%，渲染 96%
function pctOf(j) {
  if (j.status === "done" || j.status === "failed") return 100;
  if (j.status === "queued") return 3;
  const f = j.total ? Math.min(1, j.progress / j.total) : 0;
  if (j.phase === "ocr") return 5 + f * 40;
  if (j.phase === "translate") return 46 + f * 49;
  if (j.phase === "render") return 96;
  return 5;
}

function statusLine(j) {
  if (j.status === "failed") return j.message || "失败";
  if (j.status === "done") return `完成 · 共 ${j.pages} 页`;
  if (j.status === "queued") return "排队中，等待空闲…";
  if (j.phase === "ocr") return j.total ? `正在解析 PDF ${j.progress}/${j.total} 页` : "正在解析 PDF…";
  if (j.phase === "translate") return `正在翻译 ${j.progress}/${j.total} 页`;
  if (j.phase === "render") return "正在生成双语对照 PDF…";
  return "处理中…";
}

function elapsedText(j) {
  if (j.status !== "running" && j.status !== "queued") return "";
  const t = Date.parse(j.created_at);
  if (!t) return "";
  let s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  const m = Math.floor(s / 60);
  return ` · 用时 ${m}:${String(s % 60).padStart(2, "0")}`;
}

function jobCard(j) {
  const pct = pctOf(j);
  const failed = j.status === "failed";
  const active = j.status === "running" || j.status === "queued";
  const dl = j.status === "done" && j.has_output
    ? `<div class="job-actions"><a class="dl" href="/api/download/${j.id}">⬇ 下载双语 PDF</a></div>` : "";
  return `
    <div class="job">
      <div class="job-top">
        <span class="job-name">${escapeHtml(j.filename)}
          <small style="color:var(--sub)">· ${j.pages} 页 · 译为 ${escapeHtml(j.target_label || "")}</small></span>
        <span class="badge ${j.status}">${STATUS_TEXT[j.status] || j.status}</span>
      </div>
      <div class="bar ${active ? "live" : ""}"><i style="width:${pct}%"></i></div>
      <div class="job-msg ${failed ? "err" : ""}">${escapeHtml(statusLine(j))}${failed ? "" : escapeHtml(elapsedText(j))}</div>
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
  if (active && !pollTimer) pollTimer = setInterval(refreshJobs, 2000);
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
    // 受邀进来：显示提示并默认切到注册
    if (localStorage.getItem("ref")) {
      $("#refHint").classList.remove("hidden");
      document.querySelector('.tab[data-tab="register"]')?.click();
    }
  }
}
boot();
