"""全局配置：路径、凭证、产品规则常量。

配置优先级：环境变量 > 项目根目录 `.env`。
模型服务支持任意 **OpenAI 兼容接口**（DeepSeek / OpenAI / Ollama / 自建网关），
通过 `LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` 配置。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


def _app_root() -> Path:
    """源码运行用项目根目录；打包成 exe 后用 exe 所在目录（数据、.env 都放这里）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = _app_root()
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "radar.db"
ENV_PATH = ROOT / ".env"

# 常见 OpenAI 兼容服务的默认值（可在 .env / 设置页覆盖）
PROVIDERS: dict[str, dict[str, object]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "json_mode": True,
        "disable_thinking": True,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "json_mode": True,
        "disable_thinking": False,
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
        "json_mode": True,
        "disable_thinking": False,
    },
    "custom": {
        "base_url": "",
        "model": "",
        "json_mode": True,
        "disable_thinking": False,
    },
}


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _truthy(value: str, default: bool = True) -> bool:
    value = (value or "").strip().lower()
    if not value:
        return default
    return value not in ("0", "false", "no", "off")


# ---- 运行时配置（由 _load() 填充，可通过 save_env() 热更新）----
GITHUB_TOKEN: str = ""
GH_CLI_PATH: str = ""
LLM_PROVIDER: str = "deepseek"
LLM_BASE_URL: str = ""
LLM_API_KEY: str = ""
LLM_MODEL: str = ""
LLM_JSON_MODE: bool = True
LLM_DISABLE_THINKING: bool = True
WEB_HOST: str = "127.0.0.1"
WEB_PORT: int = 8765

# 由 _load 管理的键：真实环境变量优先级高于 .env，同时 .env 改动后能热加载
_MANAGED_ENV = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GH_CLI_PATH",
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_JSON_MODE",
    "LLM_DISABLE_THINKING",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "WEB_HOST",
    "WEB_PORT",
)
_TRUE_ENV = {key: os.environ[key] for key in _MANAGED_ENV if key in os.environ}


def _load() -> None:
    global GITHUB_TOKEN, GH_CLI_PATH, LLM_PROVIDER, LLM_BASE_URL, LLM_API_KEY
    global LLM_MODEL, LLM_JSON_MODE, LLM_DISABLE_THINKING, WEB_HOST, WEB_PORT

    # 重置托管键 -> 读取 .env -> 再把真实环境变量覆盖回去
    for key in _MANAGED_ENV:
        os.environ.pop(key, None)
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=True)
    os.environ.update(_TRUE_ENV)

    GITHUB_TOKEN = _env("GITHUB_TOKEN") or _env("GH_TOKEN")
    GH_CLI_PATH = _env("GH_CLI_PATH")

    # 兼容旧版 DEEPSEEK_* 变量名
    legacy_key = _env("DEEPSEEK_API_KEY")
    provider = (_env("LLM_PROVIDER") or ("deepseek" if legacy_key or _env("DEEPSEEK_BASE_URL") else "deepseek")).lower()
    if provider not in PROVIDERS:
        provider = "custom"
    preset = PROVIDERS[provider]

    LLM_PROVIDER = provider
    LLM_BASE_URL = (
        _env("LLM_BASE_URL") or _env("DEEPSEEK_BASE_URL") or str(preset["base_url"] or "")
    ).rstrip("/")
    LLM_API_KEY = _env("LLM_API_KEY") or legacy_key
    LLM_MODEL = _env("LLM_MODEL") or _env("DEEPSEEK_MODEL") or str(preset["model"] or "")
    LLM_JSON_MODE = _truthy(_env("LLM_JSON_MODE"), bool(preset["json_mode"]))
    LLM_DISABLE_THINKING = _truthy(_env("LLM_DISABLE_THINKING"), bool(preset["disable_thinking"]))

    WEB_HOST = _env("WEB_HOST") or "127.0.0.1"
    try:
        WEB_PORT = int(_env("WEB_PORT") or "8765")
    except ValueError:
        WEB_PORT = 8765


_load()

# ---- 产品规则（可按需修改）----
MIN_STARS = 50          # 收录门槛：star > 50
ACTIVE_DAYS = 92        # 最近 3 个月有提交
SEED_DAYS = 90          # 种子池：近 90 天创建
INCREMENTAL_DAYS = 2    # 每波增量：近 2 天创建

STAR_JUMP_ABS = 50      # 24h 内 +50★
STAR_JUMP_RATIO = 0.30  # 或 +30%


def llm_config() -> dict[str, object]:
    """当前生效的模型服务配置。"""
    base = (LLM_BASE_URL or "").rstrip("/")
    if base.endswith("/chat/completions"):
        chat_url = base
    elif base.endswith("/v1"):
        chat_url = base + "/chat/completions"
    else:
        chat_url = base + "/chat/completions"
    return {
        "provider": LLM_PROVIDER,
        "base_url": base,
        "chat_url": chat_url,
        "model": LLM_MODEL,
        "api_key": LLM_API_KEY,
        "json_mode": LLM_JSON_MODE,
        "disable_thinking": LLM_DISABLE_THINKING,
    }


def resolve_llm_key() -> str:
    cfg = llm_config()
    if not cfg["api_key"]:
        raise RuntimeError(
            "缺少模型 API Key：请在网页「设置」里填，或写入 .env 的 LLM_API_KEY（本地 Ollama 可留空）"
        )
    return str(cfg["api_key"])


def resolve_github_token() -> str:
    """优先 .env 的 GITHUB_TOKEN，其次本机 gh CLI 登录态。"""
    if GITHUB_TOKEN:
        return GITHUB_TOKEN
    exe = GH_CLI_PATH or shutil.which("gh")
    if exe and Path(exe).exists():
        try:
            out = subprocess.run(
                [exe, "auth", "token"], capture_output=True, text=True, timeout=20
            )
            token = (out.stdout or "").strip()
            if token:
                return token
        except Exception:
            pass
    raise RuntimeError(
        "找不到 GitHub token：请在网页「设置」里填，或 .env 配置 GITHUB_TOKEN，或先 gh auth login"
    )


def github_token_status() -> str:
    """用于设置页展示：env / gh-cli / 未配置。"""
    if GITHUB_TOKEN:
        return "env"
    exe = GH_CLI_PATH or shutil.which("gh")
    if exe and Path(exe).exists():
        try:
            out = subprocess.run([exe, "auth", "token"], capture_output=True, text=True, timeout=10)
            if (out.stdout or "").strip():
                return "gh-cli"
        except Exception:
            pass
    return "missing"


# ---- 保存设置（写回 .env 并热加载）----
MANAGED_KEYS = (
    "GITHUB_TOKEN",
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_JSON_MODE",
    "LLM_DISABLE_THINKING",
)


def save_env(values: dict[str, str]) -> None:
    """更新 .env 里我们管理的键，其他行原样保留；随后热加载。"""
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    result: list[str] = []
    handled: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in MANAGED_KEYS:
                handled.add(key)
                if key in values:
                    result.append(f"{key}={values[key]}")
                else:
                    result.append(line)  # 没提供新值就保留旧值
                continue
        result.append(line)
    for key in MANAGED_KEYS:
        if key in values and key not in handled:
            result.append(f"{key}={values[key]}")
    ENV_PATH.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")
    _load()


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def assets_dir() -> Path:
    """打包后资源在 _MEIPASS/assets，源码运行时在项目 assets/。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets"
    return ROOT / "assets"
