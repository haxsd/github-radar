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
function markDirty(){
  if(dirty || !SETTINGS_WRITABLE) return;
  dirty = true;
  const btn = $("saveBtn");
  if(btn) btn.classList.add("dirty");
  const hint = $("saveHint");
  if(hint) hint.textContent = "有未保存的修改";
}
function clearDirty(){
  dirty = false;
  const btn = $("saveBtn");
  if(btn) btn.classList.remove("dirty");
  const hint = $("saveHint");
  if(hint) hint.textContent = "";
}
document.querySelectorAll(".sgrid input, .sgrid select").forEach(el=>{
  el.addEventListener("input", markDirty);
  el.addEventListener("change", markDirty);
});

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
    clearDirty();
    refreshNetwork(true);
    window.toast("配置已保存");
  }catch(e){
    box.className = "result err"; box.textContent = e.message;
  }
}

async function testTarget(target){
  const box = target === "github" ? $("ghResult") : $("llmResult");
  if(!writableGuard(box)) return;
  box.className = "result"; box.textContent = "测试中…";
  try{
    const r = await fetch("/api/settings/test", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({target, ...adminPayload()})});
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || "测试失败");
    box.className = "result ok"; box.textContent = d.message;
    rememberAdminToken();
  }catch(e){
    box.className = "result err"; box.textContent = e.message;
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

(function initAdminToken(){
  const el = $("adminToken");
  if(el) el.value = loadAdminToken();
})();
