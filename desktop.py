"""桌面应用入口：启动本地服务 + 用 Edge 应用窗口（无地址栏）打开。

开发运行：python desktop.py
打包运行：dist/StarScout/StarScout.exe

没有 Edge 时退回默认浏览器；端口已被占用则直接连已有服务。
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

from radar import config, db, web

EDGE_CANDIDATES = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
)


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _wait_port(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_in_use(host, port):
            return True
        time.sleep(0.2)
    return False


def _find_edge() -> str | None:
    for raw in EDGE_CANDIDATES:
        path = os.path.expandvars(raw)
        if os.path.exists(path):
            return path
    return shutil.which("msedge")


def main() -> None:
    config.ensure_dirs()
    conn = db.connect()
    db.init_db(conn)
    conn.close()

    url = f"http://{config.WEB_HOST}:{config.WEB_PORT}"
    if not _port_in_use(config.WEB_HOST, config.WEB_PORT):
        threading.Thread(
            target=lambda: web.app.run(
                host=config.WEB_HOST, port=config.WEB_PORT, debug=False, use_reloader=False, threaded=True
            ),
            daemon=True,
        ).start()
        threading.Thread(target=web._startup_catchup, daemon=True).start()
        web._start_thumb_warmer()
        _wait_port(config.WEB_HOST, config.WEB_PORT)

    edge = _find_edge()
    if edge:
        profile = config.DATA_DIR / "edge-profile"
        profile.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [
                edge,
                f"--app={url}",
                "--window-size=1340,940",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            close_fds=True,
        )
        try:
            while proc.poll() is None:
                time.sleep(0.8)
        except KeyboardInterrupt:
            pass
        return

    # 没有 Edge：用默认浏览器
    webbrowser.open(url)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
