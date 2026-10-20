"""网络连通性检测：GitHub API / 缩略图 CDN / 模型接口。

结果缓存 5 分钟，供网页顶栏和设置页展示。国内网络下 GitHub API 可能慢、
GitHub 图片 CDN 可能无法直连，此时可以配置 RADAR_PROXY / LLM_PROXY。

检测只做最小请求：
- GitHub：有 Token 时查 /rate_limit（5000/小时），否则查 /zen（缓存后每小时最多几次）；
- 图片 CDN：请求域名根路径，任何 HTTP 响应都算「网络可达」；
- 模型接口：请求 Base URL，任何 HTTP 响应都算「网络可达」（401/404 说明网络通、配置待补）。
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from . import config

logger = logging.getLogger(__name__)

CHECK_TIMEOUT = 6.0
CACHE_TTL = 300.0
SLOW_MS = 8000  # 超过这个延迟就标记为「较慢」，即使能连上也提示

_CACHE: dict[str, Any] | None = None
_CACHE_AT = 0.0
_LOCK = threading.Lock()


def _short(exc: BaseException) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text[:120] if text else type(exc).__name__


def _error_message(exc: BaseException) -> str:
    if isinstance(exc, requests.exceptions.ProxyError):
        return "代理连接失败，请检查代理地址/端口"
    if isinstance(exc, requests.exceptions.Timeout):
        return "连接超时"
    if isinstance(exc, requests.exceptions.SSLError):
        return "TLS 握手失败（可能被网络干扰）"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "连接失败"
    if isinstance(exc, requests.exceptions.InvalidURL):
        return "地址格式不正确"
    return f"请求失败（{type(exc).__name__}）"


def _session(proxies: dict[str, str] | None) -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # 代理完全由显式配置决定，避免系统代理影响检测结果
    if proxies:
        session.proxies.update(proxies)
    session.headers.update({"User-Agent": "github-radar/0.1 (network-check)"})
    return session


def _probe(
    url: str,
    proxies: dict[str, str] | None,
    headers: dict[str, str] | None = None,
    timeout: float = CHECK_TIMEOUT,
) -> dict[str, Any]:
    started = time.time()
    session = _session(proxies)
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=False, headers=headers or {})
        return {
            "ok": True,
            "latency_ms": int((time.time() - started) * 1000),
            "status": resp.status_code,
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": int((time.time() - started) * 1000),
            "error": _short(exc),
            "message": _error_message(exc),
        }
    finally:
        session.close()


def _mark_slow(result: dict[str, Any], target: str) -> dict[str, Any]:
    """能连上但很慢时也提示：用户感知上这同样属于“网络不好”。"""
    if result.get("ok") and not result.get("warning") and result.get("latency_ms", 0) >= SLOW_MS:
        result["warning"] = True
        result["message"] = f"可连接，但较慢（{result['latency_ms']}ms）"
        result["hint"] = f"{target}响应很慢，国内网络可配置代理加速"
    return result


def _check_github() -> dict[str, Any]:
    """GitHub API 连通性；有 Token 用鉴权接口，避免无谓的匿名限流。"""
    proxies = config.radar_proxies()
    token = (config.GITHUB_TOKEN or "").strip()
    if token:
        result = _probe(
            "https://api.github.com/rate_limit",
            proxies,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
    else:
        result = _probe("https://api.github.com/zen", proxies)
    if not result["ok"]:
        result["message"] = f"GitHub API 不可达：{result.get('message', '连接失败')}"
        result["hint"] = "国内网络可能需要代理；可在设置里配置 RADAR_PROXY"
        return result
    status = result.get("status")
    if status == 401:
        result["message"] = "可连接，但 GitHub Token 无效（401）"
        result["warning"] = True
    elif status == 403:
        result["message"] = "可连接，但 GitHub API 被限流（403）"
        result["warning"] = True
    elif status and status >= 500:
        result["ok"] = False
        result["message"] = f"GitHub 服务异常（HTTP {status}）"
    else:
        result["message"] = "可连接"
    return _mark_slow(result, "GitHub API")


def _check_images() -> dict[str, Any]:
    """缩略图 CDN 连通性（国内最常见的卡点）。"""
    result = _probe("https://opengraph.githubassets.com/", config.radar_proxies())
    if result["ok"]:
        result["message"] = "可连接"
        if result.get("latency_ms", 0) >= SLOW_MS:
            result["message"] = f"可连接，但较慢（{result['latency_ms']}ms）"
            result["hint"] = "图片 CDN 较慢时预览图会先显示占位图；配置 RADAR_PROXY 可加速"
            result["warning"] = True
    else:
        result["message"] = f"图片 CDN 不可达：{result.get('message', '连接失败')}"
        result["hint"] = "国内网络常无法直连 GitHub 图片 CDN；可配置 RADAR_PROXY，或先接受雷达占位图"
    return result


def _check_llm() -> dict[str, Any]:
    base = (config.LLM_BASE_URL or "").strip()
    provider = config.LLM_PROVIDER
    if not base:
        return {
            "ok": False,
            "configured": False,
            "message": "未配置模型接口地址",
            "hint": "在设置页填写 Base URL 后再检测",
        }
    url = base.rstrip("/") + "/models"
    headers: dict[str, str] = {}
    if config.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
    result = _probe(url, config.llm_proxies(), headers=headers)
    result["configured"] = True
    if not result["ok"]:
        result["message"] = f"模型接口不可达：{result.get('message', '连接失败')}"
        if provider == "ollama":
            result["hint"] = "本地 Ollama 可能没有启动（ollama serve）"
        else:
            result["hint"] = "检查 Base URL / 网络；如模型在境外可配置 LLM_PROXY"
        return result
    status = result.get("status")
    result["message"] = f"可连接（{provider}，HTTP {status}）"
    if status == 401:
        result["message"] = f"可连接，但 {provider} API Key 无效（401）"
        result["warning"] = True
    return _mark_slow(result, "模型接口")


def _level(targets: dict[str, dict[str, Any]]) -> str:
    checked = [
        item
        for name, item in targets.items()
        if item.get("configured", True) and not item.get("skipped")
    ]
    failures = [item for item in checked if not item.get("ok")]
    warnings = [item for item in checked if item.get("ok") and item.get("warning")]
    if checked and not failures and not warnings:
        return "ok"
    if checked and len(failures) == len(checked):
        return "offline"
    return "degraded"


def _reset_cache() -> None:
    global _CACHE, _CACHE_AT
    with _LOCK:
        _CACHE = None
        _CACHE_AT = 0.0


def check_all(force: bool = False) -> dict[str, Any]:
    """返回三路网络状态；默认缓存 5 分钟。"""
    global _CACHE, _CACHE_AT
    now = time.time()
    with _LOCK:
        if not force and _CACHE is not None and now - _CACHE_AT < CACHE_TTL:
            cached = dict(_CACHE)
            cached["cached"] = True
            return cached

    started = time.time()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            "github": pool.submit(_check_github),
            "images": pool.submit(_check_images),
            "llm": pool.submit(_check_llm),
        }
        targets = {name: future.result() for name, future in futures.items()}

    result: dict[str, Any] = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_ms": int((time.time() - started) * 1000),
        "cached": False,
        "level": _level(targets),
        "targets": targets,
        "proxy": {
            "radar": config.mask_proxy(config.RADAR_PROXY) or "直连",
            "llm": config.mask_proxy(config.LLM_PROXY) or "直连",
            "system": config.system_proxy_summary() or "未设置",
        },
    }
    with _LOCK:
        _CACHE = result
        _CACHE_AT = time.time()
    logger.info(
        "网络检测完成：level=%s github=%s images=%s llm=%s",
        result["level"],
        targets["github"].get("ok"),
        targets["images"].get("ok"),
        targets["llm"].get("ok"),
    )
    return dict(result)
