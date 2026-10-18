"""后台批量补翻译：每批一个小进程，超时就跳过，避免长连接卡死。

由 translate_loop.bat 在隐藏窗口里调用。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / "data" / "logs" / "collect.log"

BATCH = 120
MAX_BATCHES = 120


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")


def main() -> None:
    try:
        from radar import db
    except Exception as exc:
        log(f"[loop] 无法导入 radar: {exc}")
        return

    total = 0
    for i in range(MAX_BATCHES):
        try:
            proc = subprocess.run(
                [str(PY), "-u", "-m", "radar.collect", "translate", "--limit", str(BATCH)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            log(f"[loop] 第 {i + 1} 批超时，跳过")
            time.sleep(3)
            continue
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
            time.sleep(2)
            # 连续两批都没新东西才认为补完了
            if i > 0 and total == 0:
                break
            continue
        time.sleep(1)

    conn = db.connect()
    left = len(db.untranslated(conn, 999999))
    conn.close()
    log(f"[loop] 翻译循环结束：本次 {total} 条，剩余未翻译 {left}")


if __name__ == "__main__":
    main()
