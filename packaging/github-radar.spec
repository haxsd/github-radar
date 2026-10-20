# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：把应用打成 dist/StarScout（onedir，带版本信息/图标）。"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "radar" / "templates"), "radar/templates"),
        (str(ROOT / "radar" / "static"), "radar/static"),
        (str(ROOT / "radar" / "demo_data.json"), "radar"),
        (str(ROOT / "assets" / "icon.png"), "assets"),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "README.md"), "."),
        (str(ROOT / ".env.example"), "."),
        (str(ROOT / "packaging" / "使用说明.txt"), "."),
    ],
    hiddenimports=[
        "pystray",
        "pystray._win32",
        "PIL.Image",
        "werkzeug.serving",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StarScout",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(ROOT / "assets" / "icon.ico")],
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StarScout",
)
