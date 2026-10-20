"""出站图片地址校验：缩略图只允许 GitHub 自有图片域名（SSRF 防护）。

缩略图来源是 GitHub GraphQL 返回的 ``openGraphImageUrl``，正常落在
``opengraph.githubassets.com`` / ``repository-images.githubusercontent.com``
等域名。如果本地库被污染（手工改库、导入脏数据等），直接 ``GET`` 就可能被
用来探测内网。这里做严格的 scheme + host 白名单，下载时每一跳重定向都会
重新校验。
"""

from __future__ import annotations

from urllib.parse import urlsplit

# 允许的根域名：
# - github.com（含 api.github.com 等子域）
# - githubassets.com（opengraph.githubassets.com 是 GraphQL openGraphImageUrl 的常见宿主）
# - githubusercontent.com（含 avatars / user-images / repository-images 等子域）
ALLOWED_IMAGE_HOSTS: tuple[str, ...] = (
    "github.com",
    "githubassets.com",
    "githubusercontent.com",
)

_ALLOWED_SCHEMES = ("https",)
_ALLOWED_PORTS = (None, 443)
_MAX_URL_LENGTH = 2048


def is_safe_image_url(url: str | None) -> bool:
    """判断 URL 是否可以安全地作为图片下载地址。

    只放行 https + GitHub 自有域名（含子域）；拒绝 IP 字面量、userinfo、
    非 443 端口、控制字符和超长 URL。
    """
    if not isinstance(url, str):
        return False
    candidate = url.strip()
    if not candidate or len(candidate) > _MAX_URL_LENGTH:
        return False
    # 控制字符/空格可能被底层 HTTP 库重新解释，直接拒绝
    if any(ord(ch) < 0x20 or ch == " " for ch in candidate):
        return False

    try:
        parts = urlsplit(candidate)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return False

    if (parts.scheme or "").lower() not in _ALLOWED_SCHEMES:
        return False
    if not host:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    if port not in _ALLOWED_PORTS:
        return False

    host = host.lower()
    return any(
        host == allowed or host.endswith("." + allowed)
        for allowed in ALLOWED_IMAGE_HOSTS
    )
