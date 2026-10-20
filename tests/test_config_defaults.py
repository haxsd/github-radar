# -*- coding: utf-8 -*-
"""config.llm_config() 的 chat_url 拼接规则测试（离线，仅 patch 模块级变量）。"""

from __future__ import annotations

import unittest
from unittest import mock

from radar import config, llm

CASES = [
    # (LLM_BASE_URL, 期望的 chat_url)
    ("https://api.deepseek.com/v1", "https://api.deepseek.com/v1/chat/completions"),
    (
        "https://gateway.example.com/chat/completions",
        "https://gateway.example.com/chat/completions",
    ),
    ("https://api.openai.com", "https://api.openai.com/chat/completions"),
]


class TestLlmChatUrl(unittest.TestCase):
    def test_chat_url_building(self):
        for base, expected in CASES:
            with self.subTest(base=base):
                with mock.patch.object(config, "LLM_BASE_URL", base):
                    self.assertEqual(config.llm_config()["chat_url"], expected)

    def test_base_url_trailing_slash_normalized(self):
        with mock.patch.object(config, "LLM_BASE_URL", "https://api.deepseek.com/v1/"):
            cfg = config.llm_config()
        self.assertEqual(cfg["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(
            cfg["chat_url"], "https://api.deepseek.com/v1/chat/completions"
        )

    def test_empty_base_url_has_no_fake_chat_url(self):
        # 之前会拼出 "/chat/completions"，导致错误信息变成 Invalid URL 而不是"未配置"
        with mock.patch.object(config, "LLM_BASE_URL", ""):
            cfg = config.llm_config()
        self.assertEqual(cfg["chat_url"], "")

    def test_missing_model_raises_friendly_error(self):
        with mock.patch.object(config, "LLM_BASE_URL", "https://api.deepseek.com"), mock.patch.object(
            config, "LLM_MODEL", ""
        ), mock.patch.object(config, "LLM_API_KEY", "test"):
            with self.assertRaisesRegex(llm.LLMError, "模型名未配置"):
                llm._chat_json([{"role": "user", "content": "hi"}], max_tokens=10)

    def test_overrides_do_not_touch_global_config(self):
        original = (config.LLM_PROVIDER, config.LLM_BASE_URL, config.LLM_MODEL)
        cfg = config.llm_config(
            {
                "provider": "openai",
                "base_url": "https://api.openai.com/v1/",
                "model": "gpt-4o-mini",
                "json_mode": False,
            }
        )
        self.assertEqual(cfg["provider"], "openai")
        self.assertEqual(cfg["chat_url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(cfg["model"], "gpt-4o-mini")
        self.assertFalse(cfg["json_mode"])
        self.assertEqual(
            (config.LLM_PROVIDER, config.LLM_BASE_URL, config.LLM_MODEL), original
        )


if __name__ == "__main__":
    unittest.main()
