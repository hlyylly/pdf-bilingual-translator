const $ = (s) => document.querySelector(s);

async function api(path) {
  const r = await fetch(path);
  if (r.status === 401) throw { code: 401 };
  if (r.status === 403) throw { code: 403 };
  if (!r.ok) throw { code: r.status };
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

$("#refresh").addEventListener("click", load);
load();
setInterval(load, 30000);
