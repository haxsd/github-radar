"""GitHub API 客户端：搜索、批量状态查询。"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any, Iterator

import requests

from . import config

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or config.resolve_github_token()
        self.session = requests.Session()
        # 显式配置的 RADAR_PROXY 优先；未配置时保持 requests 默认（沿用系统 HTTP(S)_PROXY 环境变量）
        proxies = config.radar_proxies()
        if proxies:
            self.session.proxies.update(proxies)
            self.session.trust_env = False
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "github-radar/0.1",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        self._last_search = 0.0

    # ---------- 基础请求 ----------
    def _request(self, method: str, url: str, **kw: Any) -> requests.Response | None:
        for attempt in range(4):
            try:
                resp = self.session.request(method, url, timeout=40, **kw)
            except requests.RequestException as exc:
                # 连接失败/超时也重试；之前只重试 HTTP 状态码，网络一抖整波采集就失败
                if attempt == 3:
                    raise GitHubError(f"网络请求失败（重试耗尽）: {url}: {exc}") from exc
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code in (403, 429):
                remaining = resp.headers.get("X-RateLimit-Remaining")
                reset = resp.headers.get("X-RateLimit-Reset")
                if remaining == "0" and reset:
                    wait = max(5, int(reset) - int(time.time()) + 2)
                    time.sleep(min(wait, 70))
                    continue
                time.sleep(5 * (attempt + 1))
                continue
            if resp.status_code >= 500:
                time.sleep(3 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise GitHubError(f"{resp.status_code} {resp.url}: {resp.text[:300]}")
            return resp
        raise GitHubError(f"请求失败（重试耗尽）: {url}")

    def fetch_og_images(self, full_names: list[str]) -> dict[str, str]:
        """批量取仓库的社交预览图（openGraphImageUrl），100 个一批。"""
        out: dict[str, str] = {}
        for i in range(0, len(full_names), 100):
            chunk = full_names[i : i + 100]
            parts = []
            for idx, fn in enumerate(chunk):
                if "/" not in fn:
                    continue
                owner, name = fn.split("/", 1)
                owner = owner.replace('"', "")
                name = name.replace('"', "")
                parts.append(
                    f'r{idx}: repository(owner: "{owner}", name: "{name}") '
                    "{ nameWithOwner openGraphImageUrl }"
                )
            if not parts:
                continue
            resp = self._request("POST", GRAPHQL, json={"query": "query {" + " ".join(parts) + "}"})
            if not resp:
                continue
            data = (resp.json() or {}).get("data") or {}
            for idx, fn in enumerate(chunk):
                node = data.get(f"r{idx}")
                if node and node.get("openGraphImageUrl"):
                    out[node["nameWithOwner"]] = node["openGraphImageUrl"]
            time.sleep(0.3)
        return out

    def rate_limit(self) -> dict[str, Any]:
        resp = self._request("GET", f"{API}/rate_limit")
        return (resp.json() if resp else {}).get("resources", {})

    # ---------- 搜索 ----------
    def _search_gate(self) -> None:
        """搜索接口 30 次/分钟，做简单限速。"""
        gap = 2.2 - (time.time() - self._last_search)
        if gap > 0:
            time.sleep(gap)
        self._last_search = time.time()

    def search(
        self,
        q: str,
        per_page: int = 100,
        max_pages: int = 10,
        sort: str = "stars",
        order: str = "desc",
    ) -> Iterator[dict[str, Any]]:
        for page in range(1, max_pages + 1):
            self._search_gate()
            resp = self._request(
                "GET",
                f"{API}/search/repositories",
                params={"q": q, "per_page": per_page, "page": page, "sort": sort, "order": order},
            )
            if resp is None:
                return
            data = resp.json()
            items = data.get("items") or []
            yield from items
            total = data.get("total_count") or 0
            if len(items) < per_page or page * per_page >= total:
                return

    def search_created_between(self, start: date, end: date) -> Iterator[dict[str, Any]]:
        """创建时间在 [start, end] 且达标活跃的仓库。"""
        active = (date.today() - timedelta(days=config.ACTIVE_DAYS)).isoformat()
        q = (
            f"stars:>{config.MIN_STARS} pushed:>{active} "
            f"created:{start.isoformat()}..{end.isoformat()}"
        )
        return self.search(q)

    # ---------- 批量状态（GraphQL）----------
    def fetch_nodes(self, node_ids: list[str]) -> list[dict[str, Any]]:
        """一次最多 100 个仓库节点，取最新状态。"""
        if not node_ids:
            return []
        query = """
        query($ids: [ID!]!) {
          nodes(ids: $ids) {
            ... on Repository {
              id
              nameWithOwner
              stargazerCount
              forkCount
              pushedAt
              isArchived
              latestRelease { tagName publishedAt }
            }
          }
        }
        """
        resp = self._request(
            "POST", GRAPHQL, json={"query": query, "variables": {"ids": node_ids[:100]}}
        )
        if resp is None:
            return []
        data = resp.json()
        nodes = [n for n in (data.get("data") or {}).get("nodes") or [] if n]
        errors = data.get("errors") or []
        if errors:
            # 仓库被删除/转移后节点会 NOT_FOUND：只跳过这些，不让整批更新失败
            fatal = [e for e in errors if e.get("type") != "NOT_FOUND"]
            if fatal:
                raise GitHubError(f"GraphQL: {fatal}")
        return nodes
