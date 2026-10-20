"""采集主流程：seed（种子池）/ wave（每波增量）/ update（老项目状态）/ translate（中文）。

用法：
    python -m radar.collect seed --days 30
    python -m radar.collect wave
    python -m radar.collect update --limit 2000
    python -m radar.collect translate --limit 300
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Any

from . import config, db, github, llm, netguard

logger = logging.getLogger(__name__)


def _record_failure(scope: str, exc: BaseException, conn=None) -> None:
    """把最近一次采集失败摘要写进 meta，供网页展示。

    记录失败信息本身不能影响主流程：写库失败只打日志。
    传入 conn 时优先复用（可能已处于事务中），失败再用独立连接兜底。
    """
    message = f"{type(exc).__name__}: {exc}"[:400]
    # 用毫秒精度：last_wave_at 是秒精度，同一秒内的快速失败也要能被判定为"未恢复"
    now = db.now_iso_ms()

    def _write(target) -> None:
        db.meta_set(target, "last_error_at", now)
        db.meta_set(target, "last_error_scope", scope[:60])
        db.meta_set(target, "last_error_message", message)
        target.commit()

    if conn is not None:
        try:
            _write(conn)
            return
        except Exception as write_exc:
            logger.warning("记录采集失败信息失败（复用连接，scope=%s）: %s", scope, write_exc)
    try:
        own = db.connect()
        try:
            db.init_db(own)
            _write(own)
        finally:
            own.close()
    except Exception as write_exc:
        logger.warning("记录采集失败信息失败（独立连接，scope=%s）: %s", scope, write_exc)


def _fill_og_images(gh: github.GitHub, limit: int = 300) -> int:
    """给还没有预览图的仓库回填 openGraphImageUrl（按最近卡片时间优先）。

    GitHub 只在 GraphQL 里返回该字段，这里每波补一小批，避免拖慢采集。
    只写入通过 netguard 域名校验的地址，防止脏数据把缩略图变成 SSRF 入口。
    """
    if limit <= 0:
        return 0
    conn = db.connect()
    db.init_db(conn)
    try:
        rows = conn.execute(
            """SELECT r.full_name FROM repos r
               JOIN events e ON e.repo_id = r.id
               WHERE r.hidden = 0 AND (r.og_image IS NULL OR r.og_image = '')
               GROUP BY r.id
               ORDER BY MAX(e.occurred_at) DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        if not rows:
            return 0
        try:
            images = gh.fetch_og_images([r["full_name"] for r in rows])
        except Exception as exc:
            logger.warning("[og] 拉取预览图失败（不影响采集）: %s", exc)
            return 0
        written = 0
        for full_name, url in images.items():
            if not netguard.is_safe_image_url(url):
                logger.warning("[og] 跳过非 GitHub 图片地址 %s -> %s", full_name, str(url)[:120])
                continue
            conn.execute("UPDATE repos SET og_image=? WHERE full_name=?", (url, full_name))
            written += 1
        conn.commit()
        if written:
            logger.info("[og] 回填预览图 %s 个", written)
        return written
    except Exception as exc:
        logger.warning("[og] 回填预览图失败（不影响采集）: %s", exc)
        return 0
    finally:
        conn.close()


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

def _seed_days(
    conn, gh: github.GitHub, days: int, per_day: int | None = None
) -> tuple[int, Exception | None]:
    """按天拉取「近 N 天创建 + 达标」的项目，返回 (新增数, 最后一个失败)。"""
    today = date.today()
    total = 0
    last_error: Exception | None = None
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
            last_error = exc
            print(f"[seed] {d} 失败: {exc}")
            logger.warning("[seed] %s 失败: %s", d, exc)
            _record_failure("seed-search", exc, conn)
        conn.commit()
        print(f"[seed] {d} 新增 {n}")
    return total, last_error


def cmd_seed(days: int, per_day: int | None = None) -> None:
    gh = github.GitHub()
    conn = db.connect()
    db.init_db(conn)
    try:
        total, last_error = _seed_days(conn, gh, days, per_day)
        db.meta_set(conn, "last_seed_at", db.now_iso())
        conn.commit()
        if last_error is not None:
            # 放在 last_seed_at 之后记录，保证失败在网页上仍然显示为"未恢复"
            _record_failure("seed-search", last_error, conn)
    except Exception as exc:
        logger.warning("[seed] 失败: %s", exc)
        _record_failure("seed", exc, conn)
        raise
    finally:
        conn.close()
    filled = _fill_og_images(gh, 500)
    suffix = f"，回填预览图 {filled} 个" if filled else ""
    print(f"[seed] 完成，共收录 {total} 个仓库{suffix}")


# ---------------- backfill（扩池 + 批量补中文）----------------

def cmd_backfill(days: int = 30, translate_total: int = 3000, batch: int = 200) -> None:
    """把种子池扩到 N 天，并批量补齐中文/标签（适合首次或夜间跑）。"""
    if not _acquire_lock():
        print("[backfill] 已有采集任务在跑，跳过")
        return
    conn = None
    gh: github.GitHub | None = None
    try:
        gh = github.GitHub()
        conn = db.connect()
        db.init_db(conn)
        db.meta_set(conn, "collecting", "1")
        conn.commit()

        seeded, seed_error = _seed_days(conn, gh, days)
        print(f"[backfill] 种子扩池完成，新增 {seeded} 个")

        filled = _fill_og_images(gh, 400)
        if filled:
            print(f"[backfill] 回填预览图 {filled} 个")

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
        if seed_error is not None:
            # 放在 last_wave_at 之后记录，保证部分失败仍然在网页上可见
            _record_failure("seed-search", seed_error, conn)
        print(f"[backfill] 完成：种子 +{seeded} · 中文 {done} · 标签 {tagged}")
    except Exception as exc:
        print(f"[backfill] 失败: {exc}")
        logger.warning("[backfill] 失败: %s", exc)
        if conn is not None:
            try:
                conn.rollback()
                db.meta_set(conn, "collecting", "0")
                conn.commit()
            except Exception as cleanup_exc:
                logger.warning("[backfill] 清理 collecting 标记失败: %s", cleanup_exc)
        _record_failure("backfill", exc, conn)
    finally:
        if conn is not None:
            conn.close()
        _release_lock()


# ---------------- update ----------------

def cmd_update(gh: github.GitHub | None = None, limit: int = 2000) -> int:
    gh = gh or github.GitHub()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM repos WHERE node_id IS NOT NULL ORDER BY last_seen_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        events = 0
        failed_chunks = 0
        cutoff = (datetime.now() - timedelta(hours=20)).strftime("%Y-%m-%dT%H")
        for start in range(0, len(rows), 100):
            chunk = rows[start : start + 100]
            try:
                nodes = gh.fetch_nodes([r["node_id"] for r in chunk])
            except Exception as exc:
                failed_chunks += 1
                print(f"[update] 批量查询失败: {exc}")
                logger.warning("[update] 批量查询失败: %s", exc)
                _record_failure("update", exc, conn)
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
                    conn.execute(
                        "UPDATE repos SET last_release_tag=? WHERE id=?", (tag, row["id"])
                    )
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
    except Exception as exc:
        logger.warning("[update] 失败: %s", exc)
        try:
            conn.rollback()
        except Exception as rollback_exc:
            logger.warning("[update] 回滚失败: %s", rollback_exc)
        _record_failure("update", exc, conn)
        raise
    finally:
        conn.close()
    filled = _fill_og_images(gh, 200)
    suffix = f"，回填预览图 {filled} 个" if filled else ""
    print(f"[update] 检查 {len(rows)} 个仓库，新增更新事件 {events}{suffix}")
    if failed_chunks:
        logger.warning("[update] 共 %s 批查询失败，已记录到最近失败信息", failed_chunks)
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
        except OSError as exc:
            logger.debug("清理过期采集锁失败: %s", exc)
        return False


def _release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("删除采集锁失败: %s", exc)


def _translated_total(conn) -> int:
    """已翻译仓库数（先提交，确保能看到翻译子进程的写入）。"""
    try:
        conn.commit()
    except Exception as exc:
        logger.debug("统计翻译数前提交失败: %s", exc)
    row = conn.execute(
        "SELECT COUNT(*) FROM repos WHERE description_zh IS NOT NULL AND description_zh <> ''"
    ).fetchone()
    return int(row[0]) if row else 0


def _translate_stage(conn, limit: int, timeout: int = 600) -> int:
    """补中文：源码模式放子进程跑（超时可杀），打包 exe 模式进程内跑。

    后台/计划任务环境下，长时间批量请求偶发卡在 TLS 握手或读响应上；
    子进程 + 超时终止可以保证整波采集不被拖死，剩下的留到下一波继续。
    打包成 exe 后 ``sys.executable`` 是 StarScout.exe，不能再当 python 用，
    否则会误启动第二个桌面窗口，所以直接在本进程里翻译。
    """
    import subprocess
    import sys

    before = _translated_total(conn)
    if getattr(sys, "frozen", False):
        logger.info("[wave] 打包运行模式：中文补全改为进程内执行")
        try:
            return max(0, llm.translate_pending(conn, limit))
        except Exception as exc:
            logger.warning("[wave] 进程内翻译失败: %s", exc)
            _record_failure("translate", exc, conn)
            return 0

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
        if proc.returncode not in (0, None):
            logger.warning("[wave] 翻译子进程退出码 %s", proc.returncode)
            _record_failure(
                "translate", RuntimeError(f"翻译子进程退出码 {proc.returncode}"), conn
            )
    except subprocess.TimeoutExpired:
        print(f"[wave] 翻译阶段超时（{timeout}s），已跳过，下波继续")
        logger.warning("[wave] 翻译阶段超时（%ss）", timeout)
        _record_failure("translate", RuntimeError(f"翻译阶段超时（{timeout}s）"), conn)
        try:
            if proc is not None:
                proc.kill()
        except Exception as kill_exc:
            logger.warning("[wave] 结束超时翻译子进程失败: %s", kill_exc)
    except Exception as exc:
        print(f"[wave] 翻译子进程失败: {exc}")
        logger.warning("[wave] 翻译子进程失败: %s", exc)
        _record_failure("translate", exc, conn)
    return max(0, _translated_total(conn) - before)


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
        search_error: Exception | None = None
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
                search_error = exc
                print(f"[wave] {d} 失败: {exc}")
                logger.warning("[wave] %s 搜索失败: %s", d, exc)
                _record_failure("wave-search", exc, conn)
            conn.commit()
            print(f"[wave] {d} 新增 {n}")
        db.meta_set(conn, "last_wave_at", db.now_iso())
        conn.commit()
        if search_error is not None:
            # 放在 last_wave_at 之后记录，保证部分失败仍然在网页上可见
            _record_failure("wave-search", search_error, conn)

        updated = cmd_update(gh, update_limit)
        translated = _translate_stage(conn, translate_limit)
        tagged = llm.tag_pending(conn, tag_limit) if tag_limit else 0
        db.meta_set(conn, "collecting", "0")
        db.meta_set(conn, "last_wave_finished_at", db.now_iso())
        conn.commit()
        print(
            f"[wave] 完成：新收录 {new} · 更新事件 {updated} · 中文补齐 {translated} · 标签补齐 {tagged}"
        )
    except Exception as exc:
        print(f"[wave] 失败: {exc}")
        logger.warning("[wave] 失败: %s", exc)
        if conn is not None:
            try:
                conn.rollback()
                db.meta_set(conn, "collecting", "0")
                conn.commit()
            except Exception as cleanup_exc:
                logger.warning("[wave] 清理 collecting 标记失败: %s", cleanup_exc)
        _record_failure("wave", exc, conn)
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
            except (ValueError, TypeError) as exc:
                logger.debug("解析上次采集时间失败: %s", exc)
        if age < max_age_hours:
            print(f"[startup] 数据 {age:.1f} 小时前更新，无需补跑")
            return False
        print(f"[startup] 数据已 {age:.1f} 小时未更新，后台补跑一次采集…")
        cmd_wave(translate_limit=120, update_limit=600, tag_limit=200)
        return True
    except Exception as exc:
        print(f"[startup] 补跑失败: {exc}")
        logger.warning("[startup] 补跑失败: %s", exc)
        _record_failure("startup", exc)
        return False


# ---------------- CLI ----------------

def main() -> None:
    config.setup_logging()
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
