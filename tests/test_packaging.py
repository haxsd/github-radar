# -*- coding: utf-8 -*-
"""打包相关文件一致性测试（不运行 PyInstaller/Inno，CI 可跑）。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from radar import __version__

ROOT = Path(__file__).resolve().parent.parent


class TestPackagingFiles(unittest.TestCase):
    def test_installer_version_matches(self):
        iss = (ROOT / "packaging" / "github-radar.iss").read_text(encoding="utf-8")
        self.assertIn(f'#define MyAppVersion "{__version__}"', iss)
        self.assertIn("PrivilegesRequired=lowest", iss)
        self.assertIn("GitHubRadar-Setup-{#MyAppVersion}", iss)
        self.assertIn("{localappdata}\\GitHubRadar", iss)

    def test_version_info_matches(self):
        info = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
        self.assertIn(f"filevers=({', '.join(__version__.split('.') + ['0'])})", info)
        self.assertIn(f"ProductVersion', '{__version__}'", info)

    def test_pyinstaller_spec(self):
        spec = (ROOT / "packaging" / "github-radar.spec").read_text(encoding="utf-8")
        for marker in ("radar/templates", "radar/static", "pystray", "version_info.txt"):
            self.assertIn(marker, spec)
        self.assertIn("console=False", spec)
        self.assertIn("upx=False", spec)

    def test_build_scripts(self):
        app_bat = (ROOT / "build_app.bat").read_text(encoding="utf-8")
        self.assertIn("packaging\\github-radar.spec", app_bat)
        installer_bat = (ROOT / "build_installer.bat").read_text(encoding="utf-8")
        self.assertIn("packaging\\github-radar.iss", installer_bat)
        self.assertIn("ISCC", installer_bat)

    def test_requirements_include_tray(self):
        req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("pystray", req)

    def test_desktop_cli(self):
        desktop = (ROOT / "desktop.py").read_text(encoding="utf-8")
        for flag in ("--collect", "--import-data", "--portable", "--minimized", "--data-dir"):
            self.assertIn(flag, desktop)

    def test_readme_mentions_install(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("GitHubRadar-Setup-", readme)
        self.assertIn("%LOCALAPPDATA%", readme)
        readme_en = (ROOT / "README-EN.md").read_text(encoding="utf-8")
        self.assertIn("GitHubRadar-Setup-", readme_en)
        notes = (ROOT / "packaging" / "使用说明.txt").read_text(encoding="utf-8")
        self.assertIn("--import-data", notes)


if __name__ == "__main__":
    unittest.main()
