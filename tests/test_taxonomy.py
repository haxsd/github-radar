# -*- coding: utf-8 -*-
"""规则兜底打标测试：短关键词必须按词匹配，不能子串误伤。"""

from __future__ import annotations

import unittest

from radar import taxonomy


def _repo(description: str, language: str = "Python", topics: list[str] | None = None):
    return {
        "full_name": "demo/example",
        "description": description,
        "language": language,
        "topics": topics or [],
    }


def _cat(repo) -> str:
    return next(tag for tag, kind in taxonomy.rule_tags(repo) if kind == "cat")


def _form(repo) -> str:
    return next(tag for tag, kind in taxonomy.rule_tags(repo) if kind == "form")


class TestKeywordBoundaries(unittest.TestCase):
    def test_html_is_not_ai(self):
        # "ml" 不能命中 html，"ai" 也不能命中 maintain/email
        for text in (
            "A simple HTML page",
            "maintainer tools for email",
            "daily email digest",
        ):
            with self.subTest(text=text):
                self.assertNotEqual(_cat(_repo(text)), "cat:ai")

    def test_client_is_not_cli(self):
        self.assertEqual(_form(_repo("A GitHub API client")), "form:library")

    def test_guide_is_not_gui(self):
        repo = _repo("A user guide for the service")
        tags = {tag for tag, _ in taxonomy.rule_tags(repo)}
        self.assertNotIn("feature:gui", tags)

    def test_scenarios_is_not_ios(self):
        tags = {tag for tag, _ in taxonomy.rule_tags(_repo("scenarios for testing"))}
        self.assertNotIn("platform:ios", tags)

    def test_real_ai_and_cli_still_match(self):
        self.assertEqual(_cat(_repo("AI agent for local LLM")), "cat:ai")
        self.assertEqual(_form(_repo("A CLI for backups")), "form:cli")


class TestPlatformFallback(unittest.TestCase):
    def test_html_language_maps_to_web(self):
        tags = {tag for tag, _ in taxonomy.rule_tags(_repo("A small page", "HTML"))}
        self.assertIn("platform:web", tags)
        self.assertNotIn("platform:cross", tags)

    def test_javascript_does_not_duplicate_platform_web(self):
        tags = [tag for tag, _ in taxonomy.rule_tags(_repo("A web app", "JavaScript"))]
        self.assertEqual(tags.count("platform:web"), 1)


class TestNormalizeLlmTags(unittest.TestCase):
    def test_string_arrays_are_ignored(self):
        # 模型偶尔把数组写成字符串，不能逐字拆成平台/特性/关键词
        tags = taxonomy.normalize_llm_tags(
            {
                "category": "ai",
                "form": "app",
                "platforms": "windows",
                "features": "docker",
                "keywords": "agent",
            }
        )
        values = {tag for tag, _ in tags}
        self.assertIn("cat:ai", values)
        self.assertIn("form:app", values)
        self.assertFalse(any(v.startswith(("platform:win", "feature:d", "kw:a")) for v in values))


if __name__ == "__main__":
    unittest.main()
