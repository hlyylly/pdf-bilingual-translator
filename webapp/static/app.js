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

// ---------- 用户/额度 ----------
function renderUser(u) {
  $("#username").textContent = u.username;
  $("#quota").textContent = `今日额度 ${u.used_today} / ${u.quota} 页`;
  if (u.max_upload_mb) $("#maxmb").textContent = u.max_upload_mb;
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
  for (const f of pdfs) {
    msg.className = "msg";
    msg.textContent = `上传中：${f.name} …`;
    const fd = new FormData();
    fd.append("file", f);
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
        <span class="job-name">${escapeHtml(j.filename)} <small style="color:var(--sub)">· ${j.pages} 页</small></span>
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
    $("#authView").classList.add("hidden");
    $("#appView").classList.remove("hidden");
    $("#userbar").classList.remove("hidden");
    refreshJobs();
  } catch (_) {
    $("#authView").classList.remove("hidden");
    $("#appView").classList.add("hidden");
    $("#userbar").classList.add("hidden");
  }
}
boot();
