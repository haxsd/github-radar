# -*- coding: utf-8 -*-
"""信息流卡片字段测试：未翻译项目也要带上原始 description。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from radar import config, db, feed


class TestCardFields(unittest.TestCase):
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

    def test_untranslated_card_keeps_original_description(self):
        conn = db.connect()
        try:
            db.init_db(conn)
            cur = conn.execute(
                """INSERT INTO repos
                   (full_name, owner, name, html_url, description, language,
                    created_at, first_seen_at, quality)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    "demo/english-only",
                    "demo",
                    "english-only",
                    "https://github.com/demo/english-only",
                    "An English-only description.",
                    "Python",
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                    0.5,
                ),
            )
            repo_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO events (repo_id, kind, occurred_at, payload, card_ready)"
                " VALUES (?,?,?,?,1)",
                (repo_id, "new", "2026-10-20T00:00:00+08:00", "{}"),
            )
            conn.commit()
            cards = feed.next_cards(mark_shown=False)
            self.assertEqual(len(cards), 1)
            self.assertIsNone(cards[0]["description_zh"])
            self.assertEqual(cards[0]["description"], "An English-only description.")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
