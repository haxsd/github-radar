# -*- coding: utf-8 -*-
"""检查更新：版本比较、缓存、网络错误与 API 行为（全部离线）。"""

from __future__ import annotations

import unittest
from unittest import mock

import requests

from radar import __version__, update, web


def _release(tag: str, url: str = "") -> mock.Mock:
    response = mock.Mock(status_code=200)
    response.json.return_value = {
        "tag_name": tag,
        "name": tag,
        "html_url": url or f"https://github.com/{update.GITHUB_REPO}/releases/tag/{tag}",
        "published_at": "2026-10-20T12:00:00Z",
    }
    return response


class TestVersionCompare(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(update.parse_version("v0.7.0"), (0, 7, 0))
        self.assertEqual(update.parse_version("0.7.0-beta.2"), (0, 7, 0, 2))
        self.assertEqual(update.parse_version(""), ())

    def test_newer(self):
        self.assertTrue(update.is_newer("v0.8.0", "0.7.0"))
        self.assertTrue(update.is_newer("v0.7.1", "0.7.0"))
        self.assertFalse(update.is_newer("v0.7.0", "0.7.0"))
        self.assertFalse(update.is_newer("v0.6.9", "0.7.0"))
        self.assertFalse(update.is_newer("", "0.7.0"))


class TestCheckLatest(unittest.TestCase):
    def setUp(self):
        update._reset_cache()
        self.addCleanup(update._reset_cache)

    def test_detects_new_release_and_caches(self):
        with mock.patch("radar.update.requests.get", return_value=_release("v9.9.9")) as get:
            first = update.check_latest(force=True)
            self.assertTrue(first["ok"])
            self.assertTrue(first["has_update"])
            self.assertEqual(first["latest"], "9.9.9")
            self.assertFalse(first["cached"])
            self.assertTrue(first["url"].startswith("https://github.com/haxsd/github-radar/releases/"))
            get.assert_called_once()

            get.reset_mock()
            second = update.check_latest()
            self.assertTrue(second["cached"])
            self.assertEqual(second["latest"], "9.9.9")
            get.assert_not_called()

    def test_same_version_is_not_update(self):
        with mock.patch("radar.update.requests.get", return_value=_release("v" + __version__)):
            result = update.check_latest(force=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["has_update"])

    def test_network_timeout_returns_friendly_error(self):
        with mock.patch("radar.update.requests.get", side_effect=requests.Timeout("slow")):
            result = update.check_latest(force=True)
        self.assertFalse(result["ok"])
        self.assertIn("超时", result["error"])

    def test_bad_payload(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {}
        with mock.patch("radar.update.requests.get", return_value=response):
            result = update.check_latest(force=True)
        self.assertFalse(result["ok"])
        self.assertIn("不完整", result["error"])


class TestUpdateEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def test_force_flag_and_payload(self):
        fixture = {
            "ok": True,
            "current": __version__,
            "latest": "9.9.9",
            "has_update": True,
            "url": "https://github.com/haxsd/github-radar/releases/tag/v9.9.9",
        }
        with mock.patch.object(web.update, "check_latest", return_value=fixture) as check:
            resp = self.client.get("/api/update/check?refresh=1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), fixture)
        check.assert_called_once_with(force=True)

    def test_endpoint_never_500(self):
        with mock.patch.object(web.update, "check_latest", side_effect=RuntimeError("boom")):
            resp = self.client.get("/api/update/check")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("boom", data["error"])


if __name__ == "__main__":
    unittest.main()
