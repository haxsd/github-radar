const root = document.getElementById("settingsRoot");
const PROVIDERS = JSON.parse((root && root.dataset.providers) || "{}");
const SETTINGS_WRITABLE = !!(root && root.dataset.writable === "1");
function $(id){ return document.getElementById(id); }

function adminTokenValue(){
  const el = $("adminToken");
  return el ? el.value.trim() : "";
}
function adminPayload(){
  const token = adminTokenValue();
  return token ? {admin_token: token} : {};
}
function rememberAdminToken(){
  const token = adminTokenValue();
  if(!token) return;
  try{ sessionStorage.setItem("radar_admin_token", token); }catch(e){}
}
function loadAdminToken(){
  try{ return sessionStorage.getItem("radar_admin_token") || ""; }catch(e){ return ""; }
}
function writableGuard(box){
  if(SETTINGS_WRITABLE) return true;
  if(!box) return false;
  box.className = "result err";
  box.textContent = "远程访问未启用设置写入：请在宿主机 .env 配置 WEB_ADMIN_TOKEN 后重启服务。";
  return false;
}
function togglePw(id, btn){
  const input = $(id);
  if(!input) return;
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  btn.setAttribute("aria-pressed", show ? "true" : "false");
}
let dirty = false;
let hideDockTimer = null;
function setDockState(state, message) {
  const dock = $("saveDock");
  const hint = $("saveHint");
  if (dock) {
    if (hideDockTimer) { clearTimeout(hideDockTimer); hideDockTimer = null; }
    if (state === "clean") {
      dock.hidden = true;
      dock.classList.remove("dirty", "ok");
      return;
    }
    dock.hidden = false;
    dock.classList.toggle("dirty", state === "dirty");
    dock.classList.toggle("ok", state === "ok");
  }
  if (hint) hint.textContent = message || "";
}
function markDirty(){
  if(dirty || !SETTINGS_WRITABLE) return;
  dirty = true;
  const btn = $("saveBtn");
  if(btn) btn.classList.add("dirty");
  setDockState("dirty", "有未保存的修改");
}
function clearDirty(message){
  dirty = false;
  const btn = $("saveBtn");
  if(btn) btn.classList.remove("dirty");
  setDockState("ok", message || "已保存 · 立即生效");
  hideDockTimer = setTimeout(function(){
    const dock = $("saveDock");
    if(dock && !dock.classList.contains("dirty")) dock.hidden = true;
  }, 1600);
}
document.querySelectorAll(".settings-body input, .settings-body select, .remotehint input").forEach(el=>{
  el.addEventListener("input", markDirty);
  el.addEventListener("change", markDirty);
});

function selectProvider(name) {
  const select = $("provider");
  if (!select) return;
  select.value = name;
  document.querySelectorAll(".provtile").forEach((tile) => {
    const active = tile.dataset.provider === name;
    tile.classList.toggle("active", active);
    tile.setAttribute("aria-pressed", active ? "true" : "false");
  });
  applyPreset();
}

function applyPreset(){
  const p = $("provider").value;
  const preset = PROVIDERS[p];
  if(!preset) return;
  if(preset.base_url) $("baseUrl").value = preset.base_url;
  if(preset.model) $("model").value = preset.model;
  $("jsonMode").checked = !!preset.json_mode;
  $("disableThinking").checked = !!preset.disable_thinking;
  markDirty();
}

async function saveSettings(){
  const box = $("llmResult");
  if(!writableGuard(box)) return;
  const body = {
    provider: $("provider").value,
    base_url: $("baseUrl").value.trim(),
    model: $("model").value.trim(),
    json_mode: $("jsonMode").checked,
    disable_thinking: $("disableThinking").checked,
  };
  const tok = $("ghToken").value.trim();
  if(tok) body.github_token = tok;
  const key = $("apiKey").value.trim();
  if(key) body.api_key = key;
  const proxyEl = $("radarProxy");
  if(proxyEl && proxyEl.value.trim()) body.proxy = proxyEl.value.trim();
  Object.assign(body, adminPayload());
  box.className = "result"; box.textContent = "保存中…";
  try{
    const r = await fetch("/api/settings", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || "保存失败");
    box.className = "result ok";
    box.textContent = `已保存：${d.provider} / ${d.model}（GitHub：${d.github_status}）`;
    $("ghToken").value = ""; $("apiKey").value = "";
    if(proxyEl) proxyEl.value = "";
    rememberAdminToken();
    clearDirty("已保存 · 立即生效");
    refreshNetwork(true);
    window.toast("配置已保存");
  }catch(e){
    box.className = "result err"; box.textContent = e.message;
    setDockState("dirty", "保存失败：" + e.message);
  }
}

async function testTarget(target){
  const box = target === "github" ? $("ghResult") : $("llmResult");
  if(!writableGuard(box)) return;
  box.className = "result"; box.textContent = "测试中…";
  const body = {target, ...adminPayload()};
  if(target === "llm"){
    body.provider = $("provider").value;
    body.base_url = $("baseUrl").value.trim();
    body.model = $("model").value.trim();
    body.json_mode = $("jsonMode").checked;
    body.disable_thinking = $("disableThinking").checked;
    const key = $("apiKey").value.trim();
    if(key) body.api_key = key;
  } else if(target === "github"){
    const token = $("ghToken").value.trim();
    if(token) body.github_token = token;
  }
  try{
    const r = await fetch("/api/settings/test", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || "测试失败");
    box.className = "result ok"; box.textContent = d.message;
    window.toast(d.message || "连接正常");
    rememberAdminToken();
  }catch(e){
    box.className = "result err"; box.textContent = e.message;
    window.toast(e.message || "测试失败");
  }
}

// ---------- 网络状态 ----------
const NET_LABELS = { github: "GitHub API", images: "图片 CDN", llm: "模型接口" };

function renderNetwork(data) {
  Object.keys(NET_LABELS).forEach(function (key) {
    const t = (data.targets || {})[key];
    const pill = $("net-" + key + "-pill");
    const detail = $("net-" + key + "-detail");
    if (!pill || !detail) return;
    pill.className = "pill";
    if (!t) {
      pill.textContent = "未知";
      pill.classList.add("warn");
      detail.textContent = "";
      return;
    }
    if (t.configured === false) {
      pill.textContent = "未配置";
      pill.classList.add("warn");
      detail.textContent = [t.message, t.hint].filter(Boolean).join("；");
      return;
    }
    if (t.ok && !t.warning) {
      pill.textContent = "正常 · " + (t.latency_ms || 0) + "ms";
      pill.classList.add("ok");
    } else if (t.ok && t.warning) {
      pill.textContent = "受限 · " + (t.latency_ms || 0) + "ms";
      pill.classList.add("warn");
    } else {
      pill.textContent = "不可达";
      pill.classList.add("bad");
    }
    detail.textContent = [t.message, t.hint].filter(Boolean).join("；");
  });
  const checked = $("netChecked");
  if (checked) {
    const ts = (data.checked_at || "").replace("T", " ").slice(0, 19);
    checked.textContent = ts ? ("检测于 " + ts + (data.cached ? "（缓存）" : "")) : "尚未检测";
  }
  const summary = $("netSummary");
  if (summary) {
    const levelText = data.level === "ok" ? "正常"
      : data.level === "degraded" ? "部分受限"
      : data.level === "offline" ? "不可用" : "未知";
    summary.textContent = levelText;
    summary.className = "advmeta" + (data.level === "ok" ? " ok" : data.level === "degraded" ? " warn" : " bad");
  }
  const proxy = $("netProxy");
  if (proxy && data.proxy) {
    proxy.textContent = "代理：GitHub/图片 " + data.proxy.radar
      + " · 模型 " + data.proxy.llm + " · 系统 " + data.proxy.system;
  }
}

async function refreshNetwork(force) {
  const checked = $("netChecked");
  if (checked && force) checked.textContent = "检测中…";
  try {
    const r = await fetch("/api/network/status" + (force ? "?refresh=1" : ""));
    const d = await r.json();
    renderNetwork(d);
    if (force) window.toast("网络检测完成");
  } catch (e) {
    if (checked) checked.textContent = "网络检测失败：" + e.message;
  }
}
refreshNetwork(false);

// ---------- 预览图缓存 ----------
async function loadThumbCache() {
  try {
    const r = await fetch("/api/thumbs/cache");
    const d = await r.json();
    const cache = d.cache || {};
    if ($("thumbCached")) $("thumbCached").textContent = cache.cached ?? "—";
    if ($("thumbTotal")) $("thumbTotal").textContent = cache.repos_with_image ?? "—";
    const thumbSummary = $("thumbSummary");
    if (thumbSummary) {
      thumbSummary.textContent = (cache.cached != null && cache.repos_with_image != null)
        ? `${cache.cached} / ${cache.repos_with_image}` : "—";
    }
    const p = d.prefetch || {};
    const state = $("thumbState");
    const btn = $("thumbPrefetchBtn");
    const hint = $("thumbHint");
    if (state) {
      if (p.running) state.textContent = `预下载中 ${p.done}/${p.total}…（已保存 ${p.saved || 0}）`;
      else if (p.finished_at) {
        state.textContent = `上次预下载完成：${p.done}/${p.total}（成功 ${p.saved || 0}`
          + (p.failed ? `，失败 ${p.failed}` : "") + "）";
      } else state.textContent = "当前没有预下载任务";
    }
    if (btn) {
      const writable = $("settingsRoot") && $("settingsRoot").dataset.writable === "1";
      btn.disabled = p.running || !writable;
      btn.textContent = p.running ? "预下载中…" : "预下载未读卡片";
    }
    if (hint) {
      if (p.running) hint.textContent = "预下载在后台进行，关闭页面也会继续；完成后缩略图会直接读本地。";
      else if (p.error) hint.textContent = p.error;
      else if (p.finished_at) hint.textContent = "预下载已结束，刷新页面即可看到本地缓存效果。";
    }
    if (p.running) setTimeout(loadThumbCache, 1500);
  } catch (e) {
    if ($("thumbState")) $("thumbState").textContent = "缓存状态读取失败";
  }
}

async function prefetchThumbs() {
  const hint = $("thumbHint");
  if (!writableGuard(hint)) return;
  hint.textContent = "正在启动…";
  try {
    const r = await fetch("/api/thumbs/prefetch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 30, ...adminPayload() }),
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || "启动失败");
    hint.textContent = d.message || "";
    window.toast(d.message || "已开始预下载");
    rememberAdminToken();
    loadThumbCache();
  } catch (e) {
    hint.textContent = e.message;
  }
}

loadThumbCache();

// 顶栏/外链的 #network、#thumbs 锚点：自动展开对应折叠区
function openHashDetails(){
  if(!location.hash) return;
  let target = null;
  try{ target = document.querySelector(location.hash); }catch(e){ return; }
  if(target && target.tagName === "DETAILS") target.open = true;
}
window.addEventListener("hashchange", openHashDetails);
openHashDetails();

(function initAdminToken(){
  const el = $("adminToken");
  if(el) el.value = loadAdminToken();
})();
