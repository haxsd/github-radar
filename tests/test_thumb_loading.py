# -*- coding: utf-8 -*-
"""预览图渐进加载测试：/thumb 不得阻塞等待远端下载，状态接口负责渐进替换。

全部离线：远端图片下载通过 mock 掉 _generate_thumb / 线程池 submit 来隔离，
不访问 GitHub 图片 CDN；数据库/缓存目录全部用临时目录，不碰真实 data/。
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

from radar import config, db, feed, web

SAFE_OG = "https://opengraph.githubassets.com/hash/demo/repo"


class _TempThumbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self._orig_paths = (config.DATA_DIR, config.DB_PATH, config.ENV_PATH)
        self._orig_thumb_dir = web.THUMB_DIR
        config.DATA_DIR = Path(self.tmp.name)
        config.DB_PATH = config.DATA_DIR / "radar.db"
        config.ENV_PATH = config.DATA_DIR / ".env"
        web.THUMB_DIR = config.DATA_DIR / "thumbs"
        self.addCleanup(self._restore)
        feed.invalidate_cache()
        with web._THUMB_LOCK:
            web._THUMB_PENDING.clear()
            web._THUMB_QUEUED.clear()
        with web._THUMB_RATE_LOCK:
            web._THUMB_NEXT_SLOT = 0.0
            web._THUMB_COOLDOWN_UNTIL = 0.0
            web._THUMB_429_TIMES.clear()
            web._THUMB_RETRY_AFTER.clear()
            web._THUMB_LAST_ON_DEMAND = 0.0
        self.client = web.app.test_client()

    def _restore(self):
        config.DATA_DIR, config.DB_PATH, config.ENV_PATH = self._orig_paths
        web.THUMB_DIR = self._orig_thumb_dir
        with web._THUMB_LOCK:
            web._THUMB_PENDING.clear()
            web._THUMB_QUEUED.clear()
        with web._THUMB_RATE_LOCK:
            web._THUMB_NEXT_SLOT = 0.0
            web._THUMB_COOLDOWN_UNTIL = 0.0
            web._THUMB_429_TIMES.clear()
            web._THUMB_RETRY_AFTER.clear()
            web._THUMB_LAST_ON_DEMAND = 0.0
        config._load()
        feed.invalidate_cache()

    def _insert_repo(self, og: str | None) -> int:
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
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()


class TestThumbEndpointNonBlocking(_TempThumbTestCase):
    def test_cache_miss_returns_placeholder_immediately(self):
        rid = self._insert_repo(SAFE_OG)
        with mock.patch.object(web, "_generate_thumb") as generate:
            started = time.time()
            resp = self.client.get(f"/thumb/{rid}?w=240")
            elapsed = time.time() - started
        self.assertEqual(resp.status_code, 200)
        self.assertIn("image/jpeg", resp.headers.get("Content-Type", ""))
        self.assertLess(elapsed, 1.0, "/thumb 缓存未命中不得同步等待图片下载")
        self.assertIn("no-store", resp.headers.get("Cache-Control", ""))
        self.assertEqual(resp.headers.get("X-Thumb-State"), "placeholder")
        # 请求返回后，后台任务应被调度执行
        deadline = time.time() + 2.0
        while not generate.called and time.time() < deadline:
            time.sleep(0.02)
        self.assertTrue(generate.called, "缓存未命中时应把生成任务丢到后台线程池")

    def test_cache_hit_returns_cached_file(self):
        rid = self._insert_repo(SAFE_OG)
        cache = web._thumb_path(rid, 240)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(b"\xff\xd8cached-jpeg")
        with mock.patch.object(web, "_generate_thumb") as generate:
            resp = self.client.get(f"/thumb/{rid}?w=240")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(), b"\xff\xd8cached-jpeg")
        generate.assert_not_called()

    def test_missing_repo_404(self):
        resp = self.client.get("/thumb/999999?w=240")
        self.assertEqual(resp.status_code, 404)

    def test_unsafe_og_image_never_scheduled(self):
        rid = self._insert_repo("http://127.0.0.1:1/evil.png")
        with mock.patch.object(web._THUMB_EXECUTOR, "submit") as submit:
            resp = self.client.get(f"/thumb/{rid}?w=240")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("image/jpeg", resp.headers.get("Content-Type", ""))
        submit.assert_not_called()


class TestThumbStatusEndpoint(_TempThumbTestCase):
    def test_status_reports_ready_and_schedules_pending(self):
        rid = self._insert_repo(SAFE_OG)
        with mock.patch.object(web, "_schedule_thumb") as schedule:
            resp = self.client.get(f"/api/thumbs/status?w=240&ids={rid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["ready"], [])
        self.assertEqual(data["width"], 240)
        schedule.assert_called_once()

        cache = web._thumb_path(rid, 240)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(b"\xff\xd8ready")
        with mock.patch.object(web, "_schedule_thumb") as schedule:
            resp = self.client.get(f"/api/thumbs/status?w=240&ids={rid},999999")
        data = resp.get_json()
        self.assertEqual(data["ready"], [rid])
        # 已就绪的不再调度；不存在的 id 也不应报错
        schedule.assert_not_called()

    def test_status_ignores_bad_ids(self):
        resp = self.client.get("/api/thumbs/status?w=240&ids=abc,,1x")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["ready"], [])


class TestScheduleThumbGuards(_TempThumbTestCase):
    def test_schedule_thumb_rejects_unsafe_and_dedupes(self):
        key = (1, 240)
        with mock.patch.object(web._THUMB_EXECUTOR, "submit") as submit:
            web._schedule_thumb(1, 240, "http://127.0.0.1/x", "demo")
            submit.assert_not_called()
            web._schedule_thumb(1, 240, SAFE_OG, "demo")
            web._schedule_thumb(1, 240, SAFE_OG, "demo")
            self.assertEqual(submit.call_count, 1, "同一张图在队列中只应提交一次")
        with web._THUMB_LOCK:
            web._THUMB_QUEUED.discard(key)


class TestThumbGeneration(_TempThumbTestCase):
    def test_one_download_generates_standard_widths(self):
        import io

        from PIL import Image

        rid = self._insert_repo(SAFE_OG)
        buffer = io.BytesIO()
        Image.new("RGB", (1200, 630), (30, 40, 50)).save(buffer, "PNG")
        with mock.patch.object(web, "_fetch_image_bytes", return_value=buffer.getvalue()):
            web._generate_thumb(rid, 240, SAFE_OG, "demo")
        for width in (240, 480, 960):
            path = web._thumb_path(rid, width)
            self.assertTrue(path.exists(), f"一次下载应同时生成 {width} 宽度缩略图")
            with Image.open(path) as img:
                self.assertEqual(img.width, width)


class TestThumbRateLimiting(_TempThumbTestCase):
    def test_wait_slot_spaces_requests(self):
        with mock.patch.object(web, "THUMB_MIN_INTERVAL", 0.05):
            started = time.time()
            self.assertTrue(web._thumb_wait_slot())
            self.assertTrue(web._thumb_wait_slot())
            elapsed = time.time() - started
        self.assertGreaterEqual(elapsed, 0.04, "下载时隙之间应有最小间隔")

    def test_downloads_are_serialized(self):
        import io
        import threading

        from PIL import Image

        rid1 = self._insert_repo(SAFE_OG)
        rid2 = self._insert_repo(SAFE_OG)
        buffer = io.BytesIO()
        Image.new("RGB", (1200, 630), (1, 2, 3)).save(buffer, "PNG")
        png = buffer.getvalue()
        active = {"now": 0, "max": 0}
        state_lock = threading.Lock()

        def slow_fetch(url, timeout=12.0):
            with state_lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            time.sleep(0.05)
            with state_lock:
                active["now"] -= 1
            return png

        workers = [
            threading.Thread(target=web._generate_thumb, args=(rid1, 240, SAFE_OG, "demo")),
            threading.Thread(target=web._generate_thumb, args=(rid2, 240, SAFE_OG, "demo")),
        ]
        with mock.patch.object(web, "_fetch_image_bytes", side_effect=slow_fetch):
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
        self.assertEqual(active["max"], 1, "远端下载必须串行，并发会触发 CDN 429")

    def test_429_backs_off_single_repo_and_blocks_it(self):
        rid = self._insert_repo(SAFE_OG)
        error = requests.HTTPError("429 Too Many Requests")
        error.response = mock.Mock(status_code=429)
        with mock.patch.object(web, "_fetch_image_bytes", side_effect=error):
            web._generate_thumb(rid, 240, SAFE_OG, "demo")
        self.assertGreater(
            web._thumb_retry_remaining(rid, 240), 0, "单张图 429 后应退避一段时间"
        )
        self.assertFalse(web._thumb_cooling_down(), "单次 429 不应触发全局冷却")
        with mock.patch.object(web._THUMB_EXECUTOR, "submit") as submit:
            web._schedule_thumb(rid, 240, SAFE_OG, "demo")
            submit.assert_not_called()
        self.assertFalse(web._thumb_path(rid, 240).exists())
        with web._THUMB_LOCK:
            web._THUMB_QUEUED.discard((rid, 240))

    def test_burst_429_triggers_short_global_cooldown(self):
        for i in range(web.THUMB_429_BURST_LIMIT):
            web._thumb_note_429(9000 + i, 240)
        self.assertTrue(web._thumb_cooling_down(), "短时间大量 429 应触发全局冷却")
        with mock.patch.object(web._THUMB_EXECUTOR, "submit") as submit:
            web._schedule_thumb(1, 240, SAFE_OG, "demo")
            submit.assert_not_called()


class TestTemplatesUseProgressiveThumbs(_TempThumbTestCase):
    def test_feed_and_base_assets_mark_images(self):
        conn = db.connect()
        db.init_db(conn)
        conn.close()
        html = self.client.get("/").get_data(as_text=True)
        # 渐进加载逻辑在 P2 重构后拆到 static/js，HTML 只负责引用
        self.assertIn("js/feed.js", html)
        self.assertIn("js/base.js", html)
        feed_js = (web.__file__ and Path(web.__file__).resolve().parent / "static" / "js" / "feed.js")
        base_js = feed_js.parent / "base.js"
        self.assertIn("data-thumb-repo", feed_js.read_text(encoding="utf-8"),
                      "feed 缩略图应带 data-thumb-repo 供渐进替换")
        self.assertIn("/api/thumbs/status", base_js.read_text(encoding="utf-8"),
                      "base 脚本应包含缩略图状态轮询")


if __name__ == "__main__":
    unittest.main()
