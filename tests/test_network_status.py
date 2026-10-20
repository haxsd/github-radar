# -*- coding: utf-8 -*-
"""网络状态检测与代理配置测试。

全部离线：网络检测的底层函数被 mock，不访问 GitHub / 模型接口。
"""

from __future__ import annotations

import unittest
from unittest import mock

from radar import config, network, web


def _ok(latency=12, status=200):
    return {"ok": True, "latency_ms": latency, "status": status, "message": "可连接"}


def _fail(message="连接超时"):
    return {"ok": False, "latency_ms": 6000, "message": message, "error": "Timeout"}


class TestProxyConfig(unittest.TestCase):
    def test_radar_proxy_helpers(self):
        original = config.RADAR_PROXY
        try:
            config.RADAR_PROXY = ""
            self.assertIsNone(config.radar_proxies())
            config.RADAR_PROXY = "127.0.0.1:7897"
            self.assertEqual(
                config.radar_proxies(),
                {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"},
            )
            config.RADAR_PROXY = "http://127.0.0.1:7890"
            self.assertEqual(config.radar_proxies()["https"], "http://127.0.0.1:7890")
        finally:
            config.RADAR_PROXY = original

    def test_llm_proxy_helpers(self):
        original = config.LLM_PROXY
        try:
            config.LLM_PROXY = ""
            self.assertIsNone(config.llm_proxies())
            config.LLM_PROXY = "http://127.0.0.1:7897"
            self.assertEqual(config.llm_proxies()["http"], "http://127.0.0.1:7897")
        finally:
            config.LLM_PROXY = original

    def test_mask_proxy_hides_credentials(self):
        self.assertEqual(
            config.mask_proxy("http://user:secret@127.0.0.1:7897"), "http://127.0.0.1:7897"
        )
        self.assertEqual(config.mask_proxy(""), "")


class TestNetworkChecks(unittest.TestCase):
    def setUp(self):
        network._reset_cache()
        self.addCleanup(network._reset_cache)

    def test_check_all_levels_and_cache(self):
        ok_checks = {
            "_check_github": _ok(20),
            "_check_images": _ok(30),
            "_check_llm": _ok(40),
        }
        with mock.patch.multiple(network, **{k: mock.Mock(return_value=dict(v)) for k, v in ok_checks.items()}):
            first = network.check_all()
        self.assertEqual(first["level"], "ok")
        self.assertFalse(first["cached"])

        # 第二次应命中缓存（即使底层检查变成失败）
        with mock.patch.multiple(
            network,
            _check_github=mock.Mock(return_value=_fail()),
            _check_images=mock.Mock(return_value=_fail()),
            _check_llm=mock.Mock(return_value=_fail()),
        ):
            cached = network.check_all()
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["level"], "ok")

        # 强制刷新后变为 offline
        with mock.patch.multiple(
            network,
            _check_github=mock.Mock(return_value=_fail()),
            _check_images=mock.Mock(return_value=_fail()),
            _check_llm=mock.Mock(return_value=_fail()),
        ):
            refreshed = network.check_all(force=True)
        self.assertFalse(refreshed["cached"])
        self.assertEqual(refreshed["level"], "offline")

    def test_degraded_when_partial_failure(self):
        with mock.patch.multiple(
            network,
            _check_github=mock.Mock(return_value=_ok()),
            _check_images=mock.Mock(return_value=_fail("图片 CDN 不可达")),
            _check_llm=mock.Mock(return_value=_ok()),
        ):
            result = network.check_all(force=True)
        self.assertEqual(result["level"], "degraded")
        self.assertIn("proxy", result)
        self.assertIn("radar", result["proxy"])

    def test_unconfigured_llm_does_not_mark_offline(self):
        with mock.patch.multiple(
            network,
            _check_github=mock.Mock(return_value=_ok()),
            _check_images=mock.Mock(return_value=_ok()),
            _check_llm=mock.Mock(return_value={"ok": False, "configured": False, "message": "未配置"}),
        ):
            result = network.check_all(force=True)
        self.assertEqual(result["level"], "ok")

    def test_github_warning_on_invalid_token(self):
        with mock.patch.object(
            network,
            "_probe",
            return_value={"ok": True, "latency_ms": 15, "status": 401},
        ), mock.patch.object(config, "GITHUB_TOKEN", "bad-token"):
            result = network._check_github()
        self.assertTrue(result["ok"])
        self.assertTrue(result["warning"])
        self.assertIn("401", result["message"])

    def test_images_failure_message(self):
        with mock.patch.object(
            network, "_probe", return_value=_fail("连接超时")
        ), mock.patch.object(config, "RADAR_PROXY", ""):
            result = network._check_images()
        self.assertFalse(result["ok"])
        self.assertIn("图片 CDN 不可达", result["message"])
        self.assertIn("RADAR_PROXY", result["hint"])

    def test_slow_target_marks_warning_and_degraded(self):
        slow = {"ok": True, "latency_ms": 12000, "status": 200}
        with mock.patch.object(network, "_probe", return_value=dict(slow)), mock.patch.object(
            config, "RADAR_PROXY", ""
        ):
            images = network._check_images()
        self.assertTrue(images["ok"])
        self.assertTrue(images["warning"])
        self.assertIn("较慢", images["message"])

        with mock.patch.multiple(
            network,
            _check_github=mock.Mock(return_value=_ok()),
            _check_images=mock.Mock(return_value=dict(images)),
            _check_llm=mock.Mock(return_value=_ok()),
        ):
            result = network.check_all(force=True)
        self.assertEqual(result["level"], "degraded")

    def test_llm_probe_uses_models_endpoint_with_auth(self):
        original = (config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_PROVIDER)
        try:
            config.LLM_BASE_URL = "https://api.deepseek.com"
            config.LLM_API_KEY = "test-key"
            config.LLM_PROVIDER = "deepseek"
            with mock.patch.object(
                network,
                "_probe",
                return_value={"ok": True, "latency_ms": 10, "status": 200},
            ) as probe:
                network._check_llm()
            args, kwargs = probe.call_args
            self.assertTrue(args[0].endswith("/models"), args[0])
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        finally:
            config.LLM_BASE_URL, config.LLM_API_KEY, config.LLM_PROVIDER = original

    def test_llm_unconfigured(self):
        original = config.LLM_BASE_URL
        try:
            config.LLM_BASE_URL = ""
            result = network._check_llm()
        finally:
            config.LLM_BASE_URL = original
        self.assertFalse(result["ok"])
        self.assertFalse(result["configured"])


class TestNetworkEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()
        network._reset_cache()
        self.addCleanup(network._reset_cache)

    def test_status_endpoint_passes_force_flag(self):
        fixture = {
            "checked_at": "2026-10-20T10:00:00+0800",
            "level": "ok",
            "cached": False,
            "targets": {"github": _ok(), "images": _ok(), "llm": _ok()},
            "proxy": {"radar": "直连", "llm": "直连", "system": "未设置"},
        }
        with mock.patch.object(web.network, "check_all", return_value=fixture) as check:
            resp = self.client.get("/api/network/status")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json(), fixture)
            check.assert_called_once_with(force=False)
        with mock.patch.object(web.network, "check_all", return_value=fixture) as check:
            self.client.get("/api/network/status?refresh=1")
            check.assert_called_once_with(force=True)

    def test_status_endpoint_never_500(self):
        with mock.patch.object(web.network, "check_all", side_effect=RuntimeError("boom")):
            resp = self.client.get("/api/network/status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["level"], "unknown")


class TestSettingsProxySave(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def _save(self, payload):
        return self.client.post(
            "/api/settings",
            json=payload,
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

    def test_proxy_is_written_to_env(self):
        with mock.patch.object(config, "save_env") as save_env, mock.patch.object(
            config, "github_token_status", return_value="env"
        ):
            resp = self._save(
                {
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "proxy": "http://127.0.0.1:7897",
                }
            )
        self.assertEqual(resp.status_code, 200)
        values = save_env.call_args[0][0]
        self.assertEqual(values.get("RADAR_PROXY"), "http://127.0.0.1:7897")

    def test_proxy_direct_clears_value(self):
        with mock.patch.object(config, "save_env") as save_env, mock.patch.object(
            config, "github_token_status", return_value="env"
        ):
            resp = self._save(
                {
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "proxy": "direct",
                }
            )
        self.assertEqual(resp.status_code, 200)
        values = save_env.call_args[0][0]
        self.assertEqual(values.get("RADAR_PROXY"), "")

    def test_proxy_newline_rejected(self):
        with mock.patch.object(config, "save_env") as save_env:
            resp = self._save(
                {
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "proxy": "http://127.0.0.1:7897\nEVIL=1",
                }
            )
        self.assertEqual(resp.status_code, 400)
        save_env.assert_not_called()


if __name__ == "__main__":
    unittest.main()
