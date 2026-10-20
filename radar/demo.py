"""内置示例数据：没配 GitHub Token / 模型 Key 的空库也能看到界面效果。

用法：
    python -m radar.demo            # 载入示例数据
    python -m radar.demo --reset    # 清空示例数据（只删演示仓库）
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import db

DATA_FILE = Path(__file__).with_name("demo_data.json")


def load_items() -> list[dict[str, Any]]:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return list(data.get("items") or [])


def is_empty(conn=None) -> bool:
    own = conn is None
    conn = conn or db.connect()
    db.init_db(conn)
    try:
        return db.count_repos(conn) == 0 and db.count_hidden(conn) == 0
    finally:
        if own:
            conn.close()


def _now() -> datetime:
    return datetime.now()


def load_demo(conn=None) -> dict[str, int]:
    """把示例仓库写入本地库：仓库 + 标签 + 快照 + 卡片事件。"""
    own = conn is None
    conn = conn or db.connect()
    db.init_db(conn)
    now = _now()
    base_hour = now.replace(minute=0, second=0, microsecond=0)
    earlier = base_hour - timedelta(hours=6)

    inserted = updated = 0
    for index, item in enumerate(load_items()):
        full_name = item["full_name"]
        owner, _, name = full_name.partition("/")
        stars = int(item.get("stars") or 0)
        tags = (
            [f"cat:{item['category']}"]
            + [f"form:{item['form']}"]
            + [f"platform:{item['platform']}"]
            + [f"feature:{f}" for f in item.get("features") or []]
            + [f"kw:{k}" for k in item.get("keywords") or []]
        )
        seen_at = now.isoformat(timespec="seconds")

        row = conn.execute("SELECT id FROM repos WHERE full_name=?", (full_name,)).fetchone()
        if row:
            repo_id = int(row["id"])
            updated += 1
        else:
            cur = conn.execute(
                """INSERT INTO repos
                   (full_name, owner, name, html_url, description, description_zh,
                    summary_zh, points, judgement, flags, language, license, topics,
                    homepage, stars, forks, open_issues, is_chinese, quality,
                    created_at, pushed_at, first_seen_at, last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    full_name,
                    owner,
                    name,
                    f"https://github.com/{full_name}",
                    item.get("description") or "",
                    item.get("description_zh") or "",
                    item.get("summary_zh") or "",
                    json.dumps(item.get("points") or [], ensure_ascii=False),
                    "值得用",
                    "[]",
                    item.get("language") or "",
                    item.get("license") or "",
                    json.dumps(item.get("topics") or [], ensure_ascii=False),
                    "",
                    stars,
                    int(item.get("forks") or 0),
                    0,
                    0,
                    0.8,
                    item.get("created_at") or seen_at,
                    item.get("pushed_at") or seen_at,
                    seen_at,
                    seen_at,
                ),
            )
            repo_id = int(cur.lastrowid)
            inserted += 1

        conn.execute("UPDATE repos SET stars=?, description_zh=?, summary_zh=?, points=? WHERE id=?",
                     (stars, item.get("description_zh") or "", item.get("summary_zh") or "",
                      json.dumps(item.get("points") or [], ensure_ascii=False), repo_id))
        for tag in tags:
            kind = tag.split(":", 1)[0]
            conn.execute(
                "INSERT OR IGNORE INTO repo_tags (repo_id, tag, kind) VALUES (?,?,?)",
                (repo_id, tag, kind),
            )

        delta = int(item.get("delta") or 0)
        conn.execute(
            "INSERT OR REPLACE INTO snapshots (repo_id, captured_on, stars, forks, open_issues)"
            " VALUES (?,?,?,?,?)",
            (repo_id, earlier.strftime("%Y-%m-%dT%H"), max(0, stars - delta), int(item.get("forks") or 0), 0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO snapshots (repo_id, captured_on, stars, forks, open_issues)"
            " VALUES (?,?,?,?,?)",
            (repo_id, base_hour.strftime("%Y-%m-%dT%H"), stars, int(item.get("forks") or 0), 0),
        )

        has_event = conn.execute(
            "SELECT 1 FROM events WHERE repo_id=? AND card_ready=1 LIMIT 1", (repo_id,)
        ).fetchone()
        if not has_event:
            occurred = (now - timedelta(minutes=index * 7)).isoformat(timespec="seconds")
            conn.execute(
                "INSERT OR IGNORE INTO events (repo_id, kind, occurred_at, payload, card_ready)"
                " VALUES (?,?,?,?,1)",
                (repo_id, "new", occurred, json.dumps({"demo": True}, ensure_ascii=False)),
            )

    conn.commit()
    db.meta_set(conn, "demo_loaded_at", now.isoformat(timespec="seconds"))
    conn.commit()
    if own:
        conn.close()
    return {"inserted": inserted, "updated": updated, "total": inserted + updated}


def reset_demo(conn=None) -> int:
    """删除示例数据（按 full_name 匹配）。"""
    own = conn is None
    conn = conn or db.connect()
    db.init_db(conn)
    names = [it["full_name"] for it in load_items()]
    removed = 0
    for name in names:
        row = conn.execute("SELECT id FROM repos WHERE full_name=?", (name,)).fetchone()
        if not row:
            continue
        repo_id = int(row["id"])
        conn.execute("DELETE FROM repo_tags WHERE repo_id=?", (repo_id,))
        conn.execute("DELETE FROM snapshots WHERE repo_id=?", (repo_id,))
        conn.execute("DELETE FROM events WHERE repo_id=?", (repo_id,))
        # 必须一并清理用户行为，否则 SQLite 复用 repo id 时会串到新项目上
        conn.execute("DELETE FROM seen WHERE repo_id=?", (repo_id,))
        conn.execute("DELETE FROM saves WHERE repo_id=?", (repo_id,))
        conn.execute("DELETE FROM repos WHERE id=?", (repo_id,))
        removed += 1
    conn.execute("DELETE FROM meta WHERE key='demo_loaded_at'")
    conn.commit()
    if own:
        conn.close()
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="载入 / 清空内置示例数据")
    parser.add_argument("--reset", action="store_true", help="删除示例数据")
    args = parser.parse_args()
    if args.reset:
        print(f"[demo] 已删除 {reset_demo()} 个示例仓库")
    else:
        result = load_demo()
        print(f"[demo] 已载入示例数据：{result}")


if __name__ == "__main__":
    main()
