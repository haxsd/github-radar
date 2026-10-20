"""本地网页：信息流 / 榜单 / 收藏 + JSON API。"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import requests
from flask import Flask, jsonify, redirect, render_template, request, send_file

from . import collect, config, db, feed, llm, netguard, network

app = Flask(__name__, template_folder="templates")
logger = logging.getLogger(__name__)


import gzip


def _is_loopback(addr: str | None) -> bool:
    """判断客户端地址是否为本机回环（127.0.0.0/8、::1、localhost、IPv4-mapped IPv6）。"""
    if not addr:
        return False
    value = str(addr).strip()
    if not value:
        return False
    if value.lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped.is_loopback
    return ip.is_loopback


def _provided_admin_token(data: dict | None = None) -> str:
    header = (request.headers.get("X-Radar-Token") or "").strip()
    if header:
        return header
    if isinstance(data, dict):
        return str(data.get("admin_token") or "").strip()
    return ""


def _can_write_settings(remote_addr: str | None, provided_token: str | None = None) -> bool:
    """本机访问直接放行；非本机必须带对 WEB_ADMIN_TOKEN。

    没有配置 WEB_ADMIN_TOKEN 时，任何非 loopback 客户端都不能改设置/测试连接，
    避免 Docker / NAS 暴露到局域网时被其他人写走密钥。
    """
    if _is_loopback(remote_addr):
        return True
    admin = (config.WEB_ADMIN_TOKEN or "").strip()
    if not admin or not provided_token:
        return False
    # compare_digest 的 str 版本只支持 ASCII；统一编码成 bytes，顺便避免中文口令 500
    try:
        return hmac.compare_digest(admin.encode("utf-8"), str(provided_token).strip().encode("utf-8"))
    except (TypeError, ValueError):
        return False


def _settings_denied_response():
    return (
        jsonify(
            {
                "ok": False,
                "error": "已拒绝远程修改设置：请在本机访问；或在 .env 配置 WEB_ADMIN_TOKEN 后重启，并在设置页填写管理口令。",
            }
        ),
        403,
    )


def _has_newline(values: dict) -> bool:
    for value in values.values():
        text = str(value)
        if "\n" in text or "\r" in text:
            return True
    return False


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
    return {
        "page": page,
        "stats": feed.stats(),
        "needs_setup": _needs_setup(),
        "version": config.APP_VERSION,
    }


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
    remote_client = not _is_loopback(request.remote_addr)
    settings_writable = (not remote_client) or bool((config.WEB_ADMIN_TOKEN or "").strip())
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
        settings_remote=remote_client,
        settings_writable=settings_writable,
        radar_proxy_configured=bool(config.RADAR_PROXY),
        radar_proxy_display=config.mask_proxy(config.RADAR_PROXY),
    )


@app.post("/api/settings")
def api_settings_save():
    data = request.get_json(silent=True) or {}
    if not _can_write_settings(request.remote_addr, _provided_admin_token(data)):
        logger.warning("拒绝设置写入请求，remote=%s", request.remote_addr)
        return _settings_denied_response()
    values: dict[str, str] = {}
    token = str(data.get("github_token") or "").strip()
    provider = str(data.get("provider") or config.LLM_PROVIDER).strip().lower()
    if provider not in config.PROVIDERS:
        return jsonify({"ok": False, "error": "未知的模型服务"}), 400
    preset = config.PROVIDERS[provider]
    base_url = str(data.get("base_url") or "").strip() or str(preset["base_url"] or "")
    model = str(data.get("model") or "").strip() or str(preset["model"] or "")
    api_key = str(data.get("api_key") or "").strip()
    proxy_raw = str(data.get("proxy") or "").strip()
    if proxy_raw.lower() in ("direct", "none", "off", "no"):
        proxy_raw = ""  # 显式直连 / 清除代理
    if _has_newline(
        {
            "github_token": token,
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "proxy": proxy_raw,
        }
    ):
        return jsonify({"ok": False, "error": "配置值不能包含换行符"}), 400
    if proxy_raw:
        values["RADAR_PROXY"] = proxy_raw
    elif "proxy" in data:
        values["RADAR_PROXY"] = ""
    if token:
        values["GITHUB_TOKEN"] = token
    values["LLM_PROVIDER"] = provider
    values["LLM_BASE_URL"] = base_url
    values["LLM_MODEL"] = model
    if api_key:
        values["LLM_API_KEY"] = api_key
    values["LLM_JSON_MODE"] = "1" if data.get("json_mode", True) else "0"
    values["LLM_DISABLE_THINKING"] = "1" if data.get("disable_thinking", True) else "0"
    try:
        config.save_env(values)
    except Exception as exc:
        logger.warning("写入 .env 失败: %s", exc)
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
    if not _can_write_settings(request.remote_addr, _provided_admin_token(data)):
        logger.warning("拒绝远程设置测试请求，remote=%s", request.remote_addr)
        return _settings_denied_response()
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
                proxies=config.radar_proxies(),
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
_PLACEHOLDER_LOCK = threading.Lock()


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
    # 页面首次打开时会有多张图并发请求占位图；加锁 + 原子写，避免 Windows 上写同一个文件失败
    with _PLACEHOLDER_LOCK:
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
            tmp = cache.with_suffix(".tmp")
            img.save(tmp, "JPEG", quality=82, optimize=True)
            tmp.replace(cache)
            return cache
        except Exception as exc:
            logger.warning("生成占位预览图失败（width=%s）: %s", width, exc)
            return None


def _avatar_url(owner: str) -> str:
    return f"https://github.com/{owner}.png?size=120"


# 缩略图下载的资源限制：只接受图片类型，限制大小与像素，避免被恶意图片拖垮。
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


def _fetch_image_bytes(url: str, timeout: float = 12.0, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    """下载图片；每一跳重定向都重新做域名白名单校验（防 SSRF）。

    只允许 https + GitHub 图片域名，拒绝私网 IP、非图片 Content-Type 和超大响应。
    """
    if not netguard.is_safe_image_url(url):
        raise ValueError(f"不允许的图片地址: {url[:120]}")
    sess = requests.Session()
    sess.trust_env = False  # 默认绕过系统代理；代理由 RADAR_PROXY 显式配置
    proxies = config.radar_proxies()
    if proxies:
        sess.proxies.update(proxies)
    try:
        for _ in range(4):
            resp = sess.get(url, timeout=timeout, allow_redirects=False, stream=True)
            try:
                if resp.is_redirect:
                    location = resp.headers.get("Location") or ""
                    url = urljoin(url, location)
                    if not netguard.is_safe_image_url(url):
                        raise ValueError(f"重定向到不允许的图片地址: {url[:120]}")
                    continue
                resp.raise_for_status()
                content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if content_type and content_type not in ALLOWED_IMAGE_TYPES:
                    raise ValueError(f"不支持的图片类型: {content_type}")
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("图片超过大小上限")
                    chunks.append(chunk)
                return b"".join(chunks)
            finally:
                resp.close()
        raise ValueError("图片重定向次数过多")
    finally:
        sess.close()


def _generate_thumb(repo_id: int, width: int, og: str, owner: str) -> bool:
    """下载 GIF/PNG 预览图并压缩缓存（只应在后台线程里调用）。

    返回 True 表示请求的宽度已经落盘；False 表示被 429 限流/下载失败（稍后重试）。
    """
    key = (repo_id, width)
    with _THUMB_LOCK:
        if key in _THUMB_PENDING:
            return _thumb_path(repo_id, width).exists()
        _THUMB_PENDING.add(key)
    try:
        cache = _thumb_path(repo_id, width)
        if cache.exists():
            return True
        import io

        from PIL import Image

        if not _thumb_wait_slot():
            return False  # 429 冷却期内不下载，等前端下次轮询/下一次打开页面再试
        with _THUMB_DOWNLOAD_LOCK:
            data = _fetch_image_bytes(og, timeout=8.0)
        img = Image.open(io.BytesIO(data))
        if getattr(img, "format", None) not in ("JPEG", "PNG", "GIF", "WEBP"):
            raise ValueError(f"不支持的图片格式: {img.format}")
        if img.width * img.height > MAX_IMAGE_PIXELS:
            raise ValueError(f"图片像素过大: {img.width}x{img.height}")
        img = img.convert("RGB")
        # 一次下载同时生成 240 / 480 / 960 三档（列表、日报、详情复用），减少 CDN 请求
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        for out_width in sorted({width, *THUMB_STANDARD_WIDTHS}):
            target = _thumb_path(repo_id, out_width)
            if target.exists():
                continue
            ratio = out_width / float(img.width)
            out = img.resize((out_width, max(1, int(img.height * ratio))), Image.LANCZOS)
            tmp = target.with_suffix(".tmp")
            out.save(tmp, "JPEG", quality=80, optimize=True)
            tmp.replace(target)
        return cache.exists()
    except Exception as exc:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status == 429:
            retry_after = 0
            try:
                retry_after = int((response.headers or {}).get("Retry-After") or 0)
            except (TypeError, ValueError):
                retry_after = 0
            _thumb_note_429(repo_id, width, retry_after)
            logger.debug("预览图下载被限流 repo=%s", repo_id)
        else:
            logger.warning("预览图生成失败 repo=%s: %s", repo_id, exc)
        return False
    finally:
        with _THUMB_LOCK:
            _THUMB_PENDING.discard(key)


# 按需生成缩略图的线程池：HTTP 请求只负责把任务排进来，绝不等待下载完成。
# 实际远端下载由 _THUMB_DOWNLOAD_LOCK 串行化，多线程只是避免阻塞请求线程。
THUMB_ON_DEMAND_WORKERS = 3
_THUMB_EXECUTOR = ThreadPoolExecutor(
    max_workers=THUMB_ON_DEMAND_WORKERS, thread_name_prefix="thumb-on-demand"
)
_THUMB_QUEUED: set[tuple[int, int]] = set()

# 缩略图下载全局限速 + 429 处理：GitHub 图片 CDN 对**并发连接**很敏感（实测并发 3 个
# 左右就会开始 429，顺序 1 个则稳定），因此所有下载串行执行；429 时单图退避，
# 只有短时间大量 429 才触发全局冷却。
THUMB_MIN_INTERVAL = 2.0          # 两次下载请求之间至少间隔多少秒（串行 + 保守限速）
THUMB_WARM_INTERVAL = 2.0         # 后台预热两次下载之间的最小间隔（给网页请求让路）
THUMB_REPO_RETRY_SECONDS = 45.0   # 单个仓库 429 后的默认重试间隔
THUMB_COOLDOWN_SECONDS = 30.0     # 连续大量 429 时的全局冷却
THUMB_429_BURST_WINDOW = 60.0
THUMB_429_BURST_LIMIT = 5
# 一次下载后顺手生成这些常用宽度，避免列表(240)/日报(480)/详情(960)各下载一次
THUMB_STANDARD_WIDTHS = (240, 480, 960)
_THUMB_RATE_LOCK = threading.Lock()
_THUMB_DOWNLOAD_LOCK = threading.Lock()  # 所有远端下载串行，避免并发触发 CDN 429
_THUMB_NEXT_SLOT = 0.0
_THUMB_COOLDOWN_UNTIL = 0.0
_THUMB_429_TIMES: list[float] = []
_THUMB_RETRY_AFTER: dict[tuple[int, int], float] = {}
_THUMB_LAST_ON_DEMAND = 0.0


def _thumb_cooling_down() -> bool:
    with _THUMB_RATE_LOCK:
        return time.time() < _THUMB_COOLDOWN_UNTIL


def _thumb_retry_remaining(repo_id: int, width: int) -> float:
    """单图 429 退避剩余秒数。"""
    with _THUMB_RATE_LOCK:
        return max(0.0, _THUMB_RETRY_AFTER.get((repo_id, width), 0.0) - time.time())


def _thumb_recent_on_demand(window: float = 120.0) -> bool:
    """最近是否有网页请求在等缩略图（有就暂停后台预热，别抢 CDN 配额）。"""
    with _THUMB_RATE_LOCK:
        return time.time() - _THUMB_LAST_ON_DEMAND < window


def _thumb_mark_on_demand() -> None:
    global _THUMB_LAST_ON_DEMAND
    with _THUMB_RATE_LOCK:
        _THUMB_LAST_ON_DEMAND = time.time()


def _thumb_note_429(repo_id: int, width: int, retry_after: int = 0) -> None:
    """单张图 429：只让这张图退避；短时间大量 429 才全局冷却一小会儿。"""
    global _THUMB_COOLDOWN_UNTIL, _THUMB_429_TIMES
    now = time.time()
    wait = max(20.0, min(float(retry_after or 45), 180.0))
    with _THUMB_RATE_LOCK:
        if len(_THUMB_RETRY_AFTER) > 5000:  # 防止长期运行字典无限增长
            _THUMB_RETRY_AFTER.clear()
        _THUMB_RETRY_AFTER[(repo_id, width)] = now + wait
        _THUMB_429_TIMES = [
            t for t in _THUMB_429_TIMES if now - t <= THUMB_429_BURST_WINDOW
        ]
        _THUMB_429_TIMES.append(now)
        if len(_THUMB_429_TIMES) >= THUMB_429_BURST_LIMIT and now >= _THUMB_COOLDOWN_UNTIL:
            _THUMB_COOLDOWN_UNTIL = now + THUMB_COOLDOWN_SECONDS
            logger.warning("图片 CDN 连续 429，暂停缩略图下载 %ss", int(THUMB_COOLDOWN_SECONDS))


def _thumb_wait_slot() -> bool:
    """线程共享的下载限速：预约一个时隙并等到它。冷却期内返回 False。"""
    global _THUMB_NEXT_SLOT
    now = time.time()
    with _THUMB_RATE_LOCK:
        if now < _THUMB_COOLDOWN_UNTIL:
            return False
        start = max(now, _THUMB_NEXT_SLOT)
        _THUMB_NEXT_SLOT = start + THUMB_MIN_INTERVAL
    wait = start - now
    if wait > 0:
        time.sleep(wait)
    return True


def _schedule_thumb(repo_id: int, width: int, og: str, owner: str) -> None:
    """把缩略图生成排到后台线程池（同一张图去重，避免轮询重复入队）。"""
    if not og or not netguard.is_safe_image_url(og):
        return
    _thumb_mark_on_demand()
    if _thumb_cooling_down() or _thumb_retry_remaining(repo_id, width) > 0:
        return
    key = (repo_id, width)
    with _THUMB_LOCK:
        if key in _THUMB_QUEUED or _thumb_path(repo_id, width).exists():
            return
        _THUMB_QUEUED.add(key)

    def _task() -> None:
        try:
            _generate_thumb(repo_id, width, og, owner)
        finally:
            with _THUMB_LOCK:
                _THUMB_QUEUED.discard(key)

    try:
        _THUMB_EXECUTOR.submit(_task)
    except (RuntimeError, ValueError) as exc:  # 解释器退出时线程池可能已关闭
        with _THUMB_LOCK:
            _THUMB_QUEUED.discard(key)
        logger.debug("提交缩略图任务失败 repo=%s: %s", repo_id, exc)


def _placeholder_reply(width: int):
    """占位图响应：不让浏览器长缓存，后台生成后由前端带 `v=` 自动替换。"""
    placeholder = _placeholder_thumb(width)
    if not placeholder or not placeholder.exists():
        return None
    response = send_file(str(placeholder), mimetype="image/jpeg", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Thumb-State"] = "placeholder"
    return response


def _warm_thumbs(limit: int = 120, width: int = 240) -> None:
    """后台预热：网页空闲时慢慢补未读卡片的列表缩略图，有网页请求时主动让路。"""
    if _thumb_recent_on_demand():
        logger.info("[thumbs] 最近有网页在加载缩略图，本轮预热跳过")
        return
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

        # 1 个预热线程 + 更大间隔，不和用户当前页面的缩略图抢 CDN 配额
        with ThreadPoolExecutor(max_workers=1) as pool:
            for row in pending:
                if _thumb_cooling_down() or _thumb_recent_on_demand():
                    logger.info("[thumbs] 暂停本轮预热（限流冷却或网页正在加载）")
                    break
                pool.submit(_generate_thumb, row["id"], width, row["og_image"], row["owner"])
                time.sleep(THUMB_WARM_INTERVAL)
    except Exception as exc:
        print(f"[thumbs] 预热失败: {exc}")
        logger.warning("[thumbs] 预热失败: %s", exc)


def _start_thumb_warmer() -> None:
    def _loop() -> None:
        time.sleep(30)  # 启动先让网页首屏按需加载，避免预热抢先消耗 CDN 配额
        while True:
            _warm_thumbs()
            time.sleep(120 if _thumb_recent_on_demand(300) else 600)

    threading.Thread(target=_loop, daemon=True).start()


# ---------- 手动预下载预览图（设置页按钮 / CLI 复用）----------
_PREFETCH_LOCK = threading.Lock()
_PREFETCH_STATE: dict[str, Any] = {
    "running": False,
    "done": 0,
    "saved": 0,
    "failed": 0,
    "total": 0,
    "started_at": "",
    "finished_at": "",
    "error": "",
}


def _thumb_cache_stats() -> dict[str, int]:
    conn = db.connect()
    db.init_db(conn)
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM repos WHERE hidden=0 AND og_image IS NOT NULL AND og_image<>''"
    ).fetchone()["n"]
    conn.close()
    try:
        cached = sum(
            1
            for path in THUMB_DIR.glob("*_240.jpg")
            if path.name.split("_", 1)[0].isdigit()
        )
    except OSError:
        cached = 0
    return {"repos_with_image": int(total), "cached": int(cached)}


def _thumb_prefetch_candidates(limit: int = 200) -> list[dict[str, Any]]:
    """优先未读的最新卡片，其次是最近卡片；只返回 240 预览图还没缓存的。"""
    limit = max(1, min(int(limit), 500))
    conn = db.connect()
    db.init_db(conn)
    base = """SELECT r.id, r.og_image, r.owner, MAX(e.occurred_at) AS last_at
              FROM events e JOIN repos r ON r.id = e.repo_id
              WHERE e.card_ready = 1 AND r.hidden = 0
                AND r.og_image IS NOT NULL AND r.og_image <> ''
              {where}
              GROUP BY r.id ORDER BY last_at DESC LIMIT ?"""
    rows = conn.execute(
        base.format(
            where="AND NOT EXISTS (SELECT 1 FROM seen s WHERE s.repo_id = r.id)"
        ),
        (limit * 5,),
    ).fetchall()
    items: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for row in rows:
        if len(items) >= limit:
            break
        if row["id"] in seen_ids or _thumb_path(row["id"], 240).exists():
            continue
        seen_ids.add(row["id"])
        items.append({"id": row["id"], "og_image": row["og_image"], "owner": row["owner"] or ""})
    if len(items) < limit:
        for row in conn.execute(base.format(where=""), (limit * 5,)).fetchall():
            if len(items) >= limit:
                break
            if row["id"] in seen_ids or _thumb_path(row["id"], 240).exists():
                continue
            seen_ids.add(row["id"])
            items.append({"id": row["id"], "og_image": row["og_image"], "owner": row["owner"] or ""})
    conn.close()
    return items


def _run_thumb_prefetch(items: list[dict[str, Any]]) -> None:
    saved = 0
    failed = 0
    consecutive_failed = 0
    processed = 0
    stopped = False
    try:
        for index, item in enumerate(items, 1):
            processed = index
            ok = False
            for attempt in range(2):
                if _thumb_path(item["id"], 240).exists():
                    ok = True
                    break
                if _thumb_cooling_down():
                    break  # 全局冷却中，不再重试，避免继续触发 429
                _generate_thumb(item["id"], 240, item["og_image"], item["owner"])
                if _thumb_path(item["id"], 240).exists():
                    ok = True
                    break
                if attempt == 0:
                    time.sleep(3)
            if ok:
                saved += 1
                consecutive_failed = 0
            else:
                failed += 1
                consecutive_failed += 1
            with _PREFETCH_LOCK:
                _PREFETCH_STATE["done"] = index
                _PREFETCH_STATE["saved"] = saved
                _PREFETCH_STATE["failed"] = failed
            if consecutive_failed >= 4:
                stopped = True
                break
            # 用户正在页面里等图时，给按需下载让一点路
            if _thumb_recent_on_demand(20):
                time.sleep(1.0)
    except Exception as exc:  # _generate_thumb 自己会吞异常，这里兜底
        logger.warning("预览图预下载中断: %s", exc)
        with _PREFETCH_LOCK:
            _PREFETCH_STATE["error"] = str(exc)
    finally:
        with _PREFETCH_LOCK:
            _PREFETCH_STATE["running"] = False
            _PREFETCH_STATE["done"] = processed
            _PREFETCH_STATE["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            if stopped or failed:
                _PREFETCH_STATE["error"] = (
                    f"图片 CDN 限流，已保存 {saved}/{processed} 张；"
                    "可稍后重试，或配置 RADAR_PROXY 后再预下载"
                )


def _prefetch_snapshot() -> dict[str, Any]:
    with _PREFETCH_LOCK:
        return dict(_PREFETCH_STATE)



@app.get("/thumb/<int:repo_id>")
def thumb(repo_id: int):
    """项目预览图：缓存命中直接返回；未命中立即给占位图，后台生成后由前端自动替换。

    关键点：这里绝不等待远端图片下载（GitHub 图片 CDN 慢/超时会让整页卡住），
    只把任务排进后台线程池，HTTP 请求立刻返回占位图。
    """
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
        _schedule_thumb(repo_id, width, og, owner)
    placeholder = _placeholder_reply(width)
    if placeholder is not None:
        return placeholder
    return redirect(_avatar_url(owner), code=302)


@app.get("/api/thumbs/status")
def api_thumbs_status():
    """缩略图状态查询：返回已生成好的 id，未生成的顺手排入后台任务。

    前端会用这个接口轮询，把占位图替换成真实预览图，用来实现「页面秒开、图片渐进加载」。
    """
    try:
        width = max(160, min(int(request.args.get("w", 240)), 1200))
    except ValueError:
        width = 240
    ids: list[int] = []
    for part in (request.args.get("ids") or "").split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        rid = int(part)
        if rid not in ids:
            ids.append(rid)
        if len(ids) >= 120:
            break
    if not ids:
        return jsonify({"ready": [], "width": width})
    ready = [rid for rid in ids if _thumb_path(rid, width).exists()]
    ready_set = set(ready)
    missing = [rid for rid in ids if rid not in ready_set]
    if missing:
        conn = db.connect()
        db.init_db(conn)
        markers = ",".join("?" * len(missing))
        rows = conn.execute(
            f"SELECT id, og_image, owner FROM repos WHERE id IN ({markers})", missing
        ).fetchall()
        conn.close()
        for row in rows:
            if row["og_image"]:
                _schedule_thumb(row["id"], width, row["og_image"], row["owner"] or "")
    return jsonify({"ready": ready, "width": width})


@app.get("/api/thumbs/cache")
def api_thumbs_cache():
    """本地预览图缓存统计 + 当前预下载进度。"""
    return jsonify({"cache": _thumb_cache_stats(), "prefetch": _prefetch_snapshot()})


@app.post("/api/thumbs/prefetch")
def api_thumbs_prefetch():
    """把未读/最新卡片的预览图预下载到 data/thumbs，之后浏览直接读本地。"""
    data = request.get_json(silent=True) or {}
    if not _can_write_settings(request.remote_addr, _provided_admin_token(data)):
        logger.warning("拒绝远程缩略图预下载请求，remote=%s", request.remote_addr)
        return _settings_denied_response()
    try:
        limit = int(data.get("limit") or 200)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 500))
    with _PREFETCH_LOCK:
        if _PREFETCH_STATE["running"]:
            return jsonify({"ok": False, "error": "预下载正在进行中，请稍候"}), 409
    items = _thumb_prefetch_candidates(limit)
    if not items:
        return jsonify({"ok": True, "total": 0, "message": "未读卡片都已有本地预览图"})
    with _PREFETCH_LOCK:
        _PREFETCH_STATE.update(
            {
                "running": True,
                "done": 0,
                "saved": 0,
                "failed": 0,
                "total": len(items),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "finished_at": "",
                "error": "",
            }
        )
    threading.Thread(target=_run_thumb_prefetch, args=(items,), daemon=True).start()
    logger.info("开始预下载预览图：%s 张", len(items))
    return jsonify(
        {"ok": True, "total": len(items), "message": f"开始在后台预下载 {len(items)} 张预览图"}
    )

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


@app.get("/api/network/status")
def api_network_status():
    """网络连通性（GitHub API / 图片 CDN / 模型接口），默认缓存 5 分钟。"""
    force = request.args.get("refresh") == "1"
    try:
        return jsonify(network.check_all(force=force))
    except Exception as exc:  # 网络检测自身不能 500
        logger.warning("网络状态检测失败: %s", exc)
        return (
            jsonify(
                {
                    "checked_at": "",
                    "level": "unknown",
                    "cached": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "targets": {},
                    "proxy": {"radar": "—", "llm": "—", "system": "—"},
                }
            ),
            200,
        )


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
        logger.warning("[startup] 补跑异常: %s", exc)


def _port_in_use(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex((host, port)) == 0


def main() -> None:
    config.setup_logging()
    if not _is_loopback(config.WEB_HOST):
        print(
            f"[安全] WEB_HOST={config.WEB_HOST}：非本机访问时，网页设置写入需要 WEB_ADMIN_TOKEN"
        )
        if not (config.WEB_ADMIN_TOKEN or "").strip():
            print(
                "[安全] 未配置 WEB_ADMIN_TOKEN：非本机访问时设置页只读（保存/测试接口返回 403）。"
                "Docker 用户建议在宿主机 .env 配好后再启动。"
            )
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
