"""桌面应用入口：本地服务 + 系统托盘 + Edge 应用窗口。

源码运行：python desktop.py
打包运行：StarScout.exe
命令行：
  StarScout.exe --version
  StarScout.exe --collect wave        # 无窗口跑采集（适合任务计划）
  StarScout.exe --import-data PATH    # 导入旧版 data / .env
  StarScout.exe --portable            # 强制便携模式（数据放 exe 旁边）
  StarScout.exe --minimized           # 启动到托盘，不打开窗口
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# 这些参数会改变数据目录，必须在导入 config 之前处理
_RAW_ARGS = sys.argv[1:]
for _index, _arg in enumerate(_RAW_ARGS):
    if _arg == "--portable":
        os.environ["RADAR_PORTABLE"] = "1"
    elif _arg == "--data-dir" and _index + 1 < len(_RAW_ARGS):
        os.environ["RADAR_DATA_DIR"] = _RAW_ARGS[_index + 1]
    elif _arg.startswith("--data-dir="):
        os.environ["RADAR_DATA_DIR"] = _arg.split("=", 1)[1]

from radar import __version__, config, db, web  # noqa: E402

logger = logging.getLogger(__name__)

EDGE_CANDIDATES = (
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
)
CREATE_NO_WINDOW = 0x08000000

_EDGE_PROCS: list[subprocess.Popen] = []
_SERVER = None
_TRAY = None
_QUITTING = threading.Event()
_MUTEX_HANDLE = None


# ---------------- 进程/窗口基础 ----------------

def _port_in_use(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((probe_host, port)) == 0


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


def _fatal(message: str) -> None:
    """窗口程序没有控制台，用 MessageBox 提示；源码运行仍打印。"""
    logger.error(message)
    if getattr(sys, "frozen", False) and os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(0, message, "GitHub 中文雷达", 0x10)
        except Exception:
            pass
    else:
        print(message, file=sys.stderr)


def _redirect_frozen_streams() -> None:
    """windowed 打包版没有 stdout/stderr，重定向到 app.log，保证 print 不报错。"""
    if not getattr(sys, "frozen", False):
        return
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        config.ensure_dirs()
        stream = open(config.DATA_DIR / "logs" / "app.log", "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _acquire_single_instance() -> bool:
    """打包版只允许一个实例；返回 False 表示已有实例。"""
    global _MUTEX_HANDLE
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\GitHubRadar.SingleInstance")
    if not handle:
        return True
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _MUTEX_HANDLE = handle
    return True


# ---------------- 窗口 / 托盘 ----------------

def _open_window(url: str) -> subprocess.Popen | None:
    edge = _find_edge()
    if not edge:
        webbrowser.open(url)
        return None
    profile = config.DATA_DIR / "edge-profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
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
    except OSError as exc:
        logger.warning("启动 Edge 应用窗口失败，改用默认浏览器: %s", exc)
        webbrowser.open(url)
        return None
    _EDGE_PROCS.append(proc)
    return proc


def _tray_image():
    from PIL import Image

    path = config.assets_dir() / "icon.png"
    try:
        with Image.open(path) as img:
            # copy 后关闭文件句柄，避免托盘长期占用安装目录里的图标文件
            return img.copy()
    except Exception:
        image = Image.new("RGBA", (64, 64), (91, 140, 255, 255))
        return image


def _spawn_collect(command: str = "wave") -> None:
    """托盘「立即采集」：后台跑，不弹窗口，输出写 collect.log。"""
    log_path = config.DATA_DIR / "logs" / "collect.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        args = [sys.executable, "--collect", command]
    else:
        args = [sys.executable, "-m", "radar.collect", command]
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            subprocess.Popen(
                args,
                cwd=str(config.ROOT),
                stdout=log,
                stderr=log,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
    except OSError as exc:
        logger.warning("启动采集失败: %s", exc)


def _run_tray(url: str, open_initial_window: bool) -> None:
    import pystray

    if open_initial_window:
        _open_window(url)

    def on_open(icon, item):
        _open_window(url)

    def on_collect(icon, item):
        _spawn_collect("wave")

    def on_data_dir(icon, item):
        try:
            os.startfile(str(config.BASE_DIR))
        except OSError:
            pass

    def on_quit(icon, item):
        _QUITTING.set()
        try:
            icon.stop()
        except Exception:
            pass

    menu = pystray.Menu(
        pystray.MenuItem("打开界面", on_open, default=True),
        pystray.MenuItem("立即采集", on_collect),
        pystray.MenuItem("打开数据目录", on_data_dir),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", on_quit),
    )
    global _TRAY
    _TRAY = pystray.Icon(
        "GitHubRadar",
        _tray_image(),
        f"GitHub 中文雷达 v{__version__}",
        menu,
    )
    logger.info("托盘已启动，数据目录：%s", config.DATA_DIR)
    _TRAY.run()


# ---------------- 服务 / 清理 ----------------

def _start_server() -> bool:
    global _SERVER
    if _port_in_use(config.WEB_HOST, config.WEB_PORT):
        return True
    from werkzeug.serving import make_server

    try:
        _SERVER = make_server(config.WEB_HOST, config.WEB_PORT, web.app, threaded=True)
    except OSError as exc:
        _fatal(f"本地服务启动失败：{exc}")
        return False
    threading.Thread(target=_SERVER.serve_forever, name="flask-server", daemon=True).start()
    threading.Thread(target=web._startup_catchup, daemon=True).start()
    web._start_thumb_warmer()
    return _wait_port(config.WEB_HOST, config.WEB_PORT)


def _cleanup() -> None:
    for proc in _EDGE_PROCS:
        try:
            if proc.poll() is None:
                proc.terminate()
        except OSError:
            pass
    if _TRAY is not None:
        try:
            _TRAY.stop()
        except Exception:
            pass
    if _SERVER is not None:
        try:
            _SERVER.shutdown()
        except Exception:
            pass


# ---------------- 命令行辅助 ----------------

def _import_data(source: str) -> int:
    src = Path(source).expanduser().resolve()
    if not src.exists():
        _fatal(f"导入目录不存在：{src}")
        return 2
    data_src = src / "data" if (src / "data").is_dir() else src
    config.ensure_dirs()
    shutil.copytree(data_src, config.DATA_DIR, dirs_exist_ok=True)
    # 旧目录里可能残留采集锁，导入后不要让新程序误以为有任务在跑
    (config.DATA_DIR / ".collect.lock").unlink(missing_ok=True)
    env_src = src / ".env"
    if not env_src.exists() and (data_src / ".env").exists():
        env_src = data_src / ".env"
    if env_src.exists():
        shutil.copy2(env_src, config.ENV_PATH)
    print(f"已导入到：{config.DATA_DIR}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="GitHub 中文雷达", description="本地 GitHub 项目雷达")
    parser.add_argument("--version", action="store_true", help="显示版本与数据目录后退出")
    parser.add_argument("--collect", nargs=argparse.REMAINDER, help="无窗口跑采集，如 --collect wave")
    parser.add_argument("--import-data", metavar="PATH", help="导入旧版 data / .env")
    parser.add_argument("--data-dir", metavar="PATH", help="自定义数据目录（本次运行）")
    parser.add_argument("--portable", action="store_true", help="便携模式：数据放 exe 旁边")
    parser.add_argument("--minimized", action="store_true", help="启动到托盘，不打开窗口")
    parser.add_argument("--no-tray", action="store_true", help="不启动托盘")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    config.ensure_dirs()
    config.migrate_legacy_layout()
    _redirect_frozen_streams()
    config.setup_logging()

    if args.version:
        print(f"GitHub 中文雷达 v{__version__}")
        print(f"frozen: {bool(getattr(sys, 'frozen', False))}")
        print(f"data: {config.DATA_DIR}")
        print(f"env: {config.ENV_PATH}")
        return 0

    if args.collect is not None:
        if not args.collect:
            print("用法：StarScout.exe --collect wave|update|thumbs ...")
            return 2
        sys.argv = [sys.argv[0], *args.collect]
        from radar import collect

        collect.main()
        return 0

    if args.import_data:
        return _import_data(args.import_data)

    conn = db.connect()
    db.init_db(conn)
    conn.close()

    url = f"http://{config.WEB_HOST}:{config.WEB_PORT}"

    if not _acquire_single_instance():
        logger.info("已有实例在运行，打开现有窗口")
        _wait_port(config.WEB_HOST, config.WEB_PORT, timeout=10)
        _open_window(url)
        return 0

    if not _start_server():
        return 1

    tray_enabled = not args.no_tray and (
        bool(getattr(sys, "frozen", False)) or os.environ.get("RADAR_TRAY") == "1"
    )
    if tray_enabled:
        try:
            _run_tray(url, open_initial_window=not args.minimized)
        except Exception as exc:
            logger.warning("托盘启动失败，退回窗口模式: %s", exc)
            if not args.minimized:
                _open_window(url)
    elif not args.minimized:
        _open_window(url)

    if not tray_enabled:
        if args.minimized:
            # 无托盘但要求后台启动：保持服务运行，直到 Ctrl+C / 进程被结束
            while not _QUITTING.wait(3600):
                pass
        else:
            # 源码/无托盘：窗口关掉就退出（保持原有行为）
            while any(proc.poll() is None for proc in _EDGE_PROCS):
                time.sleep(0.8)
        _cleanup()
        return 0

    _cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
