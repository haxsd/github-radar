"""采集主流程：seed（种子池）/ wave（每波增量）/ update（老项目状态）/ translate（中文）。

用法：
    python -m radar.collect seed --days 30
    python -m radar.collect wave
    python -m radar.collect update --limit 2000
    python -m radar.collect translate --limit 300
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import date, datetime, timedelta
from typing import Any

from . import config, db, github, llm


def _acceptable(item: dict[str, Any]) -> bool:
    if not item.get("description"):
        return False
    if item.get("fork") or item.get("archived"):
        return False
    if (item.get("stargazers_count") or 0) <= config.MIN_STARS:
        return False
    return True


def _save_item(conn, item: dict[str, Any]) -> tuple[int, bool]:
    rid, is_new = db.upsert_repo(conn, item)
    db.add_snapshot(
        conn,
        rid,
        item.get("stargazers_count") or 0,
        item.get("forks_count") or 0,
        item.get("open_issues_count") or 0,
    )
    if is_new:
        db.add_event(conn, rid, "new", db.now_iso(), {"stars": item.get("stargazers_count")})
    return rid, is_new


# ---------------- seed ----------------

def _seed_days(conn, gh: github.GitHub, days: int, per_day: int | None = None) -> int:
    """按天拉取「近 N 天创建 + 达标」的项目，返回新增数。"""
    today = date.today()
    total = 0
    for i in range(days):
        d = today - timedelta(days=i + 1)
        n = 0
        written = 0
        try:
            for item in gh.search_created_between(d, d):
                if not _acceptable(item):
                    continue
                _, is_new = _save_item(conn, item)
                written += 1
                if is_new:
                    total += 1
                    n += 1
                if per_day and n >= per_day:
                    break
                # 频繁提交，避免长时间持有写锁（网页端会报 database is locked）
                if written % 25 == 0:
                    conn.commit()
        except Exception as exc:
            print(f"[seed] {d} 失败: {exc}")
        conn.commit()
        print(f"[seed] {d} 新增 {n}")
    return total


def cmd_seed(days: int, per_day: int | None = None) -> None:
    gh = github.GitHub()
    conn = db.connect()
    db.init_db(conn)
    total = _seed_days(conn, gh, days, per_day)
    db.meta_set(conn, "last_seed_at", db.now_iso())
    conn.commit()
    conn.close()
    print(f"[seed] 完成，共收录 {total} 个仓库")


# ---------------- backfill（扩池 + 批量补中文）----------------

def cmd_backfill(days: int = 30, translate_total: int = 3000, batch: int = 200) -> None:
    """把种子池扩到 N 天，并批量补齐中文/标签（适合首次或夜间跑）。"""
    if not _acquire_lock():
        print("[backfill] 已有采集任务在跑，跳过")
        return
    conn = None
    try:
        gh = github.GitHub()
        conn = db.connect()
        db.init_db(conn)
        db.meta_set(conn, "collecting", "1")
        conn.commit()

        seeded = _seed_days(conn, gh, days)
        print(f"[backfill] 种子扩池完成，新增 {seeded} 个")

        done = 0
        while done < translate_total:
            n = llm.translate_pending(conn, batch)
            if n <= 0:
                break
            done += n
            print(f"[backfill] 中文补齐累计 {done}")

        tagged = llm.tag_pending(conn, batch * 3)
        db.meta_set(conn, "collecting", "0")
        db.meta_set(conn, "last_wave_at", db.now_iso())
        conn.commit()
        print(f"[backfill] 完成：种子 +{seeded} · 中文 {done} · 标签 {tagged}")
    except Exception as exc:
        print(f"[backfill] 失败: {exc}")
        if conn is not None:
            try:
                db.meta_set(conn, "collecting", "0")
                conn.commit()
            except Exception:
                pass
    finally:
        if conn is not None:
            conn.close()
        _release_lock()


# ---------------- update ----------------

def cmd_update(gh: github.GitHub | None = None, limit: int = 2000) -> int:
    gh = gh or github.GitHub()
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM repos WHERE node_id IS NOT NULL ORDER BY last_seen_at ASC LIMIT ?", (limit,)
    ).fetchall()
    events = 0
    cutoff = (datetime.now() - timedelta(hours=20)).strftime("%Y-%m-%dT%H")
    for start in range(0, len(rows), 100):
        chunk = rows[start : start + 100]
        try:
            nodes = gh.fetch_nodes([r["node_id"] for r in chunk])
        except Exception as exc:
            print(f"[update] 批量查询失败: {exc}")
            continue
        by_id = {n["id"]: n for n in nodes}
        for row in chunk:
            node = by_id.get(row["node_id"])
            if not node:
                continue
            stars = node.get("stargazerCount") or 0
            forks = node.get("forkCount") or 0
            pushed = node.get("pushedAt")
            archived = 1 if node.get("isArchived") else 0

            prev = conn.execute(
                """SELECT stars FROM snapshots
                   WHERE repo_id=? AND captured_on<=?
                   ORDER BY captured_on DESC LIMIT 1""",
                (row["id"], cutoff),
            ).fetchone()
            base = prev["stars"] if prev else (row["stars"] or 0)

            db.add_snapshot(conn, row["id"], stars, forks, row["open_issues"] or 0)
            conn.execute(
                """UPDATE repos SET stars=?, forks=?, pushed_at=?, archived=?, last_seen_at=?
                   WHERE id=?""",
                (stars, forks, pushed, archived, db.now_iso(), row["id"]),
            )

            delta = stars - (base or 0)
            if base and (
                delta >= config.STAR_JUMP_ABS
                or delta / max(base, 1) >= config.STAR_JUMP_RATIO
            ):
                if db.add_event(
                    conn, row["id"], "stars", db.now_iso(), {"delta": delta, "stars": stars}
                ):
                    events += 1

            rel = node.get("latestRelease") or {}
            tag = rel.get("tagName")
            if tag and tag != row["last_release_tag"]:
                conn.execute("UPDATE repos SET last_release_tag=? WHERE id=?", (tag, row["id"]))
                # 第一次见到该仓库时只登记版本，不推"新版本"卡片
                if row["last_release_tag"] and db.add_event(
                    conn,
                    row["id"],
                    "release",
                    rel.get("publishedAt") or db.now_iso(),
                    {"tag": tag},
                ):
                    events += 1
        conn.commit()
    conn.close()
    print(f"[update] 检查 {len(rows)} 个仓库，新增更新事件 {events}")
    return events


# ---------------- wave ----------------

LOCK_FILE = config.DATA_DIR / ".collect.lock"


def _acquire_lock() -> bool:
    """防止定时任务和启动补跑同时跑。"""
    config.ensure_dirs()
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            if time.time() - LOCK_FILE.stat().st_mtime > 7200:
                LOCK_FILE.unlink(missing_ok=True)
                return _acquire_lock()
        except OSError:
            pass
        return False


def _release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _translate_via_subprocess(limit: int, timeout: int = 600) -> None:
    """翻译放到子进程跑，超时就杀掉。

    后台/计划任务环境下，长时间批量请求偶发卡在 TLS 握手或读响应上；
    超时终止可以保证整波采集不被拖死，剩下的留到下一波继续。
    """
    import subprocess
    import sys

    cmd = [sys.executable, "-u", "-m", "radar.collect", "translate", "--limit", str(limit)]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(config.ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[wave] 翻译阶段超时（{timeout}s），已跳过，下波继续")
        try:
            if proc is not None:
                proc.kill()
        except Exception:
            pass
    except Exception as exc:
        print(f"[wave] 翻译子进程失败: {exc}")


def cmd_rewrite(limit: int = 400, workers: int = 6) -> None:
    """给已有项目重新生成更长的中文介绍 + 要点（老卡片升级）。"""
    conn = db.connect()
    db.init_db(conn)
    done = llm.rewrite_cards(conn, limit=limit, workers=workers)
    conn.close()
    print(f"[rewrite] 完成 {done} 个仓库的介绍升级")


# ---------------- clean（脏数据清洗）----------------

SPAM_PATTERNS = [
    # 破解 / 盗版分发
    "实为分发破解版", "破解补丁", "keygen", "序列号生成",
    # SEO 推广页 / 空壳
    "实为 html 推广页", "实为推广页", "安装配置图文指南", "安装与配置图文指南",
    "setup-guide", "setup guide", "免费领取", "加微信",
]

# 代理/节点订阅清单类：是"资源合集"而非软件，且质量低时才隐藏
LIST_PATTERNS = ["机场推荐", "节点订阅", "订阅链接大全", "免费节点"]

SOFTWARE_FORMS = {"form:app", "form:cli", "form:library", "form:framework", "form:plugin"}


def find_spam(conn) -> list[tuple[int, str, str]]:
    """返回可能该隐藏的仓库 (id, full_name, 命中的原因)。"""
    rows = conn.execute("SELECT id, full_name, description, description_zh, summary_zh FROM repos WHERE hidden=0").fetchall()
    tag_rows = conn.execute("SELECT repo_id, tag FROM repo_tags").fetchall()
    tags: dict[int, set[str]] = {}
    for t in tag_rows:
        tags.setdefault(t["repo_id"], set()).add(t["tag"])

    hits: list[tuple[int, str, str]] = []
    for r in rows:
        text = " ".join(
            [r["full_name"] or "", r["description"] or "", r["description_zh"] or "", r["summary_zh"] or ""]
        ).lower()
        reason = next((p for p in SPAM_PATTERNS if p.lower() in text), None)
        if reason:
            hits.append((r["id"], r["full_name"], reason))
            continue
        list_hit = next((p for p in LIST_PATTERNS if p.lower() in text), None)
        if list_hit and not (tags.get(r["id"], set()) & SOFTWARE_FORMS):
            hits.append((r["id"], r["full_name"], list_hit))
    return hits


def find_farms(conn) -> list[tuple[int, str, str]]:
    """识别批量刷星的垃圾农场：同语言、同 star 数、同一天创建，动辄上百个。"""
    groups = conn.execute(
        """SELECT stars, language, substr(created_at,1,10) AS d, COUNT(*) AS n
           FROM repos
           WHERE hidden = 0 AND language IN ('HTML', 'CSS')
           GROUP BY stars, language, d
           HAVING n >= 20"""
    ).fetchall()
    hits: list[tuple[int, str, str]] = []
    for g in groups:
        rows = conn.execute(
            """SELECT id, full_name FROM repos
               WHERE hidden = 0 AND stars = ? AND language = ?
                 AND substr(created_at,1,10) = ?""",
            (g["stars"], g["language"], g["d"]),
        ).fetchall()
        reason = f"farm:{g['stars']}★/{g['language']}/{g['d']} 共{g['n']}个"
        for r in rows:
            hits.append((r["id"], r["full_name"], reason))
    return hits


def cmd_clean(apply: bool = False, unhide: bool = False) -> None:
    conn = db.connect()
    db.init_db(conn)
    if unhide:
        conn.execute("UPDATE repos SET hidden=0, hidden_reason=NULL")
        conn.commit()
        print("[clean] 已全部恢复显示")
        conn.close()
        return
    spam = find_spam(conn)
    farms = find_farms(conn)
    hits = spam + farms
    print(f"[clean] SEO/推广类 {len(spam)} 个 · 刷星农场 {len(farms)} 个 · 合计 {len(hits)} 个")
    for rid, name, pat in hits[:30]:
        print(f"  - {name}  ← {pat}")
    if apply and hits:
        for rid, name, pat in hits:
            db.set_hidden(conn, rid, True, f"spam:{pat}")
        conn.commit()
        print(f"[clean] 已隐藏 {len(hits)} 个")
    elif hits:
        print("[clean] 预览模式：加 --apply 才会真正隐藏")
    conn.close()


def cmd_wave(
    translate_limit: int = 200,
    update_limit: int = 2000,
    days: int | None = None,
    tag_limit: int = 400,
) -> None:
    days = days or config.INCREMENTAL_DAYS
    if not _acquire_lock():
        print("[wave] 已有采集任务在跑，跳过本次")
        return
    conn = None
    try:
        gh = github.GitHub()
        conn = db.connect()
        db.init_db(conn)
        db.meta_set(conn, "collecting", "1")
        conn.commit()
        today = date.today()
        new = 0
        for i in range(days):
            d = today - timedelta(days=i)
            n = 0
            try:
                for item in gh.search_created_between(d, d):
                    if not _acceptable(item):
                        continue
                    _, is_new = _save_item(conn, item)
                    if is_new:
                        new += 1
                        n += 1
            except Exception as exc:
                print(f"[wave] {d} 失败: {exc}")
            conn.commit()
            print(f"[wave] {d} 新增 {n}")
        db.meta_set(conn, "last_wave_at", db.now_iso())
        conn.commit()

        updated = cmd_update(gh, update_limit)
        _translate_via_subprocess(translate_limit)
        done = 0
        tagged = llm.tag_pending(conn, tag_limit) if tag_limit else 0
        db.meta_set(conn, "collecting", "0")
        db.meta_set(conn, "last_wave_finished_at", db.now_iso())
        conn.commit()
        print(
            f"[wave] 完成：新收录 {new} · 更新事件 {updated} · 中文补齐 {done} · 标签补齐 {tagged}"
        )
    except Exception as exc:
        print(f"[wave] 失败: {exc}")
        if conn is not None:
            try:
                db.meta_set(conn, "collecting", "0")
                conn.commit()
            except Exception:
                pass
        raise
    finally:
        if conn is not None:
            conn.close()
        _release_lock()


def catchup_if_stale(max_age_hours: float = 8.0) -> bool:
    """启动时检查数据新鲜度；过期就补跑一次（补偿关机期间漏掉的定时任务）。"""
    try:
        conn = db.connect()
        db.init_db(conn)
        last = db.meta_get(conn, "last_wave_at") or db.meta_get(conn, "last_seed_at")
        conn.close()
        age = 999.0
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.astimezone()
                age = (datetime.now().astimezone() - last_dt).total_seconds() / 3600.0
            except (ValueError, TypeError):
                pass
        if age < max_age_hours:
            print(f"[startup] 数据 {age:.1f} 小时前更新，无需补跑")
            return False
        print(f"[startup] 数据已 {age:.1f} 小时未更新，后台补跑一次采集…")
        cmd_wave(translate_limit=120, update_limit=600, tag_limit=200)
        return True
    except Exception as exc:
        print(f"[startup] 补跑失败: {exc}")
        return False


# ---------------- CLI ----------------

def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub 中文雷达 · 采集器")
    sub = parser.add_subparsers(dest="cmd")

    p_seed = sub.add_parser("seed", help="拉种子池（近 N 天创建）")
    p_seed.add_argument("--days", type=int, default=config.SEED_DAYS)
    p_seed.add_argument("--per-day", type=int, default=None, help="每天最多收录多少个（调试用）")

    p_wave = sub.add_parser("wave", help="跑一波：新项目 + 更新 + 翻译 + 标签")
    p_wave.add_argument("--translate-limit", type=int, default=200)
    p_wave.add_argument("--update-limit", type=int, default=2000)
    p_wave.add_argument("--tag-limit", type=int, default=400)
    p_wave.add_argument("--days", type=int, default=None)

    p_up = sub.add_parser("update", help="只检查老项目更新")
    p_up.add_argument("--limit", type=int, default=2000)

    p_tr = sub.add_parser("translate", help="只补齐中文文案")
    p_tr.add_argument("--limit", type=int, default=300)

    p_tag = sub.add_parser("tag", help="只给项目打标签（领域/形态/平台/特性）")
    p_tag.add_argument("--limit", type=int, default=400)

    p_rw = sub.add_parser("rewrite", help="重新生成更长的中文介绍（老卡片升级）")
    p_rw.add_argument("--limit", type=int, default=400)

    p_clean = sub.add_parser("clean", help="清洗脏数据（隐藏 SEO/破解/推广类仓库）")
    p_clean.add_argument("--apply", action="store_true", help="真正执行隐藏（默认只预览）")
    p_clean.add_argument("--unhide", action="store_true", help="恢复所有被隐藏的仓库")

    p_bf = sub.add_parser("backfill", help="扩池：补齐近 N 天种子 + 批量补中文")
    p_bf.add_argument("--days", type=int, default=config.SEED_DAYS)
    p_bf.add_argument("--translate-total", type=int, default=3000)
    p_bf.add_argument("--batch", type=int, default=200)

    args = parser.parse_args()
    if args.cmd == "seed":
        cmd_seed(args.days, args.per_day)
    elif args.cmd == "update":
        cmd_update(limit=args.limit)
    elif args.cmd == "translate":
        conn = db.connect()
        db.init_db(conn)
        done = llm.translate_pending(conn, args.limit)
        conn.close()
        print(f"[translate] 完成 {done} 条")
    elif args.cmd == "tag":
        conn = db.connect()
        db.init_db(conn)
        done = llm.tag_pending(conn, args.limit)
        conn.close()
        print(f"[tag] 完成 {done} 个仓库")
    elif args.cmd == "rewrite":
        cmd_rewrite(args.limit)
    elif args.cmd == "clean":
        cmd_clean(args.apply, args.unhide)
    elif args.cmd == "backfill":
        cmd_backfill(args.days, args.translate_total, args.batch)
    elif args.cmd == "wave":
        cmd_wave(args.translate_limit, args.update_limit, args.days, args.tag_limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
