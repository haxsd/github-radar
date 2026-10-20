const tabs = document.querySelectorAll("#tabs .tab");
tabs.forEach(tab => {
  tab.onclick = () => {
    tabs.forEach(t => { t.classList.remove("active"); t.setAttribute("aria-selected","false"); });
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    tab.setAttribute("aria-selected","true");
    const panel = document.querySelector(`.panel[data-panel="${tab.dataset.panel}"]`);
    if (panel) panel.classList.add("active");
  };
});
// 周飙升还没数据时，默认落到「新收录」，避免一进来看到空表
(function () {
  const weekPanel = document.querySelector('.panel[data-panel="week"]');
  if (weekPanel && weekPanel.querySelector(".empty")) {
    const newTab = document.querySelector('#tabs .tab[data-panel="new"]');
    if (newTab) newTab.click();
  }
})();

// ---------- 点击行查看详情 ----------
const modal = document.getElementById('modal');
const mbox = document.getElementById('mbox');
const LANG_COLORS = {
  Python:"#3572A5", JavaScript:"#f1e05a", TypeScript:"#3178c6", Rust:"#dea584", Go:"#00ADD8",
  "C++":"#f34b7d", C:"#555555", "C#":"#178600", Java:"#b07219", Swift:"#F05138", Kotlin:"#A97BFF",
  HTML:"#e34c26", CSS:"#563d7c", Shell:"#89e051", Ruby:"#701516", PHP:"#4F5D95", Lua:"#000080",
  Zig:"#ec915c", Dart:"#00B4AB", Vue:"#41b883", Svelte:"#ff3e00", Elixir:"#6e4a7e", Haskell:"#5e5086"
};
let lastFocused = null;
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtStars(n){ if(n>=1000) return (n/1000).toFixed(n>=10000?0:1)+"k"; return String(n??0); }
function langDot(lang){
  const color = LANG_COLORS[lang] || "#8b98ab";
  return `<span class="dot" style="background:${color}"></span>`;
}
function openModal(c){
  lastFocused = document.activeElement;
  const tags=(c.tags||[]).map((t,i)=>{
    const kind=t.split(":")[0], label=(c.tag_labels||[])[i]||t;
    if(kind==="cat") return "";
    const cls = kind==="kw"?"kw":kind==="feature"?"feat":"";
    return `<span class="mtag ${cls}">${kind==="kw"?"#":""}${esc(label)}</span>`;
  }).join("");
  const points=(c.points||[]).length
    ? `<ul class="mpoints">${c.points.map(p=>`<li>${esc(p)}</li>`).join("")}</ul>` : "";
  mbox.innerHTML = `
    <div class="mtitle">${esc(c.full_name)}</div>
    <div class="mmeta">
      ${c.language?`<span>${langDot(c.language)}${esc(c.language)}</span>`:""}
      <span>★ ${fmtStars(c.stars)}</span>
      ${c.license?`<span>${esc(c.license)}</span>`:""}
      ${c.category?`<span>${esc(c.category)}</span>`:""}
      ${c.judgement?`<span>${esc(c.judgement)}</span>`:""}
    </div>
    ${c.description_zh?`<div style="font-size:17px;font-weight:650;line-height:1.5;margin:0 0 10px">${esc(c.description_zh)}</div>`:""}
    ${c.summary_zh?`<div class="msum">${esc(c.summary_zh)}</div>`:""}
    ${points}
    <div class="mtags">${tags}</div>
    <div class="mfoot">
      <button type="button" class="btn primary" onclick="window.open('${esc(c.html_url)}','_blank','noreferrer')">打开 GitHub</button>
      <button type="button" class="btn good" onclick="saveRepo(${c.repo_id})">收藏</button>
      <button type="button" class="btn ghost" onclick="closeModal()">关闭 Esc</button>
    </div>`;
  modal.classList.add('open');
  setTimeout(()=>{
    if(window.dialogFocus) window.dialogFocus.enter(modal, mbox);
    else mbox.focus();
    mbox.scrollTop = 0;
  }, 20);
}
function closeModal(){
  modal.classList.remove('open');
  if(window.dialogFocus) window.dialogFocus.leave();
  if(lastFocused && lastFocused.focus) lastFocused.focus();
}
async function saveRepo(id){
  try{
    await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({repo_id:id,action:'save'})});
    window.toast('已收藏 ✓');
    closeModal();
  }catch(e){ window.toast('收藏失败'); }
}
document.querySelectorAll('.rrow[data-repo]').forEach(r=>{
  r.onclick = async ()=>{
    const id = r.dataset.repo; if(!id) return;
    try{
      const res = await fetch('/api/repo/'+id);
      const d = await res.json();
      if(d.ok) openModal(d.card);
    }catch(e){}
  };
  r.onkeydown = (e)=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); r.click(); } };
});
modal.onclick = (e)=>{ if(e.target===modal) closeModal(); };
document.addEventListener('keydown',(e)=>{ if(e.key==='Escape') closeModal(); });

// 便于截图/分享：/rank?detail=1 自动打开第一个榜单项目
if (new URLSearchParams(location.search).get("detail") === "1") {
  setTimeout(() => {
    const first = document.querySelector('.panel.active .rrow[data-repo]');
    if (first) first.click();
  }, 350);
}
