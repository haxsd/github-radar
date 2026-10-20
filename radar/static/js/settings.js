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
  Object.assign(body, adminPayload());
  box.className = "result"; box.textContent = "保存中…";
  try{
    const r = await fetch("/api/settings", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || "保存失败");
    box.className = "result ok";
    box.textContent = `已保存：${d.provider} / ${d.model}（GitHub：${d.github_status}）`;
    $("ghToken").value = ""; $("apiKey").value = "";
    rememberAdminToken();
    clearDirty();
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

(function initAdminToken(){
  const el = $("adminToken");
  if(el) el.value = loadAdminToken();
})();
