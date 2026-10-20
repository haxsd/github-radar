# -*- coding: utf-8 -*-
"""设置页写入权限与 /api/settings 接口行为测试。

全部离线：save_env 一律 mock，绝不写真实 .env；远程测试用 Flask test_client
的 environ_base 伪造 REMOTE_ADDR，并把 requests / token 读取替换成"一旦调用就失败"。
"""

from __future__ import annotations

import unittest
from unittest import mock

from radar import config, web

REMOTE = "203.0.113.9"
LOOPBACK = "127.0.0.1"
ADMIN_TOKEN = "s3cret"

# /api/settings 的合法载荷（不含任何真实密钥）
VALID_SETTINGS = {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "json_mode": True,
    "disable_thinking": True,
}


class TestCanWriteSettings(unittest.TestCase):
    """纯函数 web._can_write_settings(remote_addr, provided_token=None)。"""

    def test_loopback_allowed_without_token(self):
        for addr in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"):
            with self.subTest(addr=addr):
                self.assertTrue(web._can_write_settings(addr), f"本机地址应放行：{addr}")

    def test_non_loopback_denied_without_token(self):
        for addr in ("192.168.1.5", REMOTE):
            with self.subTest(addr=addr):
                self.assertFalse(
                    web._can_write_settings(addr), f"非本机地址无口令时必须拒绝：{addr}"
                )

    def test_admin_token_allows_remote(self):
        with mock.patch.object(config, "WEB_ADMIN_TOKEN", ADMIN_TOKEN, create=True):
            self.assertTrue(web._can_write_settings(REMOTE, ADMIN_TOKEN))
            self.assertFalse(web._can_write_settings(REMOTE, "wrong"))

    def test_non_ascii_admin_token_is_safe(self):
        """中文/非 ASCII 口令不能因 hmac.compare_digest 的 str 限制而抛异常。"""
        with mock.patch.object(config, "WEB_ADMIN_TOKEN", "密码123", create=True):
            self.assertTrue(web._can_write_settings(REMOTE, "密码123"))
            self.assertFalse(web._can_write_settings(REMOTE, "口令"))
            self.assertFalse(web._can_write_settings(REMOTE, "wrong"))


class TestSettingsEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def _post(self, path, payload, remote_addr):
        return self.client.post(
            path, json=payload, environ_base={"REMOTE_ADDR": remote_addr}
        )

    def test_security_headers_and_api_no_store(self):
        page = self.client.get("/")
        self.assertEqual(page.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(page.headers.get("X-Frame-Options"), "DENY")
        api = self.client.get("/api/stats")
        self.assertEqual(api.headers.get("Cache-Control"), "no-store")

    def test_json_keeps_chinese_readable(self):
        resp = self.client.get("/api/categories")
        self.assertIn("application/json", resp.headers.get("Content-Type", ""))
        text = resp.get_data(as_text=True)
        self.assertNotIn("\\u", text, "中文标签不应被转义成 \\uXXXX")

    def test_remote_save_without_token_forbidden(self):
        with mock.patch.object(config, "WEB_ADMIN_TOKEN", "", create=True), mock.patch(
            "radar.web.config.save_env"
        ) as save_env, mock.patch(
            "radar.web.config.github_token_status", return_value="env"
        ):
            resp = self._post("/api/settings", dict(VALID_SETTINGS), REMOTE)
        self.assertEqual(resp.status_code, 403, "公网地址无口令写设置必须 403")
        save_env.assert_not_called()

    def test_remote_save_with_admin_token_allowed(self):
        payload = dict(VALID_SETTINGS, admin_token=ADMIN_TOKEN)
        with mock.patch.object(
            config, "WEB_ADMIN_TOKEN", ADMIN_TOKEN, create=True
        ), mock.patch("radar.web.config.save_env") as save_env, mock.patch(
            "radar.web.config.github_token_status", return_value="env"
        ):
            resp = self._post("/api/settings", payload, REMOTE)
        self.assertEqual(resp.status_code, 200, "口令正确时应允许保存")
        save_env.assert_called_once()

    def test_loopback_save_allowed(self):
        with mock.patch.object(config, "WEB_ADMIN_TOKEN", "", create=True), mock.patch(
            "radar.web.config.save_env"
        ) as save_env, mock.patch(
            "radar.web.config.github_token_status", return_value="env"
        ):
            resp = self._post("/api/settings", dict(VALID_SETTINGS), LOOPBACK)
        self.assertEqual(resp.status_code, 200, "本机访问应允许保存")
        save_env.assert_called_once()

    def test_loopback_base_url_with_newline_rejected(self):
        payload = dict(VALID_SETTINGS, base_url="https://x/\nEVIL=1")
        with mock.patch.object(config, "WEB_ADMIN_TOKEN", "", create=True), mock.patch(
            "radar.web.config.save_env"
        ) as save_env, mock.patch(
            "radar.web.config.github_token_status", return_value="env"
        ):
            resp = self._post("/api/settings", payload, LOOPBACK)
        self.assertEqual(resp.status_code, 400, "base_url 含换行必须 400 拒绝")
        save_env.assert_not_called()

    def test_remote_settings_test_without_token_forbidden_no_network(self):
        with mock.patch.object(config, "WEB_ADMIN_TOKEN", "", create=True), mock.patch(
            "radar.web.requests.get",
            side_effect=AssertionError("无口令的远程请求不得触网"),
        ), mock.patch(
            "radar.web.config.resolve_github_token",
            side_effect=AssertionError("无口令的远程请求不得读取 token"),
        ):
            resp = self._post("/api/settings/test", {"target": "github"}, REMOTE)
        self.assertEqual(resp.status_code, 403, "公网地址无口令调测试接口必须 403")

    def test_llm_test_uses_form_values_without_saving(self):
        payload = {
            "target": "llm",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "sk-test",
            "json_mode": False,
            "disable_thinking": False,
        }
        with mock.patch.object(config, "WEB_ADMIN_TOKEN", "", create=True), mock.patch(
            "radar.web.llm._chat_json", return_value={"ok": True}
        ) as chat, mock.patch("radar.web.config.save_env") as save_env:
            resp = self._post("/api/settings/test", payload, LOOPBACK)
        self.assertEqual(resp.status_code, 200)
        cfg = chat.call_args.kwargs["cfg_override"]
        self.assertEqual(cfg["provider"], "openai")
        self.assertEqual(cfg["base_url"], "https://api.openai.com/v1")
        self.assertEqual(cfg["model"], "gpt-4o-mini")
        self.assertEqual(cfg["api_key"], "sk-test")
        self.assertFalse(cfg["json_mode"])
        save_env.assert_not_called()

    def test_github_test_uses_form_token_without_saving(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"login": "tester"}
        with mock.patch.object(config, "WEB_ADMIN_TOKEN", "", create=True), mock.patch(
            "radar.web.requests.get", return_value=response
        ) as get, mock.patch(
            "radar.web.config.resolve_github_token", side_effect=AssertionError("不应读取已保存 token")
        ):
            resp = self._post(
                "/api/settings/test",
                {"target": "github", "github_token": "ghp_test"},
                LOOPBACK,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ghp_test", get.call_args.kwargs["headers"]["Authorization"])

    def test_remote_demo_load_forbidden(self):
        """远程访客不能往本地库里写示例数据。"""
        with mock.patch.object(config, "WEB_ADMIN_TOKEN", "", create=True), mock.patch(
            "radar.demo.load_demo", side_effect=AssertionError("无口令不得写库")
        ) as load_demo:
            resp = self._post("/api/demo/load", {}, REMOTE)
        self.assertEqual(resp.status_code, 403)
        load_demo.assert_not_called()

    def test_fetch_image_bytes_rejects_unsafe_before_request(self):
        with mock.patch(
            "radar.web.requests.get",
            side_effect=AssertionError("不安全 URL 不得发起请求"),
        ), mock.patch(
            "requests.Session.get",
            side_effect=AssertionError("不安全 URL 不得发起请求"),
        ):
            with self.assertRaises(ValueError):
                web._fetch_image_bytes("http://127.0.0.1/x")

    def test_non_ascii_admin_token_save_never_500(self):
        """回归：中文管理口令必须可正常工作，错误中文口令返回 403 而不是 500。"""
        with mock.patch.object(
            config, "WEB_ADMIN_TOKEN", "密码123", create=True
        ), mock.patch("radar.web.config.save_env") as save_env, mock.patch(
            "radar.web.config.github_token_status", return_value="env"
        ):
            resp = self._post(
                "/api/settings", dict(VALID_SETTINGS, admin_token="密码123"), REMOTE
            )
        self.assertEqual(resp.status_code, 200, "中文口令正确时应允许保存")
        save_env.assert_called_once()

        with mock.patch.object(
            config, "WEB_ADMIN_TOKEN", "s3cret", create=True
        ), mock.patch("radar.web.config.save_env") as save_env:
            resp = self._post(
                "/api/settings", dict(VALID_SETTINGS, admin_token="口令"), REMOTE
            )
        self.assertEqual(resp.status_code, 403, "错误中文口令应 403，不能 500")
        save_env.assert_not_called()


if __name__ == "__main__":
    unittest.main()
