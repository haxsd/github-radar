"""预览图批量缓存看门狗。

由 Start-Process 隐藏运行，持续监控 `radar.collect thumbs`：
- 子进程退出但还有未缓存仓库时自动重启；
- 长时间没有新增缓存文件时杀掉重启，并在直连/代理之间轮换；
- 连续多次无进展就停止并记录日志，避免无限重启。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / "data" / "logs" / "thumbs-watchdog.log"
WATCHDOG_LOCK = ROOT / "data" / "logs" / ".thumb-watchdog.lock"
CREATE_NO_WINDOW = 0x08000000
THUMB_WIDTHS = (240, 480)  # 批量预热只要求列表/日报尺寸；960 由详情页按需补


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    line = "[%s] %s" % (now(), message)
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _acquire_watchdog_lock() -> bool:
    WATCHDOG_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(WATCHDOG_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            if time.time() - WATCHDOG_LOCK.stat().st_mtime > 86400:
                WATCHDOG_LOCK.unlink(missing_ok=True)
                return _acquire_watchdog_lock()
        except OSError:
            pass
        return False


def _release_watchdog_lock() -> None:
    try:
        WATCHDOG_LOCK.unlink(missing_ok=True)
    except OSError:
        pass


def keep_system_awake() -> None:
    """Windows 下让系统在缓存完成前不自动睡眠（电池模式默认 10 分钟会睡）。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        if ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x1):
            log("已请求系统保持唤醒，缓存结束/看门狗退出后自动恢复")
        else:
            log("请求系统保持唤醒失败，夜间仍可能自动睡眠")
    except Exception as exc:
        log("请求系统保持唤醒异常：%s" % exc)


def pending_count(db_path: Path, thumbs: Path) -> int:
    """返回还没有 240/480 两档缓存的仓库数；数据库读不到时返回 -1。"""
    if not db_path.exists():
        return -1
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db_path.as_posix(), uri=True, timeout=10)
        try:
            ids = [
                int(row[0])
                for row in conn.execute(
                    "SELECT id FROM repos WHERE hidden=0 "
                    "AND og_image IS NOT NULL AND og_image <> ''"
                )
            ]
        finally:
            conn.close()
    except Exception as exc:
        log("读取数据库失败：%s" % exc)
        return -1
    pending = 0
    for repo_id in ids:
        if not all((thumbs / ("%s_%s.jpg" % (repo_id, width))).exists() for width in THUMB_WIDTHS):
            pending += 1
    return pending


def file_count(thumbs: Path) -> int:
    try:
        return sum(1 for _ in thumbs.glob("*.jpg"))
    except OSError:
        return 0


def start_worker(base: Path, use_proxy: bool):
    env = os.environ.copy()
    env["RADAR_DATA_DIR"] = str(base)
    env["PYTHONIOENCODING"] = "utf-8"
    if not use_proxy:
        env["RADAR_PROXY"] = ""  # 显式直连，覆盖 .env 里的代理
    else:
        env.pop("RADAR_PROXY", None)  # 让 worker 自己读取 .env 中的代理
    out_path = ROOT / "data" / "logs" / "thumbs-worker.out.log"
    err_path = ROOT / "data" / "logs" / "thumbs-worker.err.log"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_lock = base / "data" / ".thumb-prefetch.lock"
    try:
        thumb_lock.unlink(missing_ok=True)
    except OSError:
        pass
    with out_path.open("a", encoding="utf-8") as out, err_path.open("a", encoding="utf-8") as err:
        proc = subprocess.Popen(
            [str(PY), "-u", "-m", "radar.collect", "thumbs", "--limit", "20000"],
            cwd=str(ROOT),
            env=env,
            stdout=out,
            stderr=err,
            creationflags=CREATE_NO_WINDOW,
        )
    (ROOT / "data" / "logs" / "thumbs-worker.pid").write_text(str(proc.pid), encoding="ascii")
    log("启动缓存进程 pid=%s，代理=%s" % (proc.pid, "是" if use_proxy else "直连"))
    return proc


def stop_worker(proc, base: Path) -> None:
    if proc is not None and proc.poll() is None:
        log("停止缓存进程 pid=%s" % proc.pid)
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
    try:
        (base / "data" / ".thumb-prefetch.lock").unlink(missing_ok=True)
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="预览图批量缓存看门狗")
    parser.add_argument("--data-dir", default=os.environ.get("RADAR_DATA_DIR") or "")
    parser.add_argument("--interval", type=int, default=300, help="检查间隔秒数")
    parser.add_argument("--stall", type=int, default=1800, help="多少秒没有进展就重启")
    parser.add_argument("--max-hours", type=float, default=12.0)
    args = parser.parse_args()

    if not PY.exists():
        log("找不到虚拟环境 Python：%s" % PY)
        return 2
    if args.data_dir:
        base = Path(args.data_dir).expanduser()
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "GitHubRadar"
    db_path = base / "data" / "radar.db"
    thumbs = base / "data" / "thumbs"
    if not db_path.exists():
        log("数据库不存在：%s" % db_path)
        return 2
    if not _acquire_watchdog_lock():
        log("已有看门狗在运行，退出")
        return 0

    keep_system_awake()
    deadline = time.time() + max(1.0, args.max_hours) * 3600
    proc = None
    try:
        pending = pending_count(db_path, thumbs)
        current_files = file_count(thumbs)
        log("开始监控：待缓存 %s，现有图片 %s，数据库 %s" % (pending, current_files, db_path))
        if pending == 0:
            log("没有需要缓存的图片，退出")
            return 0

        proc = start_worker(base, use_proxy=True)
        last_files = current_files
        last_pending = pending
        last_change = time.time()
        stall_restarts = 0

        while time.time() < deadline:
            time.sleep(max(30, args.interval))
            pending = pending_count(db_path, thumbs)
            current_files = file_count(thumbs)
            if pending == 0:
                log("全部缓存完成，共 %s 张图片" % current_files)
                stop_worker(proc, base)
                return 0
            if pending < 0:
                log("数据库暂时读不到，继续等待")
                continue

            if proc.poll() is not None:
                log("缓存进程已退出 code=%s，待缓存 %s，准备重启" % (proc.returncode, pending))
                stop_worker(proc, base)
                time.sleep(15)
                proc = start_worker(base, use_proxy=True)
                last_files, last_pending, last_change = current_files, pending, time.time()
                continue

            if current_files > last_files or pending < last_pending:
                log("进度：待缓存 %s，图片 %s" % (pending, current_files))
                last_files, last_pending, last_change = current_files, pending, time.time()
                stall_restarts = 0
                continue

            if time.time() - last_change >= args.stall:
                stall_restarts += 1
                use_proxy = stall_restarts % 2 == 1
                log(
                    "超过 %ss 没有进展（待缓存 %s），重启缓存进程，模式=%s"
                    % (args.stall, pending, "代理" if use_proxy else "直连")
                )
                stop_worker(proc, base)
                time.sleep(10)
                proc = start_worker(base, use_proxy=use_proxy)
                last_files, last_pending, last_change = current_files, pending, time.time()
                if stall_restarts >= 6:
                    log("连续多次无进展，停止看门狗")
                    stop_worker(proc, base)
                    return 1

        log("达到最长运行时间，停止缓存进程")
        stop_worker(proc, base)
        return 0
    finally:
        _release_watchdog_lock()


if __name__ == "__main__":
    raise SystemExit(main())
