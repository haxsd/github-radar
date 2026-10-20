# -*- coding: utf-8 -*-
"""netguard.is_safe_image_url 白名单行为测试。

纯函数测试：离线、无副作用、不发任何网络请求。
接口契约见 task-3：只允许 GitHub 自家图片/HTML 域名上的 https 绝对 URL。
"""

from __future__ import annotations

import unittest

from radar.netguard import is_safe_image_url


class TestIsSafeImageUrl(unittest.TestCase):
    def test_allows_known_github_hosts(self):
        urls = [
            "https://repository-images.githubusercontent.com/123/abc",
            "https://opengraph.githubassets.com/hash/o/r",
            "https://github.com/a/b",
            "https://avatars.githubusercontent.com/u/1",
            "https://user-images.githubusercontent.com/x.png",
            # 域名大小写不敏感
            "https://GitHub.com/a/b",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(is_safe_image_url(url), f"应允许：{url}")

    def test_rejects_unsafe_urls(self):
        urls = [
            "http://github.com/a/b",  # 非 https
            "ftp://github.com/x",  # 非 http(s) 协议
            "https://github.com.evil.com/x",  # 前缀伪装
            "https://evilgithubusercontent.com/x",  # 后缀伪装
            "https://127.0.0.1/x",  # 回环 IP
            "https://[::1]/x",  # IPv6 回环
            "https://user:pass@github.com/x",  # 带 userinfo
            "https://github.com:8443/x",  # 非默认端口
            "https://github.com./x",  # 末尾点号
            "",  # 空串
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertFalse(is_safe_image_url(url), f"应拒绝：{url!r}")

    def test_rejects_none(self):
        # 契约允许 None 返回 False 或抛 ValueError；这里锁定更稳的 False 行为。
        self.assertFalse(is_safe_image_url(None))


if __name__ == "__main__":
    unittest.main()
