"""DeepSeek：中文卡片文案 + 项目标签。"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from . import config, db, taxonomy

SYSTEM = (
    "你是「GitHub 中文雷达」的开源项目编辑，读者是中文开发者。"
    "根据给定的仓库信息，产出中文卡片文案和结构化标签。"
    "要求：忠实、具体、不夸张、不编造未被提供的信息。只输出 JSON 对象，不要 markdown。"
)

JUDGEMENTS = {"值得用", "可以关注", "不建议"}


def _enum_text(table: dict[str, str]) -> str:
    return "、".join(f"{k}={v}" for k, v in table.items())


TAG_FIELDS = f"""另外输出这些标签字段（受控词表，必须用 key）：
- category: 领域，从 [{_enum_text(taxonomy.CATEGORIES)}] 中选一个
- form: 形态，从 [{_enum_text(taxonomy.FORMS)}] 中选一个（不确定时不要一律选 other：能安装运行的程序/桌面工具选 app，命令行工具选 cli）
- platforms: 平台数组，从 [{_enum_text(taxonomy.PLATFORMS)}] 选 1~3 个
- features: 特性数组，从 [{_enum_text(taxonomy.FEATURES)}] 选 0~3 个
- keywords: 中文关键词数组，1~4 个，每个不超过 6 个字，描述项目特点"""

CARD_FIELDS = """输出这些文案字段：
- desc_zh: 一句话说明这是什么，不超过 45 个汉字，要有信息量（别写"这是一个开源工具"这种空话）
- summary_zh: 3~5 句、180~320 个汉字，像给朋友介绍一样讲清楚：
    ①它具体做什么、②解决什么痛点、③主要功能点（挑 2~3 个最关键的）、④适合谁用、⑤上手门槛或注意事项
- points: 字符串数组，2~4 条「亮点/关键点」，每条不超过 20 个汉字，用于列表详情里快速扫读
- judgement: 只能是 "值得用" / "可以关注" / "不建议" 之一。
    注意：如果仓库只是**教程/指南/导航页/聚合页**（没有软件本体、没有代码），或者明显是付费软件/破解资源的推广页，必须给 "不建议"。
- flags: 字符串数组，最多 3 个，例如 "需要 API Key"、"需 Docker"、"中文文档"；没有就给 []
- is_chinese: 布尔值，该项目的描述或文档是否中文友好"""


class LLMError(RuntimeError):
    pass


class _FatalLLMError(LLMError):
    """401/403 这类重试无意义的错误。"""


# 不走本机系统代理：并发调用时本机代理（如 127.0.0.1:7897）会排队卡死请求。
# DeepSeek API 可直连，绕过代理反而更快更稳。
_session = requests.Session()
_session.trust_env = False


def _extract_json(content: str) -> dict[str, Any]:
    """模型偶尔会包 markdown / 前后缀，尽量提取出 JSON 对象。"""
    text = (content or "").strip()
    if text.startswith("```"):
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _chat_json(
    messages: list[dict[str, str]],
    max_tokens: int = 900,
    cfg_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """调用任意 OpenAI 兼容的 /chat/completions 接口，返回 JSON。"""
    cfg = cfg_override or config.llm_config()
    if not cfg["chat_url"]:
        raise LLMError("模型地址未配置：请在网页「设置」里填写 Base URL")
    if not cfg["model"]:
        raise LLMError("模型名未配置：请在网页「设置」里填写模型名（如 deepseek-chat）")
    headers = {"Content-Type": "application/json", "Connection": "close"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    payload: dict[str, Any] = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if cfg["json_mode"]:
        payload["response_format"] = {"type": "json_object"}
    if cfg["disable_thinking"] and cfg["provider"] == "deepseek":
        # DeepSeek 思考 token 会挤占输出预算，导致偶发空内容；其他兼容接口不认识这个字段
        payload["thinking"] = {"type": "disabled"}

    last_err: Exception | None = None
    json_mode = bool(cfg["json_mode"])
    proxies = config.llm_proxies() or {}
    for attempt in range(3):
        try:
            resp = _session.post(
                str(cfg["chat_url"]),
                headers=headers,
                json=payload,
                timeout=(15, 60),
                proxies=proxies,
            )
            if resp.status_code in (401, 403):
                # Key 无效/无权限：重试没有意义，直接返回可读错误
                raise _FatalLLMError(f"{resp.status_code}: {resp.text[:200]}")
            if resp.status_code >= 400 and json_mode and "response_format" in resp.text.lower():
                # 部分兼容接口不支持 JSON 模式，去掉后重试
                json_mode = False
                payload.pop("response_format", None)
                continue
            if resp.status_code >= 400:
                raise LLMError(f"{resp.status_code}: {resp.text[:200]}")
            content = resp.json()["choices"][0]["message"].get("content") or ""
            if not content.strip():
                raise LLMError("模型返回空内容")
            return _extract_json(content)
        except _FatalLLMError:
            raise
        except Exception as exc:
            last_err = exc
            time.sleep(1.2 * (attempt + 1))
    raise LLMError(f"模型调用失败（{cfg['provider']}/{cfg['model']}）: {last_err}")


def _repo_info(repo: dict[str, Any]) -> str:
    topics = repo.get("topics")
    try:
        topics = json.loads(topics) if isinstance(topics, str) else topics
    except Exception:
        topics = []
    return f"""仓库名：{repo.get('full_name')}
描述：{repo.get('description') or '(无)'}
中文简介（可能有）：{repo.get('description_zh') or '(无)'}
语言：{repo.get('language') or '未知'}
GitHub topics：{', '.join(topics or []) or '(无)'}
star：{repo.get('stars')}  fork：{repo.get('forks')}
license：{repo.get('license') or '未知'}
创建时间：{repo.get('created_at')}  最近提交：{repo.get('pushed_at')}
官网：{repo.get('homepage') or '(无)'}"""


def _normalize_card(data: dict[str, Any]) -> dict[str, Any]:
    desc = str(data.get("desc_zh") or "").strip()[:80]
    summary = str(data.get("summary_zh") or "").strip()[:600]
    judgement = data.get("judgement")
    if judgement not in JUDGEMENTS:
        judgement = "可以关注"
    flags = data.get("flags") or []
    if not isinstance(flags, list):
        flags = []
    flags = [str(f).strip()[:20] for f in flags if str(f).strip()][:3]
    raw_points = data.get("points") or []
    if not isinstance(raw_points, list):
        raw_points = []
    points = [str(p).strip()[:40] for p in raw_points if str(p).strip()][:4]
    return {
        "desc_zh": desc,
        "summary_zh": summary,
        "points": points,
        "judgement": judgement,
        "flags": flags,
        "is_chinese": bool(data.get("is_chinese")),
    }


def analyze_full(repo: dict[str, Any]) -> dict[str, Any]:
    """一次调用同时产出中文文案 + 标签（用于新项目）。"""
    data = _chat_json(
        [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": f"{CARD_FIELDS}\n\n{TAG_FIELDS}\n\n仓库信息：\n{_repo_info(repo)}",
            },
        ],
        max_tokens=1500,
    )
    out = _normalize_card(data)
    out["tags"] = taxonomy.normalize_llm_tags(data)
    return out


def tag_only(repo: dict[str, Any]) -> list[tuple[str, str]]:
    """只打标签（用于已经翻好的老项目）。"""
    data = _chat_json(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"{TAG_FIELDS}\n\n仓库信息：\n{_repo_info(repo)}"},
        ],
        max_tokens=600,
    )
    return taxonomy.normalize_llm_tags(data)


def _parallel(items: list[Any], fn: Callable[[Any], Any], workers: int) -> list[tuple[Any, Any, Exception | None]]:
    """并发调用 API，返回 (item, result, error)。"""
    results: list[tuple[Any, Any, Exception | None]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fn, item): item for item in items}
        for fut, item in futures.items():
            try:
                results.append((item, fut.result(), None))
            except Exception as exc:  # 单条失败不影响整体
                results.append((item, None, exc))
    return results


# ---------------- 批量任务 ----------------

def rewrite_cards(conn, limit: int = 200, workers: int = 6, verbose: bool = True) -> int:
    """给已有项目重新生成更长的中文介绍 + 要点（老卡片升级用）。"""
    rows = db.repos_needing_rewrite(conn, limit)
    if not rows:
        return 0
    done = 0
    for item, data, err in _parallel([dict(r) for r in rows], analyze_full, workers):
        rid = item["id"]
        if err is not None:
            if verbose:
                print(f"  [失败] {item['full_name']}: {err}")
            continue
        db.set_translation(conn, rid, data)
        db.set_tags(conn, rid, data.get("tags") or taxonomy.rule_tags(item))
        conn.commit()
        done += 1
        if verbose:
            print(f"  [OK] {item['full_name']} · {len(data.get('summary_zh') or '')} 字 · {len(data.get('points') or [])} 个要点")
    return done


def translate_pending(conn, limit: int = 200, workers: int = 6, verbose: bool = True) -> int:
    """补齐中文文案（顺便打标签）。只处理还没中文的卡片。"""
    rows = db.untranslated(conn, limit)
    if not rows:
        return 0
    done = 0
    for item, data, err in _parallel([dict(r) for r in rows], analyze_full, workers):
        rid = item["id"]
        if err is not None:
            if verbose:
                print(f"  [失败] {item['full_name']}: {err}")
            db.set_tags(conn, rid, taxonomy.rule_tags(item))
            continue
        db.set_translation(conn, rid, data)
        db.set_tags(conn, rid, data.get("tags") or taxonomy.rule_tags(item))
        conn.commit()
        done += 1
        if verbose:
            print(f"  [OK] {item['full_name']} -> {data['judgement']} · {len(data.get('tags') or [])} 个标签")
    return done


def tag_pending(conn, limit: int = 400, workers: int = 6, verbose: bool = True) -> int:
    """给还没有标签的仓库打标。"""
    rows = db.repos_without_tags(conn, limit)
    if not rows:
        return 0
    done = 0
    for item, tags, err in _parallel([dict(r) for r in rows], tag_only, workers):
        rid = item["id"]
        if err is not None:
            db.set_tags(conn, rid, taxonomy.rule_tags(item))
        else:
            db.set_tags(conn, rid, tags or taxonomy.rule_tags(item))
        conn.commit()
        done += 1
        if verbose and done % 20 == 0:
            print(f"  [标签] 已处理 {done}/{len(rows)}")
    return done
