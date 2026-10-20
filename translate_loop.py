"""后台批量补翻译：每批一个小进程，超时就跳过，避免长连接卡死。

由 translate_loop.bat 在隐藏窗口里调用；日志直接打印到 stdout，
由批处理重定向到 data/logs/translate_loop.log，避免和 collect.log 抢同一个文件句柄。
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"

BATCH = 120
MAX_BATCHES = 120
MAX_EMPTY_BATCHES = 2


def log(msg: str) -> None:
    # 只写 stdout：调用方负责重定向；不自己打开日志文件，避免 Windows 文件锁冲突
    print(msg, flush=True)


def main() -> None:
    try:
        from radar import db
    except Exception as exc:
        log(f"[loop] 无法导入 radar: {exc}")
        return

    total = 0
    empty_streak = 0
    for i in range(MAX_BATCHES):
        try:
            proc = subprocess.run(
                [str(PY), "-u", "-m", "radar.collect", "translate", "--limit", str(BATCH)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired:
            empty_streak += 1
            log(f"[loop] 第 {i + 1} 批超时，跳过")
            if empty_streak >= MAX_EMPTY_BATCHES:
                break
            time.sleep(3)
            continue
        except OSError as exc:
            log("[loop] 无法启动翻译进程：%s" % exc)
            break
        out = (proc.stdout or "") + (proc.stderr or "")
        done = 0
        for line in out.splitlines():
            if "[translate] 完成" in line:
                try:
                    done = int(line.split("完成")[1].split("条")[0].strip())
                except Exception:
                    done = 0
        total += done
        log(f"[loop] 第 {i + 1} 批完成 {done} 条（累计 {total}）")
        if done == 0:
            # 连续几批都没有新内容才结束；不能只看累计 total，
            # 否则翻译过一批之后就永远停不下来，会空跑满 MAX_BATCHES 次。
            empty_streak += 1
            if empty_streak >= MAX_EMPTY_BATCHES:
                break
            time.sleep(2)
            continue
        empty_streak = 0
        time.sleep(1)

    conn = db.connect()
    try:
        left = len(db.untranslated(conn, 999999))
    finally:
        conn.close()
    log(f"[loop] 翻译循环结束：本次 {total} 条，剩余未翻译 {left}")


if __name__ == "__main__":
    main()
