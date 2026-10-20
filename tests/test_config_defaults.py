# -*- coding: utf-8 -*-
"""config.llm_config() 的 chat_url 拼接规则测试（离线，仅 patch 模块级变量）。"""

from __future__ import annotations

import unittest
from unittest import mock

from radar import config

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


if __name__ == "__main__":
    unittest.main()
