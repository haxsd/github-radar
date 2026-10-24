(function () {
"use strict";
// 全局 toast：各页面统一调用 window.toast("...")，避免每个模板重复实现
var toastTimer = null;
window.toast = function (message) {
  var el = document.getElementById("toast");
  if (!el) return;
  el.textContent = message || "";
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { el.classList.remove("show"); }, 1900);
};

// 清除采集失败横幅。失败记录保存在 meta 里，必须显式清除才会消失。
window.dismissError = async function (btn) {
  var box = btn.closest(".errbar") || btn.closest(".result");
  if (btn) btn.disabled = true;
  try {
    var token = "";
    try { token = sessionStorage.getItem("radar_admin_token") || ""; } catch (e) {}
    var resp = await fetch("/api/status/clear-error", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(token ? { admin_token: token } : {}),
    });
    var data = await resp.json();
    if (!resp.ok || !data.ok) throw new Error(data.error || "清除失败");
    if (box && box.classList.contains("errbar")) box.remove();
    if (box && box.classList.contains("result")) {
      box.className = "result ok";
      box.textContent = "失败提示已清除。";
    }
    window.toast("已清除失败提示");
  } catch (e) {
    if (btn) btn.disabled = false;
    window.toast(e.message || "清除失败");
  }
};

// ---------- 对话框焦点管理（供 feed / rank 等弹层复用） ----------
var activeDialog = null;
function dialogFocusables(root) {
  if (!root) return [];
  var nodes = root.querySelectorAll(
    'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
  );
  return Array.prototype.filter.call(nodes, function (el) {
    return el.offsetParent !== null || el === document.activeElement;
  });
}
document.addEventListener("keydown", function (e) {
  if (!activeDialog || e.key !== "Tab") return;
  var focusable = dialogFocusables(activeDialog);
  if (!focusable.length) return;
  var first = focusable[0], last = focusable[focusable.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault(); last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault(); first.focus();
  }
});
window.dialogFocus = {
  enter: function (root, initial) {
    activeDialog = root;
    var target = initial || dialogFocusables(root)[0];
    if (target && target.focus) target.focus();
    if (target && typeof target.scrollTop === "number") target.scrollTop = 0;
  },
  leave: function () { activeDialog = null; }
};

// 缩略图渐进加载：后端先返回占位图并在后台生成，这里轮询状态后自动替换。
// 这样即使 GitHub 图片 CDN 很慢/超时，页面也能秒开、图片逐渐出现。
var POLL_MS = 2500;
var GIVE_UP_MS = 180000;
var polling = false;

function isRealThumb(img) {
  var w = Number(img.getAttribute("data-thumb-w") || "240");
  var ph = Math.round(w * 9 / 16);
  return img.complete && img.naturalWidth > 0 && Math.abs(img.naturalHeight - ph) > 1;
}

function pendingImgs(now) {
  var out = [];
  var nodes = document.querySelectorAll("img[data-thumb-repo]");
  for (var i = 0; i < nodes.length; i++) {
    var img = nodes[i];
    if (img.getAttribute("data-thumb-done") === "1") continue;
    if (isRealThumb(img)) { img.setAttribute("data-thumb-done", "1"); continue; }
    if (!img.getAttribute("data-thumb-since")) img.setAttribute("data-thumb-since", String(now));
    if (now - Number(img.getAttribute("data-thumb-since")) > GIVE_UP_MS) {
      img.setAttribute("data-thumb-done", "1");
      continue;
    }
    out.push(img);
  }
  return out;
}

async function refreshThumbs() {
  if (polling || document.hidden) return;
  var imgs = pendingImgs(Date.now());
  if (!imgs.length) return;
  polling = true;
  try {
    var groups = {};
    imgs.forEach(function (img) {
      var w = img.getAttribute("data-thumb-w") || "240";
      groups[w] = groups[w] || {};
      groups[w][img.getAttribute("data-thumb-repo")] = true;
    });
    var widths = Object.keys(groups);
    for (var g = 0; g < widths.length; g++) {
      var w = widths[g];
      var ids = Object.keys(groups[w]).slice(0, 120);
      var resp = await fetch("/api/thumbs/status?w=" + encodeURIComponent(w) + "&ids=" + ids.join(","));
      if (!resp.ok) continue;
      var data = await resp.json();
      var ready = {};
      (data.ready || []).forEach(function (id) { ready[String(id)] = true; });
      imgs.forEach(function (img) {
        if ((img.getAttribute("data-thumb-w") || "240") !== w) return;
        if (!ready[String(img.getAttribute("data-thumb-repo"))]) return;
        img.setAttribute("data-thumb-done", "1");
        img.src = img.src.split("?")[0] + "?w=" + w + "&v=" + Date.now();
      });
    }
  } catch (e) {
    // 轮询失败不影响页面
  } finally {
    polling = false;
  }
}

window.refreshThumbs = refreshThumbs;
setInterval(refreshThumbs, POLL_MS);
window.addEventListener("load", function () { setTimeout(refreshThumbs, 700); });
})();

// ---------- 网络状态：顶栏一个小指示灯，不占用首页内容区 ----------
(function () {
  "use strict";
  var LABELS = { github: "GitHub API", images: "图片 CDN", llm: "模型接口" };

  function apply(data) {
    var level = (data && data.level) || "unknown";
    var dot = document.getElementById("netDot");
    var text = document.getElementById("netText");
    var netState = document.getElementById("netState");
    if (dot) dot.classList.remove("busy", "warn", "bad");
    var label = "网络状态未知";
    if (level === "ok") label = "网络正常";
    else if (level === "degraded") { label = "网络受限"; if (dot) dot.classList.add("warn"); }
    else if (level === "offline") { label = "网络异常"; if (dot) dot.classList.add("bad"); }
    if (text) text.textContent = label;
    var targets = (data && data.targets) || {};
    var parts = [];
    Object.keys(LABELS).forEach(function (key) {
      var t = targets[key];
      if (!t || t.configured === false) return;
      if (!t.ok) parts.push(LABELS[key] + " 不可达");
      else if (t.warning) parts.push(LABELS[key] + " 较慢");
    });
    if (netState) {
      var tip = "网络：" + label;
      if (parts.length) tip += "（" + parts.join("、") + "）";
      if (data && data.proxy) {
        tip += " ｜ GitHub/图片代理：" + data.proxy.radar
          + " ｜ 模型代理：" + data.proxy.llm;
      }
      netState.title = tip + "；点击去设置查看";
    }
  }

  async function refresh() {
    try {
      var resp = await fetch("/api/network/status", { cache: "no-store" });
      if (!resp.ok) return;
      apply(await resp.json());
    } catch (e) {
      // 网络检测失败时保持原有显示
    }
  }

  window.refreshNetworkStatus = refresh;
  setTimeout(refresh, 1500);
  setInterval(refresh, 300000);
})();
