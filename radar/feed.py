"""信息流：候选查询、个性化排序、标签组合筛选、榜单、收藏。"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from typing import Any

from . import db, taxonomy

# 兴趣反馈权重
ACTION_WEIGHT = {"save": 2.0, "like": 1.5, "skip": -1.0}
TAG_WEIGHT = {"cat": 0.60, "platform": 0.35, "feature": 0.35, "form": 0.20}


def _hours_since(iso: str | None) -> float:
    if not iso:
        return 999.0
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 999.0
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def _json_field(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else (value or default)
    except Exception:
        return default


# ---------------- 兴趣画像 ----------------

def affinity(conn) -> dict[str, float]:
    """从收藏/感兴趣/跳过里学出标签偏好，范围约 -0.5 ~ 0.5。"""
    rows = conn.execute(
        """SELECT t.tag, s.action, COUNT(*) AS n
           FROM seen s JOIN repo_tags t ON t.repo_id = s.repo_id
           WHERE s.action IN ('save','like','skip')
             AND t.kind IN ('cat','platform','feature')
           GROUP BY t.tag, s.action"""
    ).fetchall()
    pos: dict[str, float] = {}
    neg: dict[str, float] = {}
    for r in rows:
        w = ACTION_WEIGHT.get(r["action"], 0.0) * float(r["n"])
        if w >= 0:
            pos[r["tag"]] = pos.get(r["tag"], 0.0) + w
        else:
            neg[r["tag"]] = neg.get(r["tag"], 0.0) - w
    out: dict[str, float] = {}
    for tag in set(pos) | set(neg):
        p, n = pos.get(tag, 0.0), neg.get(tag, 0.0)
        out[tag] = round((p - n) / (p + n + 2.0), 3)
    return out


def _personal(tags: list[str], aff: dict[str, float]) -> float:
    if not aff or not tags:
        return 0.0
    s = sum(TAG_WEIGHT.get(t.split(":")[0], 0.0) * aff.get(t, 0.0) for t in tags)
    return max(-0.45, min(0.70, s))


def _score(row: Any, tags: list[str], aff: dict[str, float]) -> float:
    freshness = math.exp(-_hours_since(row["occurred_at"]) / 48.0)
    quality = float(row["quality"] or 0.0)
    kind_bonus = {"new": 0.10, "release": 0.06, "stars": 0.04}.get(row["kind"], 0.0)
    base = freshness * (0.35 + quality) + kind_bonus
    return base * (1.0 + _personal(tags, aff))


def profile_summary() -> dict[str, Any]:
    conn = db.connect()
    db.init_db(conn)
    rows = conn.execute(
        "SELECT action, COUNT(*) n FROM seen WHERE action IN ('like','save','skip') GROUP BY action"
    ).fetchall()
    counts = {r["action"]: r["n"] for r in rows}
    aff = affinity(conn)
    conn.close()
    pos = sorted(((t, v) for t, v in aff.items() if v > 0.05), key=lambda x: -x[1])[:4]
    neg = sorted(((t, v) for t, v in aff.items() if v < -0.05), key=lambda x: x[1])[:4]
    return {
        "signals": sum(counts.values()),
        "counts": counts,
        "positive": [{"tag": t, "label": taxonomy.label(t), "score": v} for t, v in pos],
        "negative": [{"tag": t, "label": taxonomy.label(t), "score": v} for t, v in neg],
    }


# ---------------- 出卡 ----------------

def _to_card(row: Any, score: float, tags: list[str]) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "kind": row["kind"],
        "occurred_at": row["occurred_at"],
        "repo_id": row["id"],
        "full_name": row["full_name"],
        "html_url": row["html_url"],
        "description_zh": row["description_zh"],
        "summary_zh": row["summary_zh"],
        "points": _json_field(row["points"], []),
        "judgement": row["judgement"],
        "flags": _json_field(row["flags"], []),
        "topics": _json_field(row["topics"], [])[:6],
        "tags": tags,
        "tag_labels": [taxonomy.label(t) for t in tags],
        "category": next((taxonomy.label(t) for t in tags if t.startswith("cat:")), ""),
        "language": row["language"],
        "license": row["license"],
        "stars": row["stars"],
        "forks": row["forks"],
        "is_chinese": bool(row["is_chinese"]),
        "homepage": row["homepage"],
        "pushed_at": row["pushed_at"],
        "payload": _json_field(row["payload"], {}),
        "score": round(score, 4),
    }


def _split_tags(tags: list[str] | None, category: str | None) -> list[str]:
    out: list[str] = []
    if category:
        out.append(category)
    for t in tags or []:
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out[:6]


def next_cards(
    limit: int = 20,
    category: str | None = None,
    tags: list[str] | None = None,
    mark_shown: bool = True,
) -> list[dict[str, Any]]:
    wanted = _split_tags(tags, category)
    conn = db.connect()
    db.init_db(conn)
    sql = """SELECT e.id AS event_id, e.kind, e.occurred_at, e.payload, r.*
             FROM events e JOIN repos r ON r.id = e.repo_id
             WHERE e.card_ready = 1 AND r.hidden = 0
               AND NOT EXISTS (SELECT 1 FROM seen s WHERE s.repo_id = r.id)"""
    params: list[Any] = []
    for tag in wanted:
        sql += """ AND EXISTS (SELECT 1 FROM repo_tags t
                               WHERE t.repo_id = r.id AND t.tag = ?)"""
        params.append(tag)
    sql += " ORDER BY e.occurred_at DESC LIMIT 900"

    rows = conn.execute(sql, params).fetchall()
    tags_map = db.tags_for(conn, [r["id"] for r in rows])
    aff = affinity(conn)
    scored = sorted(
        ((_score(r, tags_map.get(r["id"], []), aff), r) for r in rows), key=lambda x: -x[0]
    )

    # 多样性：同一领域最多占 ~25%，避免一屏全是同类项目
    cap = max(2, int(limit * 0.25))
    picked: list[tuple[float, Any]] = []
    per_cat: dict[str, int] = {}
    for score, r in scored:
        cat = next((t for t in tags_map.get(r["id"], []) if t.startswith("cat:")), "cat:other")
        if per_cat.get(cat, 0) >= cap:
            continue
        per_cat[cat] = per_cat.get(cat, 0) + 1
        picked.append((score, r))
        if len(picked) >= limit:
            break
    if len(picked) < limit:  # 领域太集中时补足数量
        chosen = {r["id"] for _, r in picked}
        for score, r in scored:
            if r["id"] in chosen:
                continue
            picked.append((score, r))
            if len(picked) >= limit:
                break

    cards = [_to_card(r, s, tags_map.get(r["id"], [])) for s, r in picked]

    if mark_shown:
        try:
            for card in cards:
                db.mark_seen(conn, card["repo_id"], "shown")
            conn.commit()
        except Exception:
            # 采集正在写库时可能短暂锁定：卡片照常返回，下次再标记
            try:
                conn.rollback()
            except Exception:
                pass
    conn.close()
    return cards


# ---------------- 筛选面板 ----------------

def category_counts() -> list[dict[str, Any]]:
    conn = db.connect()
    db.init_db(conn)
    rows = conn.execute(
        """SELECT t.tag, COUNT(DISTINCT e.repo_id) AS n
           FROM repo_tags t
           JOIN events e ON e.repo_id = t.repo_id
           JOIN repos r ON r.id = t.repo_id AND r.hidden = 0
           WHERE t.kind = 'cat' AND e.card_ready = 1
             AND NOT EXISTS (SELECT 1 FROM seen s WHERE s.repo_id = e.repo_id)
           GROUP BY t.tag ORDER BY n DESC"""
    ).fetchall()
    conn.close()
    return [{"tag": r["tag"], "label": taxonomy.label(r["tag"]), "count": r["n"]} for r in rows]


def tag_groups() -> list[dict[str, Any]]:
    """组合筛选用：按 领域/平台/特性/形态 分组的标签与未读数量。"""
    conn = db.connect()
    db.init_db(conn)
    rows = conn.execute(
        """SELECT t.kind, t.tag, COUNT(DISTINCT e.repo_id) AS n
           FROM repo_tags t
           JOIN events e ON e.repo_id = t.repo_id
           JOIN repos r ON r.id = t.repo_id AND r.hidden = 0
           WHERE e.card_ready = 1
             AND NOT EXISTS (SELECT 1 FROM seen s WHERE s.repo_id = e.repo_id)
           GROUP BY t.kind, t.tag"""
    ).fetchall()
    conn.close()
    buckets: dict[str, list[dict[str, Any]]] = {"cat": [], "platform": [], "feature": [], "form": []}
    for r in rows:
        if r["kind"] in buckets:
            buckets[r["kind"]].append(
                {"tag": r["tag"], "label": taxonomy.label(r["tag"]), "count": r["n"]}
            )
    names = {"cat": "领域", "platform": "平台", "feature": "特性", "form": "形态"}
    out = []
    for kind in ("cat", "platform", "feature", "form"):
        items = sorted(buckets[kind], key=lambda x: -x["count"])[:18]
        if items:
            out.append({"kind": kind, "name": names[kind], "items": items})
    return out


# ---------------- 统计 ----------------

def stats() -> dict[str, Any]:
    conn = db.connect()
    db.init_db(conn)
    out = {
        "repos": db.count_repos(conn),
        "events": db.count_events(conn),
        "unread": db.count_unread(conn),
        "tagged": conn.execute("SELECT COUNT(DISTINCT repo_id) n FROM repo_tags").fetchone()["n"],
        "saved": conn.execute("SELECT COUNT(*) n FROM saves").fetchone()["n"],
        "hidden": db.count_hidden(conn),
        "last_wave_at": db.meta_get(conn, "last_wave_at") or db.meta_get(conn, "last_seed_at"),
        "collecting": db.meta_get(conn, "collecting") == "1",
    }
    conn.close()
    return out


# ---------------- 榜单 ----------------

def _snapshot_span(conn) -> float:
    row = conn.execute("SELECT MIN(captured_on) a, MAX(captured_on) b FROM snapshots").fetchone()
    if not row or not row["a"] or not row["b"]:
        return 0.0
    try:
        a = datetime.fromisoformat(row["a"])
        b = datetime.fromisoformat(row["b"])
        return max(0.0, (b - a).total_seconds() / 86400.0)
    except ValueError:
        return 0.0


def ranking(days: int = 7, limit: int = 60) -> dict[str, Any]:
    conn = db.connect()
    db.init_db(conn)
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H")
    rows = conn.execute(
        """
        WITH w AS (
          SELECT repo_id, stars, captured_on,
                 ROW_NUMBER() OVER (PARTITION BY repo_id ORDER BY captured_on) AS rf,
                 ROW_NUMBER() OVER (PARTITION BY repo_id ORDER BY captured_on DESC) AS rl
          FROM snapshots WHERE captured_on >= ?
        )
        SELECT r.*, (wl.stars - wf.stars) AS delta, wf.stars AS stars_first,
               wl.stars AS stars_last, wl.captured_on AS last_at
        FROM w wf
        JOIN w wl ON wf.repo_id = wl.repo_id AND wf.rf = 1 AND wl.rl = 1
        JOIN repos r ON r.id = wf.repo_id
        WHERE r.hidden = 0 AND (wl.stars - wf.stars) <> 0
        ORDER BY delta DESC
        LIMIT ?
        """,
        (since, limit),
    ).fetchall()
    tags_map = db.tags_for(conn, [r["id"] for r in rows])
    items = []
    for r in rows:
        base = dict(r)
        base.update(event_id=0, kind="rank", occurred_at=r["last_at"], payload="{}")
        d = _to_card(base, 0.0, tags_map.get(r["id"], []))
        d["delta"] = r["delta"]
        d["stars_first"] = r["stars_first"]
        items.append(d)
    span = _snapshot_span(conn)
    conn.close()
    return {"items": items, "window_days": days, "span_days": round(span, 1)}


def newcomers(limit: int = 60) -> list[dict[str, Any]]:
    conn = db.connect()
    db.init_db(conn)
    rows = conn.execute(
        """SELECT e.id AS event_id, e.kind, e.occurred_at, e.payload, r.*
           FROM events e JOIN repos r ON r.id = e.repo_id
           WHERE e.kind = 'new' AND r.hidden = 0
           ORDER BY e.occurred_at DESC, r.stars DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    tags_map = db.tags_for(conn, [r["id"] for r in rows])
    items = [_to_card(r, 0.0, tags_map.get(r["id"], [])) for r in rows]
    conn.close()
    return items


def top_stars(limit: int = 60) -> list[dict[str, Any]]:
    conn = db.connect()
    db.init_db(conn)
    rows = conn.execute(
        "SELECT * FROM repos WHERE hidden=0 ORDER BY stars DESC LIMIT ?", (limit,)
    ).fetchall()
    tags_map = db.tags_for(conn, [r["id"] for r in rows])
    items = []
    for r in rows:
        base = dict(r)
        base.update(event_id=0, kind="top", occurred_at=r["pushed_at"], payload="{}")
        items.append(_to_card(base, 0.0, tags_map.get(r["id"], [])))
    conn.close()
    return items


def history(limit: int = 120) -> dict[str, Any]:
    """已读回看：最近跳过 / 收藏 / 看过。"""
    conn = db.connect()
    db.init_db(conn)

    def _fetch(action: str | None, n: int) -> list[dict[str, Any]]:
        sql = """SELECT r.*, s.action AS seen_action, s.acted_at
                 FROM seen s JOIN repos r ON r.id = s.repo_id
                 WHERE r.hidden = 0"""
        params: list[Any] = []
        if action:
            sql += " AND s.action = ?"
            params.append(action)
        sql += " ORDER BY s.acted_at DESC LIMIT ?"
        params.append(n)
        rows = conn.execute(sql, params).fetchall()
        tags_map = db.tags_for(conn, [r["id"] for r in rows])
        out = []
        for r in rows:
            base = dict(r)
            base.update(event_id=0, kind="history", occurred_at=r["acted_at"], payload="{}")
            d = _to_card(base, 0.0, tags_map.get(r["id"], []))
            d["seen_action"] = r["seen_action"]
            d["acted_at"] = r["acted_at"]
            out.append(d)
        return out

    out = {
        "skipped": _fetch("skip", limit),
        "liked": _fetch("like", limit),
        "saved": _fetch("save", limit),
        "skipped_count": conn.execute(
            "SELECT COUNT(*) n FROM seen s JOIN repos r ON r.id=s.repo_id WHERE s.action='skip' AND r.hidden=0"
        ).fetchone()["n"],
    }
    conn.close()
    return out


def similar(repo_id: int, limit: int = 6) -> list[dict[str, Any]]:
    """按标签重合度找相似项目。"""
    conn = db.connect()
    db.init_db(conn)
    tags = db.tags_for(conn, [repo_id]).get(repo_id, [])
    keys = [t for t in tags if t.split(":")[0] in ("cat", "platform", "feature", "form")]
    if not keys:
        conn.close()
        return []
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        f"""SELECT r.id, r.full_name, r.html_url, r.description_zh, r.stars, r.language,
                   COUNT(*) AS overlap
            FROM repo_tags t JOIN repos r ON r.id = t.repo_id
            WHERE t.tag IN ({placeholders}) AND r.id <> ? AND r.hidden = 0
            GROUP BY r.id
            ORDER BY overlap DESC, r.stars DESC
            LIMIT ?""",
        (*keys, repo_id, limit),
    ).fetchall()
    out = [
        {
            "repo_id": r["id"],
            "full_name": r["full_name"],
            "html_url": r["html_url"],
            "description_zh": r["description_zh"],
            "stars": r["stars"],
            "language": r["language"],
            "overlap": r["overlap"],
        }
        for r in rows
    ]
    conn.close()
    return out


def daily(limit: int = 12) -> list[dict[str, Any]]:
    """今日精选：近 24 小时的事件里按个性化分数挑，每个领域最多 2 个。"""
    conn = db.connect()
    db.init_db(conn)
    since = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT e.id AS event_id, e.kind, e.occurred_at, e.payload, r.*
           FROM events e JOIN repos r ON r.id = e.repo_id
           WHERE e.card_ready = 1 AND r.hidden = 0 AND e.occurred_at >= ?
           ORDER BY e.occurred_at DESC LIMIT 1200""",
        (since,),
    ).fetchall()
    tags_map = db.tags_for(conn, [r["id"] for r in rows])
    aff = affinity(conn)
    scored = sorted(
        ((_score(r, tags_map.get(r["id"], []), aff), r) for r in rows), key=lambda x: -x[0]
    )
    picked: list[Any] = []
    per_cat: dict[str, int] = {}
    for score, r in scored:
        cat = next((t for t in tags_map.get(r["id"], []) if t.startswith("cat:")), "cat:other")
        if per_cat.get(cat, 0) >= 2:
            continue
        per_cat[cat] = per_cat.get(cat, 0) + 1
        picked.append((score, r))
        if len(picked) >= limit:
            break
    cards = [_to_card(r, s, tags_map.get(r["id"], [])) for s, r in picked]
    conn.close()
    return cards


def saved_cards(limit: int = 200) -> list[dict[str, Any]]:
    conn = db.connect()
    db.init_db(conn)
    rows = conn.execute(
        """SELECT r.*, s.note AS save_note, s.saved_at
           FROM saves s JOIN repos r ON r.id = s.repo_id
           ORDER BY s.saved_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    tags_map = db.tags_for(conn, [r["id"] for r in rows])
    items = []
    for r in rows:
        base = dict(r)
        base.update(event_id=0, kind="saved", occurred_at=r["saved_at"], payload="{}")
        d = _to_card(base, 0.0, tags_map.get(r["id"], []))
        d["note"] = r["save_note"]
        d["saved_at"] = r["saved_at"]
        items.append(d)
    conn.close()
    return items


def card_by_id(repo_id: int) -> dict[str, Any] | None:
    """单仓库详情（榜单/收藏等页面点击行时用）。"""
    conn = db.connect()
    db.init_db(conn)
    row = conn.execute("SELECT * FROM repos WHERE id=?", (repo_id,)).fetchone()
    if not row:
        conn.close()
        return None
    tags = db.tags_for(conn, [repo_id]).get(repo_id, [])
    base = dict(row)
    base.update(event_id=0, kind="view", occurred_at=row["pushed_at"], payload="{}")
    card = _to_card(base, 0.0, tags)
    conn.close()
    return card
