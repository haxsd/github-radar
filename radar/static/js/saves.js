function cardOf(el){ return el.closest(".scard"); }
function editNote(repoId, btn){
  const card = cardOf(btn);
  const editor = card.querySelector(".note-edit");
  editor.hidden = !editor.hidden;
  if(!editor.hidden) editor.querySelector("textarea").focus();
}
function cancelNote(repoId, btn){
  const card = cardOf(btn);
  card.querySelector(".note-edit").hidden = true;
}
async function saveNote(repoId, btn){
  const card = cardOf(btn);
  const text = card.querySelector(".note-edit textarea").value.trim();
  try{
    const r = await fetch("/api/action", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({repo_id: repoId, action: "save", note: text})});
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || "保存失败");
    let noteEl = card.querySelector(".note");
    if(text){
      if(!noteEl){
        noteEl = document.createElement("div");
        noteEl.className = "note";
        card.querySelector(".note-edit").before(noteEl);
      }
      noteEl.textContent = text;
    } else if(noteEl){
      noteEl.remove();
    }
    card.querySelector(".note-edit").hidden = true;
    window.toast(text ? "备注已保存" : "备注已清除");
  }catch(e){
    window.toast("保存备注失败：" + e.message);
  }
}
async function unsave(repoId, btn){
  const card = cardOf(btn);
  try{
    const r = await fetch("/api/action", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({repo_id: repoId, action: "unsave"})});
    const d = await r.json();
    if(!d.ok) throw new Error(d.error || "取消失败");
    card.style.transition = ".22s";
    card.style.opacity = "0";
    card.style.transform = "scale(.96)";
    setTimeout(()=>{ card.remove(); window.toast("已取消收藏"); }, 220);
  }catch(e){
    window.toast("取消收藏失败：" + e.message);
  }
}
