# -*- coding: utf-8 -*-
"""示例数据载入/清理测试：reset 不能留下 seen/saves 孤儿行。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from radar import config, db, demo, feed


class _TempDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self._orig = (config.DATA_DIR, config.DB_PATH, config.ENV_PATH)
        config.DATA_DIR = Path(self.tmp.name)
        config.DB_PATH = config.DATA_DIR / "radar.db"
        config.ENV_PATH = config.DATA_DIR / ".env"
        self.addCleanup(self._restore)
        feed.invalidate_cache()

    def _restore(self):
        config.DATA_DIR, config.DB_PATH, config.ENV_PATH = self._orig
        config._load()
        feed.invalidate_cache()

    def test_reset_removes_user_rows(self):
        conn = db.connect()
        try:
            db.init_db(conn)
            demo.load_demo(conn)
            repo_id = conn.execute(
                "SELECT id FROM repos WHERE full_name=?", (demo.load_items()[0]["full_name"],)
            ).fetchone()["id"]
            db.mark_seen(conn, repo_id, "skip")
            db.add_save(conn, repo_id, "demo note")
            conn.commit()

            removed = demo.reset_demo(conn)
            self.assertGreaterEqual(removed, 1)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) c FROM seen WHERE repo_id=?", (repo_id,)).fetchone()["c"],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) c FROM saves WHERE repo_id=?", (repo_id,)).fetchone()["c"],
                0,
            )
        finally:
            conn.close()

    def test_demo_quality_is_normalized(self):
        conn = db.connect()
        try:
            db.init_db(conn)
            demo.load_demo(conn)
            row = conn.execute("SELECT quality FROM repos LIMIT 1").fetchone()
            self.assertIsNotNone(row)
            self.assertGreater(row["quality"], 0)
            self.assertLessEqual(row["quality"], 1.0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
