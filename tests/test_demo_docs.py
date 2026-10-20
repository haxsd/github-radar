# -*- coding: utf-8 -*-
"""内置示例数据与 README 文档一致性测试。

不碰数据库、不碰 .env：demo.load_items() 只读 radar/demo_data.json，
README 只读仓库根的 README.md。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from radar import demo

ROOT = Path(__file__).resolve().parent.parent
README_PATH = ROOT / "README.md"

REQUIRED_FIELDS = ("full_name", "description_zh", "summary_zh", "category", "form")

# README 里必须有两处「N 个手写中文示例项目」，N 与示例条数一致
DEMO_COUNT_PATTERN = re.compile(r"(\d+) 个手写中文示例项目")


class TestDemoItems(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = demo.load_items()

    def test_items_not_empty(self):
        self.assertTrue(self.items, "内置示例数据不能为空")

    def test_required_fields_present_and_non_empty(self):
        for index, item in enumerate(self.items):
            for field in REQUIRED_FIELDS:
                with self.subTest(index=index, field=field):
                    self.assertIn(field, item, f"第 {index} 条示例缺少字段 {field}")
                    self.assertTrue(
                        item.get(field),
                        f"第 {index} 条示例的 {field} 不能为空：{item.get('full_name')}",
                    )

    def test_full_name_unique(self):
        names = [str(item.get("full_name") or "") for item in self.items]
        self.assertEqual(
            len(names), len(set(names)), "示例数据里的 full_name 必须唯一"
        )


class TestReadmeDemoCount(unittest.TestCase):
    def test_readme_mentions_match_demo_item_count(self):
        self.assertTrue(README_PATH.is_file(), f"找不到仓库根 README.md：{README_PATH}")
        text = README_PATH.read_text(encoding="utf-8")
        total = len(demo.load_items())
        numbers = [int(m) for m in DEMO_COUNT_PATTERN.findall(text)]

        if not numbers:
            # 精简版 README 可能只写“载入示例数据/radar.demo”，不写数量
            self.assertIn("radar.demo", text, "README 应提到内置示例数据（radar.demo）")
            return
        for number in numbers:
            self.assertEqual(
                number,
                total,
                f"README 写的是 {number} 个手写中文示例项目，"
                f"但 demo.load_items() 实际有 {total} 条",
            )


if __name__ == "__main__":
    unittest.main()
