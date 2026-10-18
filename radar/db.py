"""SQLite 存储层：仓库 / 快照 / 事件 / 已读 / 收藏。"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from typing import Any

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
  id            INTEGER PRIMARY KEY,
  node_id       TEXT,
  full_name     TEXT UNIQUE NOT NULL,
  owner         TEXT,
  name          TEXT,
  html_url      TEXT,
  description   TEXT,
  description_zh TEXT,
  summary_zh    TEXT,
  points        TEXT,
  judgement     TEXT,
  flags         TEXT,
  language      TEXT,
  license       TEXT,
  topics        TEXT,
  homepage      TEXT,
  stars         INTEGER DEFAULT 0,
  forks         INTEGER DEFAULT 0,
  open_issues   INTEGER DEFAULT 0,
  archived      INTEGER DEFAULT 0,
  is_fork       INTEGER DEFAULT 0,
  is_chinese    INTEGER DEFAULT 0,
  quality       REAL DEFAULT 0,
  created_at    TEXT,
  pushed_at     TEXT,
  last_release_tag TEXT,
  hidden        INTEGER DEFAULT 0,
  hidden_reason TEXT,
  og_image      TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
  repo_id     INTEGER NOT NULL,
  captured_on TEXT NOT NULL,
  stars       INTEGER,
  forks       INTEGER,
  open_issues INTEGER,
  PRIMARY KEY (repo_id, captured_on)
);

CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id     INTEGER NOT NULL,
  kind        TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  payload     TEXT,
  card_ready  INTEGER DEFAULT 0,
  UNIQUE(repo_id, kind, occurred_at)
);

CREATE TABLE IF NOT EXISTS seen (
  repo_id  INTEGER NOT NULL,
  action   TEXT NOT NULL,
  acted_at TEXT NOT NULL,
  PRIMARY KEY (repo_id, action)
);

CREATE TABLE IF NOT EXISTS saves (
  repo_id  INTEGER PRIMARY KEY,
  note     TEXT,
  saved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repo_tags (
  repo_id INTEGER NOT NULL,
  tag     TEXT NOT NULL,
  kind    TEXT NOT NULL,
  PRIMARY KEY (repo_id, tag)
);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ready ON events(card_ready, occurred_at);
CREATE INDEX IF NOT EXISTS idx_repos_pushed ON repos(pushed_at);
CREATE INDEX IF NOT EXISTS idx_repo_tags_tag ON repo_tags(tag);
CREATE INDEX IF NOT EXISTS idx_repo_tags_kind ON repo_tags(kind);
"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # 采集进程写入时，网页端的保存/跳过要能等一会儿而不是直接报 locked
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or connect()
    conn.executescript(SCHEMA)
    # 老库自动补列
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(repos)").fetchall()}
    if "points" not in cols:
        conn.execute("ALTER TABLE repos ADD COLUMN points TEXT")
    if "hidden" not in cols:
        conn.execute("ALTER TABLE repos ADD COLUMN hidden INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE repos ADD COLUMN hidden_reason TEXT")
    if "og_image" not in cols:
        conn.execute("ALTER TABLE repos ADD COLUMN og_image TEXT")
    conn.commit()
    if own:
        conn.close()


# ---------------- meta ----------------

def meta_get(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# ---------------- repos ----------------

def compute_quality(item: dict[str, Any]) -> float:
    """粗略质量分 0~1：星数为主，文档完整度与 license 加分。"""
    stars = item.get("stargazers_count") or 0
    q = min(1.0, math.log10(stars + 1) / 5.0)
    if item.get("description"):
        q += 0.05
    lic = (item.get("license") or {}).get("spdx_id")
    if lic and lic != "NOASSERTION":
        q += 0.05
    if item.get("topics"):
        q += 0.05
    return round(min(q, 1.0), 3)


def _item_row(item: dict[str, Any], now: str) -> dict[str, Any]:
    return {
        "node_id": item.get("node_id"),
        "full_name": item["full_name"],
        "owner": (item.get("owner") or {}).get("login"),
        "name": item.get("name"),
        "html_url": item.get("html_url"),
        "description": item.get("description"),
        "language": item.get("language"),
        "license": (item.get("license") or {}).get("spdx_id"),
        "topics": json.dumps(item.get("topics") or [], ensure_ascii=False),
        "homepage": item.get("homepage"),
        "stars": item.get("stargazers_count") or 0,
        "forks": item.get("forks_count") or 0,
        "open_issues": item.get("open_issues_count") or 0,
        "archived": 1 if item.get("archived") else 0,
        "is_fork": 1 if item.get("fork") else 0,
        "quality": compute_quality(item),
        "created_at": item.get("created_at"),
        "pushed_at": item.get("pushed_at"),
        "last_seen_at": now,
    }


def upsert_repo(conn: sqlite3.Connection, item: dict[str, Any]) -> tuple[int, bool]:
    """写入/更新仓库，返回 (repo_id, 是否首次收录)。"""
    now = now_iso()
    row = conn.execute("SELECT id FROM repos WHERE full_name=?", (item["full_name"],)).fetchone()
    data = _item_row(item, now)
    if row:
        rid = row["id"]
        sets = ", ".join(f"{k}=:{k}" for k in data)
        conn.execute(f"UPDATE repos SET {sets} WHERE id=:id", {**data, "id": rid})
        return rid, False
    data["first_seen_at"] = now
    cols = ", ".join(data)
    ph = ", ".join(f":{k}" for k in data)
    cur = conn.execute(f"INSERT INTO repos ({cols}) VALUES ({ph})", data)
    return int(cur.lastrowid), True


def set_translation(conn: sqlite3.Connection, repo_id: int, data: dict[str, Any]) -> None:
    conn.execute(
        """UPDATE repos SET description_zh=?, summary_zh=?, judgement=?, flags=?, is_chinese=?,
                            points=?
           WHERE id=?""",
        (
            data.get("desc_zh"),
            data.get("summary_zh"),
            data.get("judgement"),
            json.dumps(data.get("flags") or [], ensure_ascii=False),
            1 if data.get("is_chinese") else 0,
            json.dumps(data.get("points") or [], ensure_ascii=False),
            repo_id,
        ),
    )
    conn.execute("UPDATE events SET card_ready=1 WHERE repo_id=?", (repo_id,))


def untranslated(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT DISTINCT r.* FROM repos r JOIN events e ON e.repo_id = r.id
           WHERE r.description_zh IS NULL ORDER BY e.occurred_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def repos_needing_rewrite(conn: sqlite3.Connection, limit: int = 200) -> list[sqlite3.Row]:
    """需要重新生成更长介绍的仓库（老版本没有 points 字段或摘要太短）。"""
    return conn.execute(
        """SELECT * FROM repos
           WHERE description_zh IS NOT NULL AND description_zh <> ''
             AND (points IS NULL OR points = '[]' OR LENGTH(summary_zh) < 150)
           ORDER BY stars DESC, id DESC LIMIT ?""",
        (limit,),
    ).fetchall()


# ---------------- snapshots / events ----------------

def add_snapshot(
    conn: sqlite3.Connection,
    repo_id: int,
    stars: int,
    forks: int,
    open_issues: int,
    captured_on: str | None = None,
) -> None:
    captured_on = captured_on or datetime.now().strftime("%Y-%m-%dT%H")
    conn.execute(
        "INSERT OR REPLACE INTO snapshots(repo_id, captured_on, stars, forks, open_issues) VALUES(?,?,?,?,?)",
        (repo_id, captured_on, stars, forks, open_issues),
    )


def add_event(
    conn: sqlite3.Connection,
    repo_id: int,
    kind: str,
    occurred_at: str | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    occurred_at = occurred_at or now_iso()
    cur = conn.execute(
        "INSERT OR IGNORE INTO events(repo_id, kind, occurred_at, payload) VALUES(?,?,?,?)",
        (repo_id, kind, occurred_at, json.dumps(payload or {}, ensure_ascii=False)),
    )
    return cur.rowcount > 0


# ---------------- 用户行为 ----------------

def mark_seen(conn: sqlite3.Connection, repo_id: int, action: str = "shown") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO seen(repo_id, action, acted_at) VALUES(?,?,?)",
        (repo_id, action, now_iso()),
    )


def unmark_seen(conn: sqlite3.Connection, repo_id: int, action: str) -> None:
    conn.execute("DELETE FROM seen WHERE repo_id=? AND action=?", (repo_id, action))


def add_save(conn: sqlite3.Connection, repo_id: int, note: str = "") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO saves(repo_id, note, saved_at) VALUES(?,?,?)",
        (repo_id, note, now_iso()),
    )


# ---------------- 统计 ----------------

def count_repos(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) c FROM repos WHERE hidden=0").fetchone()["c"]


def count_hidden(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) c FROM repos WHERE hidden=1").fetchone()["c"]


def count_events(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM events e JOIN repos r ON r.id=e.repo_id WHERE r.hidden=0"
    ).fetchone()["c"]


def count_unread(conn: sqlite3.Connection) -> int:
    return conn.execute(
        """SELECT COUNT(*) c FROM events e JOIN repos r ON r.id=e.repo_id
           WHERE e.card_ready=1 AND r.hidden=0
             AND NOT EXISTS(SELECT 1 FROM seen s WHERE s.repo_id=e.repo_id)"""
    ).fetchone()["c"]


def set_hidden(conn: sqlite3.Connection, repo_id: int, hidden: bool, reason: str = "") -> None:
    conn.execute(
        "UPDATE repos SET hidden=?, hidden_reason=? WHERE id=?",
        (1 if hidden else 0, reason, repo_id),
    )


# ---------------- 标签 ----------------

def set_tags(conn: sqlite3.Connection, repo_id: int, tags: list[tuple[str, str]]) -> None:
    conn.execute("DELETE FROM repo_tags WHERE repo_id=?", (repo_id,))
    if tags:
        conn.executemany(
            "INSERT OR REPLACE INTO repo_tags(repo_id, tag, kind) VALUES(?,?,?)",
            [(repo_id, tag, kind) for tag, kind in tags],
        )


def tags_for(conn: sqlite3.Connection, repo_ids: list[int]) -> dict[int, list[str]]:
    if not repo_ids:
        return {}
    ph = ",".join("?" * len(repo_ids))
    rows = conn.execute(
        f"SELECT repo_id, tag FROM repo_tags WHERE repo_id IN ({ph})", repo_ids
    ).fetchall()
    out: dict[int, list[str]] = {}
    for r in rows:
        out.setdefault(r["repo_id"], []).append(r["tag"])
    return out


def repos_without_tags(conn: sqlite3.Connection, limit: int = 400) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT r.* FROM repos r
           WHERE NOT EXISTS (SELECT 1 FROM repo_tags t WHERE t.repo_id = r.id)
           ORDER BY r.stars DESC LIMIT ?""",
        (limit,),
    ).fetchall()
