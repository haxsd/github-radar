# -*- coding: utf-8 -*-
"""数据目录 / 便携模式 / 版本信息测试。

不依赖打包环境：只测试纯函数在 frozen / portable / env override 下的路径决策。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from radar import __version__, config


class TestDataDirResolution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.program = Path(self.tmp.name) / "program"
        self.program.mkdir(parents=True, exist_ok=True)

    def _env(self, **overrides):
        env = {k: v for k, v in os.environ.items() if k not in ("RADAR_DATA_DIR", "RADAR_PORTABLE", "LOCALAPPDATA")}
        env.update(overrides)
        return mock.patch.dict(os.environ, env, clear=True)

    def test_source_mode_uses_program_root(self):
        with self._env():
            self.assertEqual(config._default_base_dir(self.program), self.program)

    def test_frozen_uses_localappdata(self):
        with self._env(LOCALAPPDATA=str(self.tmp.name)), mock.patch.object(
            sys, "frozen", True, create=True
        ):
            self.assertEqual(config._default_base_dir(self.program), Path(self.tmp.name) / "GitHubRadar")

    def test_portable_flag_uses_program_root(self):
        (self.program / "portable.flag").write_text("", encoding="utf-8")
        with self._env(LOCALAPPDATA=str(self.tmp.name)), mock.patch.object(
            sys, "frozen", True, create=True
        ):
            self.assertEqual(config._default_base_dir(self.program), self.program)

    def test_env_portable_uses_program_root(self):
        with self._env(RADAR_PORTABLE="1", LOCALAPPDATA=str(self.tmp.name)), mock.patch.object(
            sys, "frozen", True, create=True
        ):
            self.assertEqual(config._default_base_dir(self.program), self.program)

    def test_data_dir_override_wins(self):
        target = Path(self.tmp.name) / "custom-data"
        with self._env(RADAR_DATA_DIR=str(target), LOCALAPPDATA=str(self.tmp.name)), mock.patch.object(
            sys, "frozen", True, create=True
        ):
            self.assertEqual(config._default_base_dir(self.program), target)

    def test_data_dir_is_base_data_subdir(self):
        with self._env(), mock.patch.object(sys, "frozen", True, create=True), mock.patch.dict(
            os.environ, {"LOCALAPPDATA": self.tmp.name}, clear=False
        ):
            base = config._default_base_dir(self.program)
            self.assertEqual(base, Path(self.tmp.name) / "GitHubRadar")
            self.assertEqual(base / "data", Path(self.tmp.name) / "GitHubRadar" / "data")

    def test_frozen_legacy_layout_migrates(self):
        legacy = Path(self.tmp.name) / "base"
        legacy.mkdir()
        (legacy / "radar.db").write_bytes(b"db")
        (legacy / "radar.db-wal").write_bytes(b"wal")
        (legacy / "radar.db-shm").write_bytes(b"shm")
        (legacy / "thumbs").mkdir()
        (legacy / "thumbs" / "1_240.jpg").write_bytes(b"jpg")
        data = legacy / "data"
        originals = (config.BASE_DIR, config.DATA_DIR, config.DB_PATH, config.ENV_PATH)
        try:
            config.BASE_DIR = legacy
            config.DATA_DIR = data
            config.DB_PATH = data / "radar.db"
            config.ENV_PATH = legacy / ".env"
            with mock.patch.object(sys, "frozen", True, create=True):
                config.migrate_legacy_layout()
            self.assertTrue((data / "radar.db").exists())
            self.assertTrue((data / "radar.db-wal").exists(), "WAL 边车文件必须一起迁移")
            self.assertTrue((data / "radar.db-shm").exists(), "SHM 边车文件必须一起迁移")
            self.assertTrue((data / "thumbs" / "1_240.jpg").exists())
            self.assertFalse((legacy / "radar.db").exists())
        finally:
            config.BASE_DIR, config.DATA_DIR, config.DB_PATH, config.ENV_PATH = originals

    def test_ensure_dirs_creates_data_and_logs(self):
        original = config.DATA_DIR
        try:
            config.DATA_DIR = Path(self.tmp.name) / "fresh"
            config.ensure_dirs()
            self.assertTrue((config.DATA_DIR / "logs").is_dir())
        finally:
            config.DATA_DIR = original


class TestVersion(unittest.TestCase):
    def test_version_is_product_version(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(config.APP_VERSION, __version__)


if __name__ == "__main__":
    unittest.main()
