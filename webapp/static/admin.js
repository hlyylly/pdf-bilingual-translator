const $ = (s) => document.querySelector(s);

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 401) throw { code: 401 };
  if (r.status === 403) throw { code: 403 };
  if (!r.ok) {
    let detail = r.status;
    try { detail = (await r.json()).detail || detail; } catch (_) {}
    throw { code: r.status, message: detail };
  }
  return r.json();
}

const fmtTime = (t) => (t ? String(t).replace("T", " ").slice(5, 16) : "—");

const STATUS = { paid: "已支付", pending: "待支付", failed: "已关闭" };

function card(v, label, extra) {
  const ex = extra ? ` <small>${extra}</small>` : "";
  return `<div class="stat ${label.includes("收入") ? "rev" : ""}">
    <div class="v">${v}${ex}</div><div class="l">${label}</div></div>`;
}

async function load() {
  try {
    const s = await api("/api/admin/stats");
    const r = await api("/api/admin/recent");
    $("#gate").classList.add("hidden");
    $("#dash").classList.remove("hidden");

    $("#cards").innerHTML = [
      card(s.users_total, "用户总数", s.users_today ? `+${s.users_today} 今日` : ""),
      card("¥" + s.revenue_total, "累计收入", s.revenue_today ? `¥${s.revenue_today} 今日` : ""),
      card(s.orders_paid, "已支付订单"),
      card(s.pages_translated, "已翻译页数"),
      card(s.jobs_total, "翻译任务", s.jobs_today ? `+${s.jobs_today} 今日` : ""),
      card(s.invited, "邀请注册"),
      card(s.referral_converted, "邀请转化", s.referral_pages_given ? `送出 ${s.referral_pages_given} 页` : ""),
      card(s.credits_outstanding, "待消耗页数余额"),
    ].join("");

    $("#orders").innerHTML = r.orders.length
      ? r.orders.map((o) => `<tr><td>${o.username}</td><td>${o.pages} 页</td>
          <td>¥${o.price}</td><td><span class="tag ${o.status}">${STATUS[o.status] || o.status}</span></td>
          <td>${fmtTime(o.time)}</td></tr>`).join("")
      : `<tr><td colspan="5" style="color:var(--sub)">暂无订单</td></tr>`;

    $("#users").innerHTML = r.users.length
      ? r.users.map((u) => `<tr><td>${u.username}</td><td>${u.credits} 页</td>
          <td>${u.inviter || "—"}</td><td>${fmtTime(u.time)}</td></tr>`).join("")
      : `<tr><td colspan="4" style="color:var(--sub)">暂无用户</td></tr>`;
  } catch (e) {
    $("#dash").classList.add("hidden");
    const g = $("#gate");
    g.classList.remove("hidden");
    if (e.code === 401) g.innerHTML = `请先在 <a href="/app">工作台</a> 登录管理员账号后再访问。`;
    else if (e.code === 403) g.innerHTML = `当前账号无运营后台权限。`;
    else g.innerHTML = `加载失败（${e.code || "网络错误"}）。`;
  }
}

// ---------- 卡密管理 ----------
function showCodes(codes, msg) {
  $("#cdkResult").classList.remove("hidden");
  $("#cdkResultMsg").textContent = msg;
  $("#cdkCodes").value = codes.join("\n");
}

async function loadBatches() {
  try {
    const d = await api("/api/admin/cdkeys");
    $("#cdkBatches").innerHTML = d.batches.length
      ? d.batches.map((b) => {
          const eb = encodeURIComponent(b.batch);
          return `<tr>
          <td>${b.batch}</td><td>${b.pages} 页</td><td>${b.total}</td>
          <td>${b.used}</td><td><b>${b.left}</b></td>
          <td><button class="link det" data-batch="${eb}">明细</button>
            ${b.left ? `· <button class="link exp" data-batch="${eb}" data-pages="${b.pages}">导出未用</button>` : ""}</td>
        </tr>`;
        }).join("")
      : `<tr><td colspan="6" style="color:var(--sub)">还没有卡密，用上方表单生成。</td></tr>`;
    $("#cdkBatches").querySelectorAll("button.exp").forEach((btn) =>
      btn.addEventListener("click", async () => {
        const batch = decodeURIComponent(btn.dataset.batch);
        const r = await api(`/api/admin/cdkeys/export?batch=${encodeURIComponent(batch)}&pages=${btn.dataset.pages}`);
        showCodes(r.codes, `批次「${batch}」剩余 ${r.codes.length} 个未用卡密`);
      })
    );
    $("#cdkBatches").querySelectorAll("button.det").forEach((btn) =>
      btn.addEventListener("click", () => queryCdkeys({ batch: decodeURIComponent(btn.dataset.batch) }))
    );
  } catch (_) {}
}

const CDK_ST = { used: "已使用", unused: "未使用" };
const cdkTime = (t) => (t ? String(t).replace("T", " ").slice(0, 16) : "—");

async function queryCdkeys(opts) {
  opts = opts || {};
  const q = opts.q !== undefined ? opts.q : $("#cdkQ").value.trim();
  const status = opts.status !== undefined ? opts.status : $("#cdkStatus").value;
  const batch = opts.batch || "";
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (status) params.set("status", status);
  if (batch) params.set("batch", batch);
  $("#cdkListMsg").textContent = "查询中…";
  try {
    const d = await api("/api/admin/cdkeys/list?" + params.toString());
    $("#cdkListMsg").textContent = batch
      ? `批次「${batch}」共 ${d.items.length} 条`
      : `共 ${d.items.length} 条`;
    $("#cdkList").innerHTML = d.items.length
      ? d.items.map((k) => `<tr>
          <td class="code">${k.code}</td><td>${k.pages}</td><td>${k.batch}</td>
          <td class="st-${k.status}">${CDK_ST[k.status] || k.status}</td>
          <td>${k.used_by || "—"}</td><td>${cdkTime(k.used_at)}</td></tr>`).join("")
      : `<tr><td colspan="6" style="color:var(--sub)">没有匹配的卡密。</td></tr>`;
  } catch (e) {
    $("#cdkListMsg").textContent = "查询失败";
  }
}

$("#cdkQuery").addEventListener("click", () => queryCdkeys());
$("#cdkQ").addEventListener("keydown", (e) => { if (e.key === "Enter") queryCdkeys(); });
$("#cdkStatus").addEventListener("change", () => queryCdkeys());

$("#cdkGen").addEventListener("click", async () => {
  const pages = +$("#cdkPages").value;
  const count = +$("#cdkCount").value;
  const batch = $("#cdkBatch").value.trim();
  $("#cdkGen").disabled = true;
  $("#cdkGen").textContent = "生成中…";
  try {
    const fd = new FormData();
    fd.append("pages", pages); fd.append("count", count); fd.append("batch", batch);
    const r = await api("/api/admin/cdkeys/generate", { method: "POST", body: fd });
    showCodes(r.codes, `已生成 ${r.count} 个 · 每个 ${r.pages} 页${r.batch ? " · 批次 " + r.batch : ""}`);
    loadBatches();
    load();
    queryCdkeys({ q: "", status: "" });
  } catch (e) {
    alert("生成失败：" + (e.message || e.code));
  } finally {
    $("#cdkGen").disabled = false;
    $("#cdkGen").textContent = "生成卡密";
  }
});

$("#cdkCopy").addEventListener("click", () => {
  const ta = $("#cdkCodes");
  ta.select();
  navigator.clipboard?.writeText(ta.value);
  $("#cdkCopy").textContent = "已复制";
  setTimeout(() => ($("#cdkCopy").textContent = "复制全部"), 1500);
});

$("#cdkDownload").addEventListener("click", () => {
  const blob = new Blob([$("#cdkCodes").value], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "dualpdf-cdkeys.txt";
  a.click();
  URL.revokeObjectURL(a.href);
});

$("#refresh").addEventListener("click", () => { load(); loadBatches(); });
load();
loadBatches();
setInterval(load, 30000);
