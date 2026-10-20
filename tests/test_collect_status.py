# -*- coding: utf-8 -*-
"""采集失败状态回显 + config.save_env 换行注入清洗测试。

安全约束：每个用例都把 config.DATA_DIR / DB_PATH / ENV_PATH 指向
tempfile.TemporaryDirectory()，tearDown 恢复原值并重新 config._load()，
同时 feed.invalidate_cache()；绝不写真实 data/radar.db 与真实 .env。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from radar import collect, config, db, feed


def _later_iso(iso: str, seconds: int = 60) -> str:
    """在给定 ISO 时间上再加一段时间（保持原时区格式）。"""
    return (datetime.fromisoformat(iso) + timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


class _TempConfigTestCase(unittest.TestCase):
    """把配置路径指到临时目录的公共基类。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)  # 先注册 -> 最后执行
        self._orig_paths = (config.DATA_DIR, config.DB_PATH, config.ENV_PATH)
        config.DATA_DIR = Path(self.tmp.name)
        config.DB_PATH = config.DATA_DIR / "radar.db"
        config.ENV_PATH = config.DATA_DIR / ".env"
        self.addCleanup(self._restore_config)  # 后注册 -> 先执行
        # 安全断言：测试期间绝不能指向真实 .env
        self.assertNotEqual(
            Path(config.ENV_PATH),
            Path(self._orig_paths[2]),
            "ENV_PATH 必须指向临时文件，禁止写真实 .env",
        )
        feed.invalidate_cache()

    def _restore_config(self):
        config.DATA_DIR, config.DB_PATH, config.ENV_PATH = self._orig_paths
        try:
            config._load()
        finally:
            feed.invalidate_cache()

    def _stats(self):
        # 绕过 TTL 缓存，拿数据库里的最新状态
        return feed._unwrapped["stats"]()


class TestCollectErrorStatus(_TempConfigTestCase):
    def test_failure_visible_then_cleared_by_newer_wave(self):
        collect._record_failure("wave", RuntimeError("boom"))

        stats = self._stats()
        self.assertIn("boom", str(stats.get("last_error")), "last_error 应包含异常信息 boom")
        self.assertEqual(stats.get("last_error_scope"), "wave", "失败作用域应为 wave")
        self.assertTrue(stats.get("last_error_at"), "last_error_at 不能为空")
        self.assertTrue(stats.get("error_active"), "刚失败后 error_active 应为 True")

        # 模拟之后成功跑完一波：last_wave_at 晚于 last_error_at
        later = _later_iso(str(stats["last_error_at"]))
        conn = db.connect()
        try:
            db.init_db(conn)
            db.meta_set(conn, "last_wave_at", later)
            conn.commit()
        finally:
            conn.close()
        feed.invalidate_cache()

        stats = self._stats()
        self.assertFalse(
            stats.get("error_active"),
            "last_wave_at 晚于 last_error_at 时 error_active 应为 False",
        )
        self.assertEqual(
            stats.get("last_wave_at"), later, "last_wave_at 应写入数据库并可读回"
        )

    def test_same_second_failure_is_still_active(self):
        """回归：last_wave_at（秒精度）与失败同秒时，红条不能因为字符串相等被吞掉。"""
        conn = db.connect()
        try:
            db.init_db(conn)
            db.meta_set(conn, "last_wave_at", db.now_iso())
            conn.commit()
        finally:
            conn.close()
        feed.invalidate_cache()

        collect._record_failure("translate", RuntimeError("same-second-boom"))

        stats = self._stats()
        self.assertEqual(stats.get("last_error_scope"), "translate")
        self.assertIn("same-second-boom", str(stats.get("last_error")))
        self.assertTrue(
            stats.get("error_active"),
            "同一秒内的失败也必须判定为未恢复（last_error_at 用毫秒精度）",
        )


class TestSaveEnvSanitization(_TempConfigTestCase):
    def test_newline_value_cannot_inject_env_key(self):
        config.ENV_PATH.write_text("# test\n", encoding="utf-8")

        config.save_env({"LLM_MODEL": "bad\nEVIL=1"})

        text = config.ENV_PATH.read_text(encoding="utf-8")
        keys = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            keys.append(stripped.split("=", 1)[0].strip())

        self.assertIn("LLM_MODEL", keys, "LLM_MODEL 应写入临时 .env")
        self.assertNotIn(
            "EVIL",
            keys,
            f"换行值不得注入出独立键 EVIL；实际 .env 内容：{text!r}",
        )

        # 原文件仍应能被 config._load() 正常解析（值已清洗成单行）
        config._load()
        self.assertIsInstance(config.LLM_MODEL, str)
        self.assertNotIn("\n", config.LLM_MODEL, "LLM_MODEL 不应包含换行")


class _FakeGitHub:
    """绕过真实 GitHub() 构造，只返回一个仓库节点。"""

    def __init__(self, node: dict):
        self.node = node

    def fetch_nodes(self, node_ids):
        return [self.node]


class TestUpdateCreatesSchema(_TempConfigTestCase):
    def test_update_on_fresh_db_initializes_schema(self):
        self.assertFalse(config.DB_PATH.exists())
        events = collect.cmd_update(gh=_FakeGitHub({}), limit=10)
        self.assertEqual(events, 0)
        self.assertTrue(config.DB_PATH.exists(), "update 应自动建表，而不是报表不存在")


class TestLegacyEventTimezone(unittest.TestCase):
    def test_utc_event_time_is_normalized_once(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            originals = (config.DATA_DIR, config.DB_PATH, config.ENV_PATH)
            config.DATA_DIR = Path(tmp)
            config.DB_PATH = config.DATA_DIR / "radar.db"
            config.ENV_PATH = config.DATA_DIR / ".env"
            conn = db.connect()
            try:
                db.init_db(conn)
                conn.execute("DELETE FROM meta WHERE key='event_tz_local_v1'")
                conn.execute("PRAGMA user_version=0")
                conn.execute(
                    "INSERT INTO events (repo_id, kind, occurred_at, payload) VALUES (?,?,?,?)",
                    (1, "release", "2026-10-20T00:00:00Z", "{}"),
                )
                conn.commit()
                db.init_db(conn)
                ts = conn.execute("SELECT occurred_at FROM events").fetchone()["occurred_at"]
                self.assertNotIn("Z", ts)
                self.assertIsNotNone(datetime.fromisoformat(ts).utcoffset())
                self.assertEqual(
                    db.meta_get(conn, "event_tz_local_v1"), "1", "迁移标记只应写一次"
                )
            finally:
                conn.close()
                config.DATA_DIR, config.DB_PATH, config.ENV_PATH = originals
                config._load()


class TestUpdateFailureRecorded(_TempConfigTestCase):
    def test_db_error_records_update_scope(self):
        conn = db.connect()
        try:
            db.init_db(conn)
            db.upsert_repo(
                conn,
                {
                    "node_id": "NODE1",
                    "full_name": "demo/update-failure",
                    "owner": {"login": "demo"},
                    "name": "update-failure",
                    "html_url": "https://github.com/demo/update-failure",
                    "description": "demo",
                    "language": "Python",
                    "license": {"spdx_id": "MIT"},
                    "topics": [],
                    "homepage": "",
                    "stargazers_count": 10,
                    "forks_count": 1,
                    "open_issues_count": 0,
                    "archived": False,
                    "fork": False,
                    "created_at": "2026-01-01T00:00:00Z",
                    "pushed_at": "2026-01-01T00:00:00Z",
                },
            )
            conn.commit()
        finally:
            conn.close()

        fake = _FakeGitHub(
            {
                "id": "NODE1",
                "stargazerCount": 11,
                "forkCount": 1,
                "pushedAt": "2026-01-02T00:00:00Z",
                "isArchived": False,
                "latestRelease": None,
            }
        )
        with mock.patch(
            "radar.collect.db.add_snapshot", side_effect=RuntimeError("boom-update")
        ):
            with self.assertRaises(RuntimeError):
                collect.cmd_update(gh=fake, limit=10)

        stats = self._stats()
        self.assertIn("boom-update", str(stats.get("last_error")))
        self.assertEqual(stats.get("last_error_scope"), "update")
        self.assertTrue(stats.get("error_active"))


class TestTranslateStageRecorded(_TempConfigTestCase):
    def _conn(self):
        conn = db.connect()
        db.init_db(conn)
        self.addCleanup(conn.close)
        return conn

    def test_source_mode_popen_error_records_scope(self):
        conn = self._conn()
        with mock.patch("subprocess.Popen", side_effect=RuntimeError("boom-popen")):
            done = collect._translate_stage(conn, limit=1)
        self.assertEqual(done, 0)
        stats = self._stats()
        self.assertIn("boom-popen", str(stats.get("last_error")))
        self.assertEqual(stats.get("last_error_scope"), "translate")

    def test_frozen_mode_error_records_scope(self):
        conn = self._conn()
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch(
            "radar.collect.llm.translate_pending",
            side_effect=RuntimeError("boom-translate"),
        ):
            done = collect._translate_stage(conn, limit=1)
        self.assertEqual(done, 0)
        stats = self._stats()
        self.assertIn("boom-translate", str(stats.get("last_error")))
        self.assertEqual(stats.get("last_error_scope"), "translate")


if __name__ == "__main__":
    unittest.main()
