# -*- coding: utf-8 -*-
"""前端静态资源与模板结构测试。

P2 重构后 CSS/JS 已从模板内联拆到 radar/static/：
- base.html 只负责结构与数据；
- 每个页面通过 url_for('static', ...) 引用自己的 css/js；
- 模板里不再有 <style>/<script> 内联大段代码。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from radar import web

TEMPLATES = Path(web.__file__).resolve().parent / "templates"
STATIC = TEMPLATES.parent / "static"

PAGES = ("feed", "daily", "rank", "saves", "history", "settings")


class TestNoInlineAssets(unittest.TestCase):
    def test_base_has_no_inline_style_or_script_block(self):
        html = (TEMPLATES / "base.html").read_text(encoding="utf-8")
        self.assertNotIn("<style>", html, "base.html 不应再内联 <style>")
        self.assertNotIn("<script>", html, "base.html 不应再内联 <script>")
        self.assertIn("css/base.css", html)
        self.assertIn("js/base.js", html)

    def test_pages_have_no_inline_style_or_script_block(self):
        for page in PAGES:
            with self.subTest(page=page):
                html = (TEMPLATES / f"{page}.html").read_text(encoding="utf-8")
                self.assertNotIn("<style>", html, f"{page}.html 不应内联 <style>")
                self.assertNotIn("<script>", html, f"{page}.html 不应内联 <script>")
                self.assertIn(f"css/{page}.css", html)

    def test_page_scripts_are_external(self):
        for page in PAGES:
            with self.subTest(page=page):
                html = (TEMPLATES / f"{page}.html").read_text(encoding="utf-8")
                if page == "daily":
                    self.assertNotIn(f"js/{page}.js", html, "日报页没有独立脚本")
                else:
                    self.assertIn(f"js/{page}.js", html)


class TestStaticFilesExist(unittest.TestCase):
    def test_referenced_static_files_exist(self):
        pattern = re.compile(r"url_for\('static',\s*filename='([^']+)'\)")
        for template in TEMPLATES.glob("*.html"):
            text = template.read_text(encoding="utf-8")
            for filename in pattern.findall(text):
                with self.subTest(template=template.name, file=filename):
                    self.assertTrue(
                        (STATIC / filename).is_file(),
                        f"{template.name} 引用的静态文件不存在: {filename}",
                    )

    def test_css_js_assets_are_non_empty(self):
        for path in sorted(STATIC.rglob("*")):
            if path.suffix not in (".css", ".js"):
                continue
            with self.subTest(path=str(path.relative_to(STATIC))):
                self.assertGreater(path.stat().st_size, 300, f"{path.name} 过小，疑似内容丢失")

    def test_static_assets_served_by_flask(self):
        client = web.app.test_client()
        for filename in ("css/base.css", "js/base.js", "js/feed.js", "css/settings.css"):
            with self.subTest(file=filename):
                resp = client.get(f"/static/{filename}")
                self.assertEqual(resp.status_code, 200, f"/static/{filename} 应可访问")
                self.assertGreater(len(resp.get_data()), 300)


class TestMacrosAreWired(unittest.TestCase):
    def test_pages_import_macros(self):
        # 信息流的卡片由 JS 生成，其余服务端渲染页面复用共享宏
        for page in ("daily", "rank", "history", "saves", "settings"):
            html = (TEMPLATES / f"{page}.html").read_text(encoding="utf-8")
            with self.subTest(page=page):
                self.assertIn('_macros.html', html, f"{page}.html 应引用共享宏")

    def test_base_js_exposes_shared_helpers(self):
        js = (STATIC / "js" / "base.js").read_text(encoding="utf-8")
        self.assertIn("window.toast", js)
        self.assertIn("window.dialogFocus", js)
        self.assertIn("/api/thumbs/status", js)
        self.assertIn("/api/network/status", js)

    def test_settings_page_has_network_card(self):
        html = (TEMPLATES / "settings.html").read_text(encoding="utf-8")
        for marker in ('id="network"', 'id="net-github-pill"', 'id="radarProxy"'):
            self.assertIn(marker, html, f"设置页缺少网络状态标记: {marker}")


if __name__ == "__main__":
    unittest.main()
