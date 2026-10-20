# -*- coding: utf-8 -*-
"""预览图缓存统计与预下载接口测试（全部离线，使用临时数据库/缓存目录）。"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from radar import config, db, feed, web


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self._orig = (config.DATA_DIR, config.DB_PATH, config.ENV_PATH)
        self._orig_thumb = web.THUMB_DIR
        config.DATA_DIR = Path(self.tmp.name)
        config.DB_PATH = config.DATA_DIR / "radar.db"
        config.ENV_PATH = config.DATA_DIR / ".env"
        web.THUMB_DIR = config.DATA_DIR / "thumbs"
        web.THUMB_DIR.mkdir(parents=True, exist_ok=True)
        feed.invalidate_cache()
        with web._PREFETCH_LOCK:
            web._PREFETCH_STATE.update(
                running=False, done=0, saved=0, failed=0, total=0, started_at="", finished_at="", error=""
            )
        self.addCleanup(self._restore)
        self.client = web.app.test_client()

    def _restore(self):
        config.DATA_DIR, config.DB_PATH, config.ENV_PATH = self._orig
        web.THUMB_DIR = self._orig_thumb
        with web._PREFETCH_LOCK:
            web._PREFETCH_STATE.update(
                running=False, done=0, saved=0, failed=0, total=0, started_at="", finished_at="", error=""
            )
        config._load()
        feed.invalidate_cache()

    def _insert(self, og: str | None = "https://opengraph.githubassets.com/x/demo/repo"):
        conn = db.connect()
        try:
            db.init_db(conn)
            cur = conn.execute(
                """INSERT INTO repos
                   (full_name, owner, name, html_url, created_at, first_seen_at, og_image)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    f"demo/repo-{time.time_ns()}",
                    "demo",
                    "repo",
                    "https://github.com/demo/repo",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                    og,
                ),
            )
            repo_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO events (repo_id, kind, occurred_at, payload, card_ready) VALUES (?,?,?,?,1)",
                (repo_id, "new", "2026-10-20T00:00:00+08:00", "{}"),
            )
            conn.commit()
            return repo_id
        finally:
            conn.close()

    def _cache_file(self, repo_id: int, width: int = 240) -> None:
        (web.THUMB_DIR / f"{repo_id}_{width}.jpg").write_bytes(b"jpeg")


class TestCacheStats(_Base):
    def test_cache_stats_excludes_placeholder(self):
        a = self._insert()
        self._insert()
        self._insert(og=None)  # 没有 og_image，不应计入
        self._cache_file(a)
        (web.THUMB_DIR / "_placeholder_240.jpg").write_bytes(b"p")
        stats = web._thumb_cache_stats()
        self.assertEqual(stats["repos_with_image"], 2)
        self.assertEqual(stats["cached"], 1)

    def test_prefetch_candidates_skip_cached(self):
        a = self._insert()
        b = self._insert()
        self._cache_file(a)
        items = web._thumb_prefetch_candidates(10)
        ids = {item["id"] for item in items}
        self.assertNotIn(a, ids)
        self.assertIn(b, ids)


class TestPrefetchEndpoint(_Base):
    def test_cache_endpoint(self):
        self._insert()
        resp = self.client.get("/api/thumbs/cache")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("cache", data)
        self.assertIn("prefetch", data)
        self.assertFalse(data["prefetch"]["running"])

    def test_prefetch_with_nothing_to_do(self):
        self._insert()
        with mock.patch.object(web, "_thumb_prefetch_candidates", return_value=[]):
            resp = self.client.post(
                "/api/thumbs/prefetch",
                json={"limit": 10},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 0)

    def test_prefetch_starts_background_worker(self):
        items = [{"id": 1, "og_image": "https://opengraph.githubassets.com/x", "owner": "demo"}]
        self._cache_file(1)  # 已缓存，worker 会立即成功，不会真的下载
        with mock.patch.object(
            web, "_thumb_prefetch_candidates", return_value=items
        ), mock.patch.object(web, "_generate_thumb"):
            resp = self.client.post(
                "/api/thumbs/prefetch",
                json={"limit": 10},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.get_json()["ok"])
            for _ in range(100):
                if not web._prefetch_snapshot()["running"]:
                    break
                time.sleep(0.02)
        self.assertFalse(web._prefetch_snapshot()["running"])

    def test_remote_prefetch_requires_admin_token(self):
        resp = self.client.post(
            "/api/thumbs/prefetch",
            json={"limit": 10},
            environ_base={"REMOTE_ADDR": "192.168.1.20"},
        )
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
