const state = { cards: [], focus: -1, loading: false, exhausted: false, tags: [], groups: [], catLabels: {}, total: 0 };
const $ = (id) => document.getElementById(id);
const LANG_COLORS = {
  Python:"#3572A5", JavaScript:"#f1e05a", TypeScript:"#3178c6", Rust:"#dea584", Go:"#00ADD8",
  "C++":"#f34b7d", C:"#555555", "C#":"#178600", Java:"#b07219", Swift:"#F05138", Kotlin:"#A97BFF",
  HTML:"#e34c26", CSS:"#563d7c", Shell:"#89e051", Ruby:"#701516", PHP:"#4F5D95", Lua:"#000080",
  Zig:"#ec915c", Dart:"#00B4AB", Vue:"#41b883", Svelte:"#ff3e00", Elixir:"#6e4a7e", Haskell:"#5e5086"
};
const KIND_LABEL = { new:["新项目","new"], release:["新版本","release"], stars:["涨星","stars"], push:["更新",""] };
const ICON = {
  bookmark: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h12v17l-6-4-6 4z"/></svg>',
  skip: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  radar: '<svg class="i i-lg" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="2.4"/><path d="M12 3a9 9 0 0 1 9 9"/><path d="M12 6.6a5.4 5.4 0 0 1 5.4 5.4"/><path d="M3 12a9 9 0 0 0 9 9"/></svg>',
  check: '<svg class="i i-lg" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6L9 17l-5-5"/></svg>',
  clock: '<svg class="i i-lg" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
};

function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function fmtStars(n){ if(n>=1000) return (n/1000).toFixed(n>=10000?0:1)+"k"; return String(n??0); }
function timeAgo(iso){
  if(!iso) return "";
  const t = new Date(iso).getTime(); if(isNaN(t)) return "";
  const m = Math.max(0, Math.floor((Date.now()-t)/60000));
  if(m<60) return m+" 分钟前";
  const h = Math.floor(m/60); if(h<24) return h+" 小时前";
  const d = Math.floor(h/24); if(d<30) return d+" 天前";
  return Math.floor(d/30)+" 个月前";
}
function judgeClass(j){ return j==="值得用"?"good":j==="不建议"?"bad":"mid"; }
function kindBadge(c){
  if(!c.kind || c.kind==="new") return "";
  const k = KIND_LABEL[c.kind] || ["更新",""];
  return k[0] ? `<span class="kind ${k[1]}">${k[0]}</span>` : "";
}
function ownerOf(full){ const i=full.indexOf("/"); return i<0?full:full.slice(0,i); }
function nameOf(full){ const i=full.indexOf("/"); return i<0?full:full.slice(i+1); }
function avatar(c){
  const owner = ownerOf(c.full_name);
  const letter = esc(owner.slice(0,1).toUpperCase());
  return `<div class="avatar"><img loading="lazy" alt="" src="https://github.com/${encodeURIComponent(owner)}.png?size=80"
     onerror="this.style.display='none';this.nextElementSibling.style.display='grid'"><span class="fallback">${letter}</span></div>`;
}
function thumb(c){
  const owner = ownerOf(c.full_name);
  const letter = esc(owner.slice(0,1).toUpperCase());
  return `<div class="thumb"><img loading="lazy" decoding="async" alt="" src="/thumb/${c.repo_id}?w=240"
     data-thumb-repo="${c.repo_id}" data-thumb-w="240"
     onerror="this.style.display='none';this.nextElementSibling.style.display='grid'"><span class="tfallback">${letter}</span></div>`;
}
function langDot(lang){
  const color = LANG_COLORS[lang] || "#8b98ab";
  return `<span class="dot" style="background:${color}"></span>`;
}
function deltaText(c){
  if(c.kind==="stars" && c.payload && c.payload.delta) return `<span class="delta">+${fmtStars(c.payload.delta)}</span>`;
  return "";
}
function rowHTML(c, idx){
  const judge = c.judgement ? `<span class="judge ${judgeClass(c.judgement)}">${esc(c.judgement)}</span>` : "";
  const cate = c.category ? `<span class="kind cat">${esc(c.category)}</span>` : "";
  return `<div class="row" data-idx="${idx}" data-id="${c.repo_id}" tabindex="0">
    ${thumb(c)}
    <div class="main">
      <div class="title">
        <div class="repo"><span class="owner">${esc(ownerOf(c.full_name))}</span><span class="slash">/</span>${esc(nameOf(c.full_name))}</div>
        ${kindBadge(c)}${judge}${cate}
      </div>
      <div class="desc">${esc(c.description_zh || c.description || "（暂无中文简介）")}</div>
      <div class="meta">
        ${c.language ? `<span>${langDot(c.language)}${esc(c.language)}</span>` : ""}
        <span>${timeAgo(c.occurred_at)}</span>
        ${c.is_chinese ? `<span>中文友好</span>` : ""}
      </div>
    </div>
    <div class="side">
      <div class="stars">★ <b>${fmtStars(c.stars)}</b>${deltaText(c)}</div>
      <div class="rowacts">
        <button type="button" class="minibtn save" title="收藏（S）" aria-label="收藏 ${esc(c.full_name)}"
          onclick="event.stopPropagation();actRepo(${c.repo_id},'save')">${ICON.bookmark}收藏</button>
        <button type="button" class="minibtn skip" title="跳过（X）" aria-label="跳过 ${esc(c.full_name)}"
          onclick="event.stopPropagation();actRepo(${c.repo_id},'skip')">${ICON.skip}跳过</button>
      </div>
    </div>
  </div>`;
}
function skeletonRows(n){
  let html = "";
  for(let i=0;i<n;i++){
    html += `<div class="skrow" aria-hidden="true">
      <div class="sk"></div>
      <div><div class="sk skline" style="width:${68-i*7}%"></div><div class="sk skline short"></div><div class="sk skline tiny"></div></div>
      <div class="sk skstars"></div>
    </div>`;
  }
  return html;
}
function emptyBlock(icon, title, text, actionHtml){
  return `<div class="empty fade-in">
    <div class="empty-icon">${icon}</div>
    <h2>${title}</h2>
    <p class="muted">${text}</p>
    ${actionHtml || ""}
  </div>`;
}
function renderFilters(cats){
  const box=$("filters");
  const activeCat = state.tags.length===1 && state.tags[0].startsWith("cat:") ? state.tags[0] : null;
  const all=`<button type="button" class="fchip ${state.tags.length?"":"active"}" data-tag="">全部</button>`;
  const items=(cats||[]).map(c=>
    `<button type="button" class="fchip ${activeCat===c.tag?"active":""}" data-tag="${esc(c.tag)}">${esc(c.label)}<span class="n">${c.count}</span></button>`).join("");
  box.innerHTML=all+items;
  box.querySelectorAll(".fchip").forEach(el=>{ el.onclick=()=>setQuickFilter(el.dataset.tag||null); });
}
function labelFor(tag){
  if(state.catLabels[tag]) return state.catLabels[tag];
  for(const g of state.groups) for(const it of g.items) if(it.tag===tag) return it.label;
  return tag;
}
function renderActiveFilters(){
  const box=$("activeFilters");
  if(!state.tags.length){ box.classList.remove("show"); box.innerHTML=""; return; }
  box.classList.add("show");
  box.innerHTML = state.tags.map(t=>
    `<button type="button" class="selchip" data-tag="${esc(t)}" aria-label="移除筛选 ${esc(labelFor(t))}">${esc(labelFor(t))} ×</button>`).join("")
    + `<button type="button" class="selchip" data-tag="__clear">清空全部</button>`;
  box.querySelectorAll(".selchip").forEach(el=>{
    el.onclick=()=>{
      const t=el.dataset.tag;
      if(t==="__clear"){ state.tags=[]; reload(); return; }
      state.tags=state.tags.filter(x=>x!==t); reload();
    };
  });
}
function renderPanel(){
  const body=$("fpanelBody");
  body.innerHTML=(state.groups||[]).map(g=>`
    <div class="fgroup">
      <h4>${esc(g.name)}</h4>
      <div class="fchips">
        ${g.items.map(it=>`<button type="button" class="fchip ${state.tags.includes(it.tag)?"active":""}" data-tag="${esc(it.tag)}">${esc(it.label)}<span class="n">${it.count}</span></button>`).join("")}
      </div>
    </div>`).join("");
  body.querySelectorAll(".fchip").forEach(el=>{
    el.onclick=()=>{
      const t=el.dataset.tag;
      if(state.tags.includes(t)) state.tags=state.tags.filter(x=>x!==t);
      else state.tags.push(t);
      renderPanel();
    };
  });
  const p = window.__profile || {};
  const pos = (p.positive||[]).map(x=>x.label).slice(0,4).join("、");
  $("profileline").innerHTML = p.signals
    ? `已从 ${p.signals} 次收藏/跳过里学习偏好${pos?`：更爱 <b>${esc(pos)}</b>`:""}`
    : "多收藏/跳过几行，排序会越来越懂你";
}
let lastFocused = null;
function openOverlay(el, focusSelector){
  lastFocused = document.activeElement;
  el.classList.add("open");
  const target = focusSelector ? el.querySelector(focusSelector) : el.querySelector("button,a");
  setTimeout(function(){
    if(window.dialogFocus) window.dialogFocus.enter(el, target);
    else if(target && target.focus) target.focus();
  }, 20);
}
function closeOverlay(el){
  el.classList.remove("open");
  if(window.dialogFocus) window.dialogFocus.leave();
  if(lastFocused && lastFocused.focus) lastFocused.focus();
}
function openPanel(){ renderPanel(); openOverlay($("fpanel"), "#fpanelBody .fchip"); }
function closePanel(){ closeOverlay($("fpanel")); }
function applyFilters(){ closePanel(); reload(); }
function clearFilters(){ state.tags=[]; renderPanel(); reload(); }
function setQuickFilter(tag){ state.tags = tag ? [tag] : []; reload(); }
function reload(){
  state.cards=[]; state.exhausted=false; state.loading=false;
  $("rows").innerHTML=skeletonRows(4);
  renderActiveFilters(); renderFilters(lastCats);
  loadMore(true).then(()=>{
    renderActiveFilters();
    if(state.focus>=0) setFocus(0);
  });
}
let lastCats=[];
function updateCount(){
  const loaded = state.cards.length;
  $("listcount").innerHTML = state.tags.length
    ? `筛选后 <b>${loaded}</b> 个`
    : `已加载 <b>${loaded}</b> 个`;
}
async function loadMore(first){
  if(state.loading||state.exhausted) return;
  state.loading=true;
  $("sentinel").innerHTML='<div class="spinner" aria-label="加载中"></div>';
  try{
    const q=new URLSearchParams({limit:"25"});
    if(state.tags.length) q.set("tags", state.tags.join(","));
    const r=await fetch("/api/feed?"+q.toString());
    const d=await r.json();
    const cards=d.cards||[];
    lastCats=d.categories||lastCats;
    state.groups=d.groups||state.groups;
    (d.categories||[]).forEach(c=>{state.catLabels[c.tag]=c.label;});
    window.__profile=d.profile||window.__profile;
    renderFilters(lastCats);
    if(cards.length===0) state.exhausted=true;
    const start=state.cards.length;
    state.cards=state.cards.concat(cards);
    const html=cards.map((c,i)=>rowHTML(c,start+i)).join("");
    if(first) $("rows").innerHTML="";
    $("rows").insertAdjacentHTML("beforeend", html);
    if(html) $("rows").querySelectorAll(".row").forEach(r=>r.classList.add("fade-in"));
    bindRows();
    updateCount();
    if(cards.length===0){
      const total=(d.stats&&d.stats.repos)||0;
      if(total===0 && !state.tags.length){
        $("sentinel").innerHTML=emptyBlock(ICON.radar, "还没有数据",
          '先去 <a href="/settings">设置</a> 填 GitHub Token 和模型 API Key，再跑一次采集；或者先载入内置示例数据看看界面效果（不需要任何 Key）。',
          '<button type="button" class="btn primary" onclick="loadDemo()">载入示例数据</button>');
      } else {
        $("sentinel").innerHTML=emptyBlock(ICON.check,
          state.tags.length?"该筛选下没有更多了":"这一波刷完了",
          "保持应用运行，下一波会在 00:00 / 08:00 / 16:00 自动补齐");
      }
    } else {
      $("sentinel").innerHTML="";
    }
  }catch(e){ $("sentinel").textContent="加载失败："+e.message; }
  finally{ state.loading=false; }
  if(!state.exhausted && state.cards.length<12) loadMore();
}
async function loadDemo(){
  $("sentinel").innerHTML='<div class="spinner" aria-label="载入中"></div>';
  try{
    const r=await fetch("/api/demo/load",{method:"POST"});
    const d=await r.json();
    if(!d.ok) throw new Error(d.error||"载入失败");
    window.toast(`已载入 ${d.total} 个示例项目`);
    reload();
  }catch(e){
    $("sentinel").textContent="载入示例数据失败："+e.message;
  }
}
function bindRows(){
  document.querySelectorAll("#rows .row").forEach(row=>{
    if(row._bound) return; row._bound=true;
    row.onclick=()=>{ const i=+row.dataset.idx; if(i>=0&&i<state.cards.length) openDetail(i); };
    row.onkeydown=(e)=>{
      if(e.key==="Enter"||e.key===" "){ e.preventDefault(); row.click(); }
    };
  });
  const rows=document.querySelectorAll("#rows .row");
  if(state.focus<0 && rows.length) setFocus(0);
}
function setFocus(i){
  const rows=document.querySelectorAll("#rows .row");
  if(!rows.length) return;
  i=Math.max(0,Math.min(i,rows.length-1));
  state.focus=i;
  rows.forEach(r=>r.classList.remove("focus"));
  const row=rows[i];
  row.classList.add("focus");
  row.scrollIntoView({block:"nearest",behavior:"smooth"});
}
function focusNext(){ if(state.cards.length-1>state.focus) setFocus(state.focus+1); }
function focusPrev(){ setFocus(Math.max(0,state.focus-1)); }
function openDetail(i){
  const c=state.cards[i]; if(!c) return;
  state.focus=i;
  openCard(c);
}
function openCard(c){
  const tags=(c.tags||[]).map((t,k)=>{
    const kind=t.split(":")[0], label=(c.tag_labels||[])[k]||t;
    if(kind==="cat") return "";
    const cls = kind==="kw"?"kw":kind==="feature"?"feat":"";
    return `<span class="dchip ${cls}">${kind==="kw"?"#":""}${esc(label)}</span>`;
  }).join("");
  const why = c.kind==="stars"&&c.payload&&c.payload.delta
      ? `24 小时涨了 <b>+${fmtStars(c.payload.delta)}★</b>`
      : (c.kind==="release"&&c.payload&&c.payload.tag ? `发布新版本 <b>${esc(c.payload.tag)}</b>`
      : `刚达到收录门槛（${fmtStars(c.stars)}★）`);
  $("dbox").innerHTML = `
    <div class="dhead">
      ${avatar(c)}
      <div style="min-width:0">
        <div class="dname"><a href="${esc(c.html_url)}" target="_blank" rel="noreferrer">${esc(c.full_name)}</a></div>
        <div class="dmeta">
          ${c.language?`<span>${langDot(c.language)}${esc(c.language)}</span>`:""}
          <span>★ ${fmtStars(c.stars)}</span>
          ${c.license?`<span>${esc(c.license)}</span>`:""}
          ${c.category?`<span>${esc(c.category)}</span>`:""}
          <span>${timeAgo(c.occurred_at)}</span>
        </div>
      </div>
    </div>
    <img class="dpreview" alt="" src="/thumb/${c.repo_id}?w=960"
      data-thumb-repo="${c.repo_id}" data-thumb-w="960" onerror="this.remove()">
    ${c.description_zh?`<div style="font-size:17px;font-weight:650;line-height:1.5;margin:0 0 8px">${esc(c.description_zh)}</div>`:""}
    ${c.summary_zh?`<div class="dsummary">${esc(c.summary_zh)}</div>`:""}
    ${(c.points&&c.points.length)?`<ul class="dpoints">${c.points.map(p=>`<li>${esc(p)}</li>`).join("")}</ul>`:""}
    <div class="dchips">${tags}</div>
    <div class="dsimwrap">
      <div class="dsimtitle">类似项目</div>
      <div class="dsimlist" id="dsimlist">加载中…</div>
    </div>
    <div class="dwhy">为什么刷到它：${why}</div>
    <div class="dactions">
      <button type="button" class="btn primary" onclick="cardAct(${c.repo_id},'like')">★ 感兴趣</button>
      <button type="button" class="btn good" onclick="cardAct(${c.repo_id},'save')">收藏</button>
      <button type="button" class="btn" onclick="cardAct(${c.repo_id},'skip')">跳过</button>
      <button type="button" class="btn ghost" onclick="window.open('${esc(c.html_url)}','_blank','noreferrer')">打开 GitHub</button>
      <button type="button" class="btn ghost" onclick="closeDetail()">关闭 Esc</button>
    </div>`;
  openOverlay($("detail"), "#dbox");
  $("dbox").scrollTop = 0;
  loadSimilar(c.repo_id);
}
async function loadSimilar(repoId){
  const box=document.getElementById("dsimlist"); if(!box) return;
  try{
    const r=await fetch("/api/similar/"+repoId);
    const d=await r.json();
    const items=d.items||[];
    box.innerHTML = items.length
      ? items.map(it=>`<a class="dsim" href="#" onclick="event.preventDefault();loadRepoCard(${it.repo_id})">
            <span class="dsimname">${esc(it.full_name)}</span>
            <span class="dsimstar">★${fmtStars(it.stars)}</span>
            <span class="dsimdesc">${esc(it.description_zh||'')}</span></a>`).join("")
      : '<span style="color:var(--muted);font-size:13px">没有找到相似项目</span>';
  }catch(e){ box.innerHTML='<span style="color:var(--muted);font-size:13px">加载失败</span>'; }
}
async function loadRepoCard(repoId){
  try{
    const r=await fetch("/api/repo/"+repoId);
    const d=await r.json();
    if(d.ok) openCard(d.card);
  }catch(e){}
}
function closeDetail(){ closeOverlay($("detail")); }
async function cardAct(repoId, action){
  const labels={like:"已标记感兴趣",save:"已收藏",skip:"已跳过，同类会降权"};
  try{
    await fetch("/api/action",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({repo_id:repoId,action})});
  }catch(e){}
  closeDetail();
  window.toast(labels[action]||"OK");
  if(action==="save"||action==="skip"){
    const idx = state.cards.findIndex(c=>c.repo_id===repoId);
    if(idx>=0) removeRow(idx);
  }
}
function removeRow(i){
  const card=state.cards[i]; if(!card) return;
  // 按 repo_id 找 DOM 行：删行动画期间 DOM 里还留着上一行，用索引会删错
  const row=document.querySelector('#rows .row[data-id="' + card.repo_id + '"]');
  if(row){ row.classList.add("removing"); setTimeout(()=>row.remove(),200); }
  state.cards.splice(i,1);
  const remain=document.querySelectorAll("#rows .row");
  remain.forEach((r,k)=>{ r.dataset.idx=k; });
  if(state.focus>=state.cards.length) state.focus=state.cards.length-1;
  updateCount();
  if(remain.length) setFocus(Math.max(0, Math.min(state.focus, remain.length-1)));
  if(state.cards.length<8 && !state.exhausted) loadMore();
}
function act(i, action){
  const c=state.cards[i]; if(!c) return;
  const labels={like:"已标记感兴趣",save:"已收藏",skip:"已跳过，同类会降权"};
  fetch("/api/action",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({repo_id:c.repo_id,action})}).catch(()=>{});
  closeDetail();
  window.toast(labels[action]||"OK");
  if(action==="save"||action==="skip") removeRow(i);
}
// 行内按钮按 repo_id 操作：删行后 data-idx 会重排，不能再依赖渲染时的旧索引
function actRepo(repoId, action){
  const i=state.cards.findIndex(c=>c.repo_id===repoId);
  if(i>=0) act(i, action);
}
$("openPanel").onclick=openPanel;
$("helpBtn").onclick=()=>{ openOverlay($("help"), ".helpbox"); };
$("refreshBtn").onclick=()=>{ reload(); window.toast("已换一批"); };
$("help").onclick=(e)=>{ if(e.target===$("help")) closeOverlay($("help")); };
$("fpanel").onclick=(e)=>{ if(e.target===$("fpanel")) closePanel(); };
$("detail").onclick=(e)=>{ if(e.target===$("detail")) closeDetail(); };
new IntersectionObserver((entries)=>{
  entries.forEach(en=>{ if(en.isIntersecting) loadMore(); });
},{rootMargin:"600px"}).observe($("sentinel"));
document.addEventListener("keydown",(e)=>{
  const k=e.key.toLowerCase();
  const help=$("help");
  if(e.target && /^(input|textarea|select)$/i.test(e.target.tagName)) return;
  if(k==="?"){ e.preventDefault(); help.classList.contains("open")?closeOverlay(help):openOverlay(help, ".helpbox"); return; }
  if(k==="escape"){ closeDetail(); closePanel(); closeOverlay(help); return; }
  if(k==="f"){ e.preventDefault(); $("fpanel").classList.contains("open")?closePanel():openPanel(); return; }
  if(k==="r"){ e.preventDefault(); reload(); window.toast("已换一批"); return; }
  if($("fpanel").classList.contains("open")||$("detail").classList.contains("open")||help.classList.contains("open")) return;
  if(k==="arrowdown"||k==="j"){ e.preventDefault(); focusNext(); }
  else if(k==="arrowup"||k==="k"){ e.preventDefault(); focusPrev(); }
  else if(k==="enter"){ e.preventDefault(); if(state.focus>=0) openDetail(state.focus); }
  else if(k==="s"){ e.preventDefault(); if(state.focus>=0) act(state.focus,"save"); }
  else if(k==="x"){ e.preventDefault(); if(state.focus>=0) act(state.focus,"skip"); }
  else if(k==="l"){ e.preventDefault(); if(state.focus>=0) act(state.focus,"like"); }
  else if(k==="o"){ e.preventDefault(); if(state.focus>=0){ const c=state.cards[state.focus]; if(c) window.open(c.html_url,"_blank","noreferrer"); } }
  else if(k==="0"){ e.preventDefault(); setQuickFilter(null); }
  else if(/^[1-9]$/.test(k)){
    const chips=document.querySelectorAll("#filters .fchip");
    const target=chips[parseInt(k,10)];
    if(target){ e.preventDefault(); setQuickFilter(target.dataset.tag||null); }
  }
});
(async function init(){
  $("rows").innerHTML=skeletonRows(4);
  const params=new URLSearchParams(location.search);
  const preset=params.get("tags");
  if(preset){ state.tags=preset.split(",").map(x=>x.trim()).filter(Boolean); renderActiveFilters(); }
  await loadMore(true);
  if(state.focus<0 && state.cards.length) setFocus(0);
  if(params.get("panel")==="1") openPanel();
  if(params.get("detail")==="1" && state.cards.length) openDetail(0);
})();
