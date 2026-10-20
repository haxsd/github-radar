const tabs = document.querySelectorAll("#tabs .tab");
tabs.forEach(tab => {
  tab.onclick = () => {
    tabs.forEach(t => { t.classList.remove("active"); t.setAttribute("aria-selected","false"); });
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    tab.setAttribute("aria-selected","true");
    const p = document.querySelector(`.panel[data-panel="${tab.dataset.panel}"]`);
    if (p) p.classList.add("active");
  };
});
async function postAction(repoId, action){
  const r = await fetch("/api/action", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({repo_id: repoId, action})});
  return r.ok;
}
function fadeOut(btn){
  const row = btn.closest(".hrow");
  if(!row) return;
  row.style.transition = ".22s";
  row.style.opacity = "0";
  row.style.transform = "translateX(16px)";
  setTimeout(()=>row.remove(), 220);
}
async function unsee(id, btn){
  if(await postAction(id, "unsee")){ window.toast("已放回信息流 ✓"); fadeOut(btn); }
  else window.toast("操作失败");
}
async function unsave(id, btn){
  if(await postAction(id, "unsave")){ window.toast("已取消收藏"); fadeOut(btn); }
  else window.toast("操作失败");
}
