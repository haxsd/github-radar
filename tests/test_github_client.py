# -*- coding: utf-8 -*-
"""GitHub 客户端重试测试（离线，不访问网络）。"""

from __future__ import annotations

import unittest
from unittest import mock

import requests

from radar import github


def _response(payload: dict, status: int = 200):
    response = mock.Mock()
    response.status_code = status
    response.headers = {}
    response.url = "https://api.github.com/test"
    response.text = ""
    response.json.return_value = payload
    return response


class TestRequestRetries(unittest.TestCase):
    def setUp(self):
        self.client = github.GitHub(token="test-token")

    def test_network_error_is_retried(self):
        ok = _response({"ok": True})
        with mock.patch.object(
            self.client.session,
            "request",
            side_effect=[requests.Timeout("timeout"), ok],
        ) as request, mock.patch("radar.github.time.sleep") as sleep:
            result = self.client._request("GET", "https://api.github.com/test")
        self.assertIs(result, ok)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once()

    def test_network_error_raises_after_retries(self):
        with mock.patch.object(
            self.client.session,
            "request",
            side_effect=requests.ConnectionError("boom"),
        ) as request, mock.patch("radar.github.time.sleep"):
            with self.assertRaises(github.GitHubError):
                self.client._request("GET", "https://api.github.com/test")
        self.assertEqual(request.call_count, 4)


if __name__ == "__main__":
    unittest.main()
