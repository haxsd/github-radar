"""Windows 开机自启动开关（注册表 HKCU Run）。

安装版写入：
    "C:\\...\\StarScout.exe" --minimized

源码版写入 pythonw + desktop.py，方便开发环境也能测试。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # 非 Windows
    winreg = None  # type: ignore[assignment]

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "GitHubRadar"


def supported() -> bool:
    return os.name == "nt" and winreg is not None


def _pythonw() -> Path:
    exe = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return exe
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def command() -> str:
    """当前程序对应的自启动命令行。"""
    exe = _pythonw()
    if getattr(sys, "frozen", False):
        return f'"{exe}" --minimized'
    script = Path(__file__).resolve().parent.parent / "desktop.py"
    return f'"{exe}" "{script}" --minimized'


def enabled() -> bool:
    if not supported():
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(str(value).strip())
    except (FileNotFoundError, OSError):
        return False


def set_enabled(value: bool) -> bool:
    """开启/关闭自启动，返回最终状态；失败抛 RuntimeError。"""
    if not supported():
        raise RuntimeError("当前系统不支持开机自启动设置")
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if value:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return enabled()
    except OSError as exc:
        raise RuntimeError("写入开机启动项失败：%s" % exc) from exc
