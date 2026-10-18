"""标签体系：领域 / 形态 / 平台 / 特性。

标签用 "kind:key" 存储，例如 cat:ai、form:cli、platform:windows、feature:docker。
LLM 打标与规则兜底都使用本文件里的受控词表，避免标签发散。
"""

from __future__ import annotations

import re
from typing import Any

# ---------------- 受控词表 ----------------

CATEGORIES: dict[str, str] = {
    "ai": "AI & LLM",
    "devtools": "开发工具",
    "data": "数据与数据库",
    "web": "Web 与前端",
    "infra": "系统与运维",
    "security": "安全",
    "productivity": "效率与办公",
    "media": "媒体与创作",
    "game": "游戏",
    "hardware": "硬件与 IoT",
    "learning": "学习与资源",
    "other": "其他",
}

FORMS: dict[str, str] = {
    "app": "应用",
    "cli": "命令行工具",
    "library": "库 / SDK",
    "framework": "框架",
    "plugin": "插件 / 扩展",
    "template": "模板 / 脚手架",
    "resource": "资源合集",
    "other": "其他",
}

PLATFORMS: dict[str, str] = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
    "web": "Web",
    "android": "Android",
    "ios": "iOS",
    "cross": "跨平台",
    "server": "服务端",
}

FEATURES: dict[str, str] = {
    "api_key": "需 API Key",
    "docker": "需 Docker",
    "local": "本地可跑",
    "zh_docs": "中文文档",
    "easy_install": "一键安装",
    "byo_data": "需自备数据",
    "gui": "图形界面",
    "gpu": "需 GPU",
}

KIND_LABEL = {
    "cat": "领域",
    "form": "形态",
    "platform": "平台",
    "feature": "特性",
    "kw": "关键词",
}


def label(tag: str) -> str:
    """cat:ai -> AI & LLM"""
    kind, _, key = tag.partition(":")
    tables = {
        "cat": CATEGORIES,
        "form": FORMS,
        "platform": PLATFORMS,
        "feature": FEATURES,
    }
    if kind == "kw":
        return key
    return tables.get(kind, {}).get(key, key)


# ---------------- 规则兜底 ----------------

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ai": (
        "llm", "gpt", "ai", "agent", "claude", "openai", "chatgpt", "prompt",
        "diffusion", "llama", "rag", "embedding", "transformer", "model", "inference",
        "tts", "asr", "speech", "vision", "ml", "deep learning", "neural",
    ),
    "devtools": (
        "cli", "sdk", "compiler", "linter", "formatter", "git", "ide", "vscode",
        "plugin", "debug", "test", "build", "bundler", "package manager", "api client",
    ),
    "data": (
        "database", "sql", "sqlite", "postgres", "mysql", "redis", "etl", "pipeline",
        "analytics", "dataframe", "parquet", "csv", "stream", "kafka", "olap",
    ),
    "web": (
        "react", "vue", "nextjs", "svelte", "css", "html", "frontend", "website",
        "static site", "browser", "http server", "web framework",
    ),
    "infra": (
        "docker", "kubernetes", "k8s", "devops", "ci", "cd", "server", "proxy",
        "monitor", "deploy", "container", "linux", "shell", "systemd", "nginx",
    ),
    "security": (
        "security", "hack", "pentest", "exploit", "crypto", "encryption", "malware",
        "vulnerability", "auth", "password", "scanner", "cve",
    ),
    "productivity": (
        "note", "todo", "calendar", "productivity", "office", "markdown", "obsidian",
        "workflow", "automation", "shortcut", "clipboard", "screenshot",
    ),
    "media": (
        "video", "audio", "image", "photo", "editor", "render", "ffmpeg", "music",
        "design", "ffmpeg", "3d", "animation", "svg", "pdf",
    ),
    "game": (
        "game", "engine", "emulator", "unity", "godot", "minecraft", "mod",
        "steam", "rpg", "pixel",
    ),
    "hardware": (
        "arduino", "esp32", "raspberry", "iot", "firmware", "robot", "sensor",
        "microcontroller", "serial", "gpio",
    ),
    "learning": (
        "awesome", "tutorial", "course", "book", "guide", "learn", "interview",
        "notes", "roadmap", "cheatsheet", "examples",
    ),
}

_FORM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cli": ("cli", "command line", "command-line", "terminal", "shell", "tui"),
    "library": ("library", "sdk", "package", "module", "api wrapper", "client for"),
    "framework": ("framework", "toolkit", "engine"),
    "plugin": ("plugin", "extension", "addon", "add-on", "integration"),
    "template": ("template", "boilerplate", "starter", "scaffold"),
    "resource": ("awesome", "list of", "collection", "curated", "resources", "roadmap"),
}

_PLATFORM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "windows": ("windows", "win32", "win64", ".exe", "wpf", "uwp"),
    "macos": ("macos", "osx", "mac os", "dmg", "cocoa"),
    "linux": ("linux", "ubuntu", "debian", "arch", "apt", "systemd"),
    "web": ("web", "browser", "saas", "website", "chrome extension"),
    "android": ("android", "apk", "kotlin"),
    "ios": ("ios", "iphone", "ipad", "swiftui", "testflight"),
}

_FEATURE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "api_key": ("api key", "api-key", "openai key", "token", "byok"),
    "docker": ("docker", "docker-compose", "container"),
    "local": ("local", "offline", "self-host", "selfhost", "on-device"),
    "zh_docs": ("中文", "chinese", "简体"),
    "easy_install": ("pip install", "npm install", "brew install", "one-click", "installer"),
    "byo_data": ("your own", "bring your own", "byo", "self-provided"),
    "gui": ("gui", "desktop app", "graphical", "ui for", "interface"),
    "gpu": ("gpu", "cuda", "nvidia", "vram"),
}


def _text(repo: dict[str, Any]) -> str:
    topics = repo.get("topics") or []
    try:
        import json

        if isinstance(topics, str):
            topics = json.loads(topics)
    except Exception:
        topics = []
    parts = [
        repo.get("full_name") or "",
        repo.get("description") or "",
        " ".join(topics or []),
        repo.get("language") or "",
    ]
    return " ".join(parts).lower()


def _match(text: str, table: dict[str, tuple[str, ...]]) -> str | None:
    for key, words in table.items():
        for w in words:
            if w in text and len(w) > 1:
                return key
    return None


def rule_tags(repo: dict[str, Any]) -> list[tuple[str, str]]:
    """不依赖 LLM 的快速打标（兜底 / 新入库即可用）。"""
    text = _text(repo)
    tags: list[tuple[str, str]] = []

    cat = _match(text, _CATEGORY_KEYWORDS) or "other"
    tags.append((f"cat:{cat}", "cat"))

    form = _match(text, _FORM_KEYWORDS) or "other"
    tags.append((f"form:{form}", "form"))

    for key, words in _PLATFORM_KEYWORDS.items():
        if any(w in text for w in words):
            tags.append((f"platform:{key}", "platform"))
            break
    if tags and not any(t[1] == "platform" for t in tags):
        tags.append(("platform:cross", "platform"))

    for key, words in _FEATURE_KEYWORDS.items():
        if any(w in text for w in words):
            tags.append((f"feature:{key}", "feature"))

    # 语言 → 平台提示（兜底）
    lang = (repo.get("language") or "").lower()
    if lang in ("javascript", "typescript") and not any(t == "platform:web" for t in tags):
        tags.append(("platform:web", "platform"))
    return tags


def valid_tag(tag: str) -> bool:
    kind, _, key = tag.partition(":")
    tables = {
        "cat": CATEGORIES,
        "form": FORMS,
        "platform": PLATFORMS,
        "feature": FEATURES,
    }
    if kind == "kw":
        return 1 <= len(key) <= 20
    return key in tables.get(kind, {})


def normalize_llm_tags(data: dict[str, Any]) -> list[tuple[str, str]]:
    """把 LLM 输出转成合法标签列表。"""
    tags: list[tuple[str, str]] = []
    cat = data.get("category")
    tags.append((f"cat:{cat}", "cat") if cat in CATEGORIES else ("cat:other", "cat"))

    form = data.get("form")
    tags.append((f"form:{form}", "form") if form in FORMS else ("form:other", "form"))

    for p in (data.get("platforms") or [])[:4]:
        if p in PLATFORMS:
            tags.append((f"platform:{p}", "platform"))
    for f in (data.get("features") or [])[:4]:
        if f in FEATURES:
            tags.append((f"feature:{f}", "feature"))
    for kw in (data.get("keywords") or [])[:4]:
        kw = re.sub(r"\s+", "", str(kw))[:12]
        if kw:
            tags.append((f"kw:{kw}", "kw"))

    # 去重保序
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for tag in tags:
        if tag[0] not in seen:
            seen.add(tag[0])
            out.append(tag)
    return out
