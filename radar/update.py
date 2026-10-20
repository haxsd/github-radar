"""检查 GitHub Releases 是否有新版本。

只读取公开的 latest release，不下载、不安装。结果缓存 6 小时，设置页打开时
自动检查一次，用户也可以点“检查更新”强制刷新。
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from typing import Any

import requests

from . import __version__, config

GITHUB_REPO = "haxsd/github-radar"
LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
CACHE_TTL = 6 * 3600
REQUEST_TIMEOUT = 8.0

_CACHE: tuple[float, dict[str, Any]] | None = None
_CACHE_LOCK = threading.Lock()


class UpdateError(RuntimeError):
    pass


def _reset_cache() -> None:
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None


def parse_version(value: str | None) -> tuple[int, ...]:
    """v0.7.0 / 0.7.0-beta -> (0, 7, 0)。"""
    numbers = [int(part) for part in re.findall(r"\d+", value or "")]
    return tuple(numbers)


def is_newer(latest: str | None, current: str | None) -> bool:
    """比较版本；任一侧没有数字时返回 False，避免误报。"""
    left, right = parse_version(latest), parse_version(current)
    if not left or not right:
        return False
    size = max(len(left), len(right))
    return left + (0,) * (size - len(left)) > right + (0,) * (size - len(right))


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _release_url(data: dict[str, Any]) -> str:
    url = str(data.get("html_url") or "")
    # 只跳转到本仓库的 Release 页面，避免 API 数据异常时把用户带到别处
    if url.startswith(f"https://github.com/{GITHUB_REPO}/releases/"):
        return url
    return RELEASES_URL


def _fetch_latest() -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-radar-update-check",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (config.GITHUB_TOKEN or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    proxies = config.radar_proxies()

    def _get(use_auth: bool) -> requests.Response:
        request_headers = dict(headers)
        if not use_auth:
            request_headers.pop("Authorization", None)
        return requests.get(
            LATEST_API,
            headers=request_headers,
            proxies=proxies,
            timeout=REQUEST_TIMEOUT,
        )

    resp = _get(use_auth=bool(token))
    # Token 过期/无权限时，公开接口仍可匿名读取一次
    if resp.status_code == 401 and token:
        resp = _get(use_auth=False)
    if resp.status_code == 404:
        raise UpdateError("GitHub 上还没有发布版本")
    if resp.status_code in (403, 429):
        raise UpdateError("GitHub API 被限流，请稍后再试")
    if resp.status_code >= 400:
        raise UpdateError(f"GitHub 返回 HTTP {resp.status_code}")
    data = resp.json()
    if not isinstance(data, dict) or not data.get("tag_name"):
        raise UpdateError("GitHub 返回的版本信息不完整")
    return data


def check_latest(force: bool = False) -> dict[str, Any]:
    """返回检查结果；网络错误会以 ``ok=False`` 返回，不抛给调用方。"""
    global _CACHE
    now = time.time()
    with _CACHE_LOCK:
        if not force and _CACHE is not None and now < _CACHE[0]:
            result = dict(_CACHE[1])
            result["cached"] = True
            return result

    try:
        data = _fetch_latest()
        latest = str(data.get("tag_name") or "").lstrip("vV")
        result: dict[str, Any] = {
            "ok": True,
            "current": __version__,
            "latest": latest,
            "has_update": is_newer(latest, __version__),
            "url": _release_url(data),
            "name": str(data.get("name") or latest),
            "published_at": str(data.get("published_at") or ""),
            "checked_at": _now_iso(),
            "cached": False,
        }
        with _CACHE_LOCK:
            _CACHE = (time.time() + CACHE_TTL, dict(result))
        return result
    except Exception as exc:
        if isinstance(exc, requests.Timeout):
            message = "连接 GitHub 超时"
        elif isinstance(exc, requests.ConnectionError):
            message = "无法连接 GitHub，请检查网络或代理"
        elif isinstance(exc, UpdateError):
            message = str(exc)
        else:
            message = "检查更新失败：%s" % exc
        return {
            "ok": False,
            "current": __version__,
            "error": message,
            "checked_at": _now_iso(),
            "cached": False,
        }
