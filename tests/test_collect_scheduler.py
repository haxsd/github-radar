# -*- coding: utf-8 -*-
"""内置定时采集与更新事件出卡回归测试。"""

from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from radar import collect, config, db, feed, web

TZ = timezone(timedelta(hours=8))


class _TempConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self._orig = (config.DATA_DIR, config.DB_PATH, config.ENV_PATH)
        config.DATA_DIR = Path(self.tmp.name)
        config.DB_PATH = config.DATA_DIR / "radar.db"
        config.ENV_PATH = config.DATA_DIR / ".env"
        self.addCleanup(self._restore)

    def _restore(self):
        config.DATA_DIR, config.DB_PATH, config.ENV_PATH = self._orig
        config._load()

    def _db(self):
        conn = db.connect()
        db.init_db(conn)
        self.addCleanup(conn.close)
        return conn


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


class TestScheduledWaveDue(_TempConfigTestCase):
    def test_due_at_first_slot_after_last_success(self):
        self.assertTrue(
            collect.scheduled_wave_due(
                _at(24, 8, 1), "2026-10-24T00:05:00+08:00", None
            )
        )

    def test_not_due_when_current_slot_was_already_attempted(self):
        slot = collect.latest_scheduled_slot(_at(24, 8, 1))
        self.assertFalse(
            collect.scheduled_wave_due(
                _at(24, 8, 30),
                "2026-10-24T00:05:00+08:00",
                slot.isoformat(timespec="minutes"),
            )
        )

    def test_overdue_slot_is_caught_up_after_long_sleep(self):
        self.assertTrue(
            collect.scheduled_wave_due(
                _at(24, 11, 0), "2026-10-24T00:05:00+08:00", None
            )
        )

    def test_recent_success_skips_current_slot(self):
        self.assertFalse(
            collect.scheduled_wave_due(
                _at(24, 8, 20), "2026-10-24T08:10:00+08:00", None
            )
        )

    def test_recent_manual_collection_skips_nearby_slot(self):
        self.assertFalse(
            collect.scheduled_wave_due(
                _at(24, 8, 10), "2026-10-24T07:30:00+08:00", None
            )
        )


class TestRunDueWaveOnce(_TempConfigTestCase):
    def test_runs_and_records_attempt_for_translated_update_event(self):
        conn = self._db()
        db.meta_set(conn, "last_wave_at", "2026-10-24T00:05:00+08:00")
        conn.commit()
        calls = []
        with mock.patch.object(
            config, "github_token_status", return_value="env", create=True
        ):
            ran = collect.run_due_wave_once(
                now=_at(24, 8, 1), runner=lambda: calls.append("wave")
            )
        self.assertTrue(ran)
        self.assertEqual(calls, ["wave"])
        self.assertEqual(
            db.meta_get(conn, "scheduler_last_attempt_slot"),
            "2026-10-24T08:00+08:00",
        )
        self.assertEqual(db.meta_get(conn, "scheduler_last_result"), "ok")

    def test_skips_without_github_token(self):
        conn = self._db()
        db.meta_set(conn, "last_wave_at", "2026-10-24T00:05:00+08:00")
        conn.commit()
        calls = []
        with mock.patch.object(
            config, "github_token_status", return_value="missing", create=True
        ):
            ran = collect.run_due_wave_once(
                now=_at(24, 8, 1), runner=lambda: calls.append("wave")
            )
        self.assertFalse(ran)
        self.assertEqual(calls, [])

    def test_runner_exception_is_visible_as_scheduler_failure(self):
        conn = self._db()
        db.meta_set(conn, "last_wave_at", "2026-10-24T00:05:00+08:00")
        conn.commit()

        def boom():
            raise RuntimeError("scheduler-boom")

        with mock.patch.object(
            config, "github_token_status", return_value="env", create=True
        ):
            ran = collect.run_due_wave_once(now=_at(24, 8, 1), runner=boom)
        self.assertTrue(ran)
        self.assertEqual(db.meta_get(conn, "last_error_scope"), "scheduler")
        self.assertIn("scheduler-boom", db.meta_get(conn, "last_error_message") or "")
        self.assertEqual(db.meta_get(conn, "scheduler_last_result"), "error")


class TestSchedulerThread(unittest.TestCase):
    def tearDown(self):
        collect._SCHEDULER_THREAD = None

    def test_start_is_idempotent(self):
        entered = threading.Event()
        release = threading.Event()

        def loop(_poll_seconds):
            entered.set()
            release.wait(2)

        with mock.patch.object(collect, "_scheduler_loop", side_effect=loop):
            first = collect.start_scheduler()
            self.assertTrue(entered.wait(1), "调度线程应已启动")
            second = collect.start_scheduler()
        self.assertTrue(first)
        self.assertFalse(second)
        release.set()
        collect._SCHEDULER_THREAD.join(timeout=2)


class TestSchedulerIntegration(_TempConfigTestCase):
    def test_web_starts_collection_scheduler(self):
        with mock.patch.object(
            web.collect, "start_scheduler", return_value=True
        ) as start:
            web._start_collection_scheduler()
        start.assert_called_once_with()

    def test_stats_expose_scheduler_state(self):
        conn = self._db()
        db.meta_set(conn, "scheduler_last_attempt_at", "2026-10-24T08:00:01+08:00")
        db.meta_set(conn, "scheduler_last_result", "ok")
        conn.commit()
        stats = feed._unwrapped["stats"]()
        self.assertEqual(
            stats["scheduler_last_attempt_at"], "2026-10-24T08:00:01+08:00"
        )
        self.assertEqual(stats["scheduler_last_result"], "ok")

    def test_settings_page_renders_scheduler_result(self):
        conn = self._db()
        db.meta_set(conn, "scheduler_last_attempt_at", "2026-10-24T08:00:01+08:00")
        db.meta_set(conn, "scheduler_last_result", "ok")
        conn.commit()
        client = web.app.test_client()
        with mock.patch.object(
            config, "github_token_status", return_value="env", create=True
        ), mock.patch.object(
            web.startup, "supported", return_value=False
        ), mock.patch.object(
            web.startup, "enabled", return_value=False
        ):
            resp = client.get("/settings")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("2026-10-24 08:00", html)
        self.assertIn("成功", html)


class _FakeGitHub:
    def __init__(self, node):
        self.node = node

    def fetch_nodes(self, node_ids):
        return [self.node]

    def fetch_og_images(self, full_names):
        return {}


def _repo_item(translated: bool) -> dict:
    return {
        "node_id": "NODE-UPDATE",
        "full_name": "demo/update-event",
        "owner": {"login": "demo"},
        "name": "update-event",
        "html_url": "https://github.com/demo/update-event",
        "description": "Demo repo",
        "description_zh": "已经翻译好的项目" if translated else None,
        "summary_zh": "摘要" if translated else None,
        "points": "[]",
        "judgement": "值得用" if translated else None,
        "flags": "[]",
        "language": "Python",
        "license": {"spdx_id": "MIT"},
        "topics": ["demo"],
        "homepage": "",
        "stargazers_count": 100,
        "forks_count": 5,
        "open_issues_count": 0,
        "archived": False,
        "fork": False,
        "created_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "last_release_tag": "v1.0.0",
    }


def _update_node() -> dict:
    return {
        "id": "NODE-UPDATE",
        "stargazerCount": 160,
        "forkCount": 6,
        "pushedAt": "2026-10-24T00:00:00Z",
        "isArchived": False,
        "latestRelease": {"tagName": "v1.1.0", "publishedAt": "2026-10-24T00:00:00Z"},
    }


class TestUpdateEventsCardReady(_TempConfigTestCase):
    def test_translated_repo_update_events_are_ready_for_feed(self):
        conn = self._db()
        rid, _ = db.upsert_repo(conn, _repo_item(translated=True))
        conn.execute(
            "UPDATE repos SET last_release_tag='v1.0.0', description_zh=?,"
            " summary_zh=?, judgement=? WHERE id=?",
            ("已经翻译好的项目", "摘要", "值得用", rid),
        )
        conn.commit()
        collect.cmd_update(gh=_FakeGitHub(_update_node()), limit=10)
        rows = conn.execute(
            "SELECT kind, card_ready FROM events WHERE repo_id=? ORDER BY kind", (rid,)
        ).fetchall()
        self.assertEqual({r["kind"] for r in rows}, {"stars", "release"})
        self.assertTrue(all(r["card_ready"] == 1 for r in rows))

    def test_untranslated_update_events_wait_until_translation(self):
        conn = self._db()
        rid, _ = db.upsert_repo(conn, _repo_item(translated=False))
        conn.commit()
        collect.cmd_update(gh=_FakeGitHub(_update_node()), limit=10)
        rows = conn.execute(
            "SELECT card_ready FROM events WHERE repo_id=?", (rid,)
        ).fetchall()
        self.assertTrue(rows)
        self.assertTrue(all(r["card_ready"] == 0 for r in rows))
        db.set_translation(
            conn,
            rid,
            {
                "desc_zh": "中文简介",
                "summary_zh": "中文摘要",
                "points": ["要点"],
                "judgement": "值得用",
                "flags": [],
            },
        )
        conn.commit()
        ready = conn.execute(
            "SELECT COUNT(*) n FROM events WHERE repo_id=? AND card_ready=1", (rid,)
        ).fetchone()["n"]
        self.assertEqual(ready, len(rows))

    def test_migration_marks_existing_translated_events_ready(self):
        conn = self._db()
        rid, _ = db.upsert_repo(conn, _repo_item(translated=True))
        conn.execute(
            "UPDATE repos SET description_zh=?, summary_zh=?, judgement=? WHERE id=?",
            ("已经翻译好的项目", "摘要", "值得用", rid),
        )
        conn.execute(
            "INSERT INTO events(repo_id, kind, occurred_at, payload, card_ready)"
            " VALUES(?,?,?,?,0)",
            (rid, "stars", "2026-10-24T00:00:00+08:00", "{}"),
        )
        conn.execute("PRAGMA user_version=1")
        conn.commit()
        db.init_db(conn)
        ready = conn.execute(
            "SELECT card_ready FROM events WHERE repo_id=?", (rid,)
        ).fetchone()["card_ready"]
        self.assertEqual(ready, 1)


if __name__ == "__main__":
    unittest.main()
