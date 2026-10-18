"""本地网页：信息流 / 榜单 / 收藏 + JSON API。"""

from __future__ import annotations

import threading
import time

import requests
from flask import Flask, jsonify, redirect, render_template, request, send_file

from . import collect, config, db, feed, llm

app = Flask(__name__, template_folder="templates")


import gzip


@app.after_request
def _compress(response):
    """对 HTML / JSON 做轻量 gzip，减少传输体积。"""
    if response.status_code < 200 or response.status_code >= 300:
        return response
    if response.direct_passthrough or "Content-Encoding" in response.headers:
        return response
    ctype = response.headers.get("Content-Type", "")
    if not any(k in ctype for k in ("text/html", "application/json", "text/css", "text/javascript")):
        return response
    if "gzip" not in request.headers.get("Accept-Encoding", ""):
        return response
    data = response.get_data()
    if len(data) < 800:
        return response
    compressed = gzip.compress(data, 6)
    if len(compressed) >= len(data):
        return response
    response.set_data(compressed)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Vary"] = "Accept-Encoding"
    return response


def _needs_setup() -> bool:
    github_ok = config.github_token_status() != "missing"
    llm_ok = bool(config.LLM_API_KEY) or config.LLM_PROVIDER == "ollama"
    return not (github_ok and llm_ok)


def _ctx(page: str) -> dict:
    return {"page": page, "stats": feed.stats(), "needs_setup": _needs_setup()}


def _window_note(data: dict) -> str:
    span = float(data.get("span_days") or 0)
    window = int(data.get("window_days") or 0)
    if span < 1:
        hours = max(1, round(span * 24))
        return f"统计窗口：最近约 {hours} 小时（数据会随每天 3 次采集逐步扩展到完整 {window} 天）"
    if span < window - 0.2:
        return f"统计窗口：目前只积累了 {span:.1f} 天数据（目标 {window} 天，会随采集自动补齐）"
    return f"统计窗口：最近 {window} 天"


@app.get("/")
def index():
    return render_template(
        "feed.html",
        **_ctx("feed"),
        categories=feed.category_counts(),
        groups=feed.tag_groups(),
        profile=feed.profile_summary(),
    )


@app.get("/rank")
def rank_page():
    week = feed.ranking(days=7, limit=60)
    month = feed.ranking(days=30, limit=60)
    return render_template(
        "rank.html",
        **_ctx("rank"),
        week=week,
        month=month,
        week_note=_window_note(week),
        month_note=_window_note(month),
        newcomers=feed.newcomers(60),
        top=feed.top_stars(60),
    )


@app.get("/saves")
def saves_page():
    return render_template("saves.html", **_ctx("saves"), cards=feed.saved_cards())


@app.get("/history")
def history_page():
    return render_template("history.html", **_ctx("history"), data=feed.history())


@app.get("/daily")
def daily_page():
    return render_template("daily.html", **_ctx("daily"), cards=feed.daily(12))


@app.get("/settings")
def settings_page():
    return render_template(
        "settings.html",
        **_ctx("settings"),
        providers=config.PROVIDERS,
        current={
            "provider": config.LLM_PROVIDER,
            "base_url": config.LLM_BASE_URL,
            "model": config.LLM_MODEL,
            "json_mode": config.LLM_JSON_MODE,
            "disable_thinking": config.LLM_DISABLE_THINKING,
        },
        github_status=config.github_token_status(),
        has_llm_key=bool(config.LLM_API_KEY),
        web_port=config.WEB_PORT,
    )


@app.post("/api/settings")
def api_settings_save():
    data = request.get_json(silent=True) or {}
    values: dict[str, str] = {}
    token = str(data.get("github_token") or "").strip()
    if token:
        values["GITHUB_TOKEN"] = token
    provider = str(data.get("provider") or config.LLM_PROVIDER).strip().lower()
    if provider not in config.PROVIDERS:
        return jsonify({"ok": False, "error": "未知的模型服务"}), 400
    preset = config.PROVIDERS[provider]
    values["LLM_PROVIDER"] = provider
    values["LLM_BASE_URL"] = str(data.get("base_url") or "").strip() or str(preset["base_url"] or "")
    values["LLM_MODEL"] = str(data.get("model") or "").strip() or str(preset["model"] or "")
    api_key = str(data.get("api_key") or "").strip()
    if api_key:
        values["LLM_API_KEY"] = api_key
    values["LLM_JSON_MODE"] = "1" if data.get("json_mode", True) else "0"
    values["LLM_DISABLE_THINKING"] = "1" if data.get("disable_thinking", True) else "0"
    try:
        config.save_env(values)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"写入 .env 失败：{exc}"}), 500
    return jsonify(
        {
            "ok": True,
            "provider": config.LLM_PROVIDER,
            "model": config.LLM_MODEL,
            "github_status": config.github_token_status(),
        }
    )


@app.post("/api/settings/test")
def api_settings_test():
    data = request.get_json(silent=True) or {}
    target = data.get("target")
    if target == "github":
        try:
            token = config.resolve_github_token()
            resp = requests.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "Connection": "close",
                },
                timeout=20,
            )
            if resp.status_code == 401:
                return jsonify({"ok": False, "error": "GitHub token 无效（401）"})
            resp.raise_for_status()
            return jsonify({"ok": True, "message": f"已连接 GitHub：{resp.json().get('login')}"})
        except Exception as exc:
            return jsonify({"ok": False, "error": f"GitHub 连接失败：{exc}"})
    if target == "llm":
        started = time.time()
        try:
            llm._chat_json(
                [{"role": "user", "content": '只输出 JSON：{"ok": true}'}], max_tokens=50
            )
            ms = int((time.time() - started) * 1000)
            return jsonify(
                {"ok": True, "message": f"模型可用：{config.LLM_MODEL}（{ms} ms）"}
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": f"模型调用失败：{exc}"})
    return jsonify({"ok": False, "error": "未知的测试目标"}), 400


THUMB_DIR = config.DATA_DIR / "thumbs"
_THUMB_PENDING: set[tuple[int, int]] = set()
_THUMB_LOCK = threading.Lock()


@app.get("/favicon.ico")
def favicon():
    icon = config.assets_dir() / "icon.png"
    if icon.exists():
        return send_file(str(icon), mimetype="image/png", max_age=86400)
    return "", 204


def _thumb_path(repo_id: int, width: int):
    return THUMB_DIR / f"{repo_id}_{width}.jpg"


def _placeholder_thumb(width: int):
    """本地生成的占位预览图（深色渐变 + 雷达圆环），真实图失败时兜底。"""
    cache = THUMB_DIR / f"_placeholder_{width}.jpg"
    if cache.exists():
        return cache
    try:
        from PIL import Image, ImageDraw

        height = max(1, int(width * 9 / 16))
        img = Image.new("RGB", (width, height), (20, 26, 38))
        draw = ImageDraw.Draw(img)
        for y in range(height):
            ratio = y / max(1, height - 1)
            draw.line(
                [(0, y), (width, y)],
                fill=(20 + int(18 * ratio), 26 + int(22 * ratio), 38 + int(30 * ratio)),
            )
        cx, cy = width // 2, height // 2
        for radius, alpha in ((min(width, height) * 0.36, 70), (min(width, height) * 0.24, 90)):
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                outline=(90, 130, 220),
                width=max(1, width // 240),
            )
        dot = max(2, width // 90)
        draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=(150, 190, 255))
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        img.save(cache, "JPEG", quality=82, optimize=True)
        return cache
    except Exception:
        return None


def _avatar_url(owner: str) -> str:
    return f"https://github.com/{owner}.png?size=120"


def _generate_thumb(repo_id: int, width: int, og: str, owner: str) -> None:
    """下载 GIF/PNG 预览图并压缩缓存（供后台线程与请求共用）。"""
    key = (repo_id, width)
    with _THUMB_LOCK:
        if key in _THUMB_PENDING:
            return
        _THUMB_PENDING.add(key)
    try:
        cache = _thumb_path(repo_id, width)
        if cache.exists():
            return
        import io

        import requests as rq
        from PIL import Image

        sess = rq.Session()
        sess.trust_env = False  # 本机代理会拖慢/卡住图片下载
        resp = sess.get(og, timeout=12)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        ratio = width / float(img.width)
        img = img.resize((width, max(1, int(img.height * ratio))), Image.LANCZOS)
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        img.save(tmp, "JPEG", quality=80, optimize=True)
        tmp.replace(cache)
    except Exception:
        pass
    finally:
        with _THUMB_LOCK:
            _THUMB_PENDING.discard(key)


def _warm_thumbs(limit: int = 800, width: int = 240) -> None:
    """后台预热：提前生成未读卡片的列表缩略图。"""
    try:
        conn = db.connect()
        db.init_db(conn)
        rows = conn.execute(
            "SELECT r.id, r.og_image, r.owner FROM events e JOIN repos r ON r.id=e.repo_id "
            "WHERE e.card_ready=1 AND r.hidden=0 AND r.og_image IS NOT NULL AND r.og_image<>'' "
            "ORDER BY e.occurred_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        pending = [r for r in rows if not _thumb_path(r["id"], width).exists()]
        if not pending:
            return
        from concurrent.futures import ThreadPoolExecutor

        # 限速：2 并发 + 间隔提交，避免触发 GitHub 图片 CDN 的 429
        with ThreadPoolExecutor(max_workers=2) as pool:
            for row in pending:
                pool.submit(_generate_thumb, row["id"], width, row["og_image"], row["owner"])
                time.sleep(0.45)
    except Exception as exc:
        print(f"[thumbs] 预热失败: {exc}")


def _start_thumb_warmer() -> None:
    def _loop() -> None:
        while True:
            _warm_thumbs()
            time.sleep(300)

    threading.Thread(target=_loop, daemon=True).start()


@app.get("/thumb/<int:repo_id>")
def thumb(repo_id: int):
    """项目预览图：缓存命中直接返回；列表宽度未命中时先给头像、后台生成。"""
    try:
        width = max(160, min(int(request.args.get("w", 480)), 1200))
    except ValueError:
        width = 480
    cache = _thumb_path(repo_id, width)
    if cache.exists():
        return send_file(str(cache), mimetype="image/jpeg", max_age=86400)

    conn = db.connect()
    db.init_db(conn)
    row = conn.execute("SELECT og_image, owner FROM repos WHERE id=?", (repo_id,)).fetchone()
    conn.close()
    if not row:
        return "", 404
    og = row["og_image"]
    owner = row["owner"] or ""
    if og:
        _generate_thumb(repo_id, width, og, owner)
        if cache.exists():
            return send_file(str(cache), mimetype="image/jpeg", max_age=86400)
    placeholder = _placeholder_thumb(width)
    if placeholder and placeholder.exists():
        return send_file(str(placeholder), mimetype="image/jpeg", max_age=120)
    return redirect(_avatar_url(owner), code=302)

@app.get("/api/similar/<int:repo_id>")
def api_similar(repo_id: int):
    return jsonify({"items": feed.similar(repo_id, 6)})


@app.get("/api/saves.md")
def api_saves_md():
    cards = feed.saved_cards()
    lines = ["# GitHub 中文雷达 · 收藏", "",
             f"共 {len(cards)} 个项目", ""]
    for c in cards:
        lines.append(f"- [{c['full_name']}]({c['html_url']}) · ★{c['stars']}"
                     + (f" · {c['category']}" if c.get("category") else ""))
        if c.get("description_zh"):
            lines.append(f"  - {c['description_zh']}")
        if c.get("summary_zh"):
            lines.append(f"  - {c['summary_zh']}")
        if c.get("note"):
            lines.append(f"  - 备注：{c['note']}")
    body = "\n".join(lines)
    from flask import Response

    return Response(
        body, mimetype="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=github-radar-saves.md"},
    )


@app.get("/api/feed")
def api_feed():
    try:
        limit = int(request.args.get("limit", 15))
    except ValueError:
        limit = 15
    limit = max(1, min(limit, 50))
    category = request.args.get("category") or None
    raw_tags = request.args.get("tags") or ""
    tags = [t for t in (x.strip() for x in raw_tags.split(",")) if t]
    cards = feed.next_cards(limit, category=category, tags=tags)
    return jsonify(
        {
            "cards": cards,
            "stats": feed.stats(),
            "categories": feed.category_counts(),
            "groups": feed.tag_groups(),
            "profile": feed.profile_summary(),
            "filter": {"category": category, "tags": tags},
        }
    )


@app.get("/api/profile")
def api_profile():
    return jsonify(feed.profile_summary())


@app.post("/api/action")
def api_action():
    data = request.get_json(silent=True) or {}
    try:
        repo_id = int(data.get("repo_id") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "bad repo_id"}), 400
    action = data.get("action")
    conn = db.connect()
    db.init_db(conn)
    try:
        if action in ("skip", "like", "shown"):
            db.mark_seen(conn, repo_id, action)
        elif action == "unsee":
            db.unmark_seen(conn, repo_id, "skip")
            db.unmark_seen(conn, repo_id, "shown")
            db.unmark_seen(conn, repo_id, "like")
        elif action == "save":
            db.add_save(conn, repo_id, str(data.get("note") or ""))
            db.mark_seen(conn, repo_id, "save")  # 收藏同时作为正反馈信号
        elif action == "unsave":
            conn.execute("DELETE FROM saves WHERE repo_id=?", (repo_id,))
            db.unmark_seen(conn, repo_id, "save")
        else:
            conn.close()
            return jsonify({"ok": False, "error": "bad action"}), 400
        conn.commit()
    except Exception as exc:  # 采集写库时可能短暂锁定
        conn.close()
        return jsonify({"ok": False, "error": f"数据库正忙，请重试：{exc}"}), 503
    conn.close()
    feed.invalidate_cache()
    return jsonify({"ok": True, "unread": feed.stats().get("unread", 0)})


@app.post("/api/demo/load")
def api_demo_load():
    from . import demo

    try:
        result = demo.load_demo()
    except Exception as exc:
        return jsonify({"ok": False, "error": f"载入示例数据失败：{exc}"}), 500
    return jsonify({"ok": True, **result})


@app.get("/api/stats")
def api_stats():
    return jsonify(feed.stats())


@app.get("/api/rank")
def api_rank():
    try:
        days = int(request.args.get("days", 7))
    except ValueError:
        days = 7
    return jsonify(feed.ranking(days=max(1, min(days, 90)), limit=60))


@app.get("/api/categories")
def api_categories():
    return jsonify({"categories": feed.category_counts()})


@app.get("/api/repo/<int:repo_id>")
def api_repo(repo_id: int):
    card = feed.card_by_id(repo_id)
    if not card:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "card": card})


def _startup_catchup() -> None:
    try:
        collect.catchup_if_stale(max_age_hours=8.0)
    except Exception as exc:  # 后台线程不能把进程带崩
        print(f"[startup] 补跑异常: {exc}")


def _port_in_use(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def main() -> None:
    if _port_in_use(config.WEB_HOST, config.WEB_PORT):
        print("服务已在运行，跳过启动")
        return
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    threading.Thread(target=_startup_catchup, daemon=True).start()
    _start_thumb_warmer()
    print(f"雷达页面：http://{config.WEB_HOST}:{config.WEB_PORT}")
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
