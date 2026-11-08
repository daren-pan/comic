"""查询改写：先把问题换成 3 个说法，再分别检索。

## 为什么需要

知识库里同一个意思常有不同写法：文档说「收藏更新通知」，用户问「更新了怎么提醒」。
词面路（BM25）要求**字面一致**，语义路的 512 维小模型又分不出「服务清单」和
「收藏更新通知」的差别 —— 实测原句查不到答案，改写成含「通知」的说法后才进候选。

## 怎么做

一次 LLM 调用（关掉 thinking），让模型给出 3 个改写：同义说法、口语化、关键词式。
`deepseek-v4.1-flash` 实测 **2.6~3.4 秒**。

## 失败语义

**任何异常都返回空列表**，调用方退化成"只用原句" —— 改写是锦上添花，
它挂了不该让检索失败（与 `chat-service` 的改写同一条约定）。

## 为什么不用 chat-service 的 `_build_llm`

模块边界：`knowledge-mcp` 不依赖 `chat-service`（那边是独立进程 + 一堆 RAG 依赖）。
这里只复用**同一套环境变量**（`COMIC_LLM_*`），客户端自己建，约 20 行。
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading

from . import config

_log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_LLM = None
#: 同一次会话里重复查询（评测、调参）不该反复花钱。
_CACHE: dict[str, list[str]] = {}

_PROMPT = (
    "你是检索助手。把用户的问题改写成 {n} 个**不同说法**，用于在项目文档里检索。\n"
    "要求：\n"
    "1. 一个用同义词替换关键概念（例如「提醒」→「通知」、「采集」→「爬虫」）；\n"
    "2. 一个口语化、像人随口问的；\n"
    "3. 一个只保留关键词、去掉疑问词。\n"
    "不要解释，只输出 JSON 字符串数组。\n\n问题：{query}"
)


def _load_env_file() -> None:
    """把 chat-service 的 `rag/.env` 里缺的键补进环境变量（只补缺失的，不覆盖）。"""
    path = config.ROOT / "chat-service" / "src" / "comic_chat" / "rag" / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


def _api_key() -> str:
    key = os.environ.get("COMIC_LLM_API_KEY", "").strip()
    if not key:
        _load_env_file()
        key = os.environ.get("COMIC_LLM_API_KEY", "").strip()
    return key


def available() -> bool:
    """有 key 才能改写；没有就静默退化成原句。"""
    return bool(_api_key())


def _build_llm():
    global _LLM
    if _LLM is not None:
        return _LLM
    with _LOCK:
        if _LLM is not None:
            return _LLM
        import uuid

        from langchain_openai import ChatOpenAI

        _LLM = ChatOpenAI(
            model=os.environ.get("COMIC_LLM_MODEL", "deepseek-v4.1-flash").strip(),
            base_url=os.environ.get("COMIC_LLM_BASE_URL", "https://opencode.ai/zen/go/v1").strip(),
            api_key=_api_key(),
            temperature=0.2,
            timeout=config.REWRITE_TIMEOUT,
            max_retries=1,
            # 改写是格式转换，开着 thinking 纯浪费（chat-service 实测 4729ms → 1680ms）
            extra_body={"thinking": {"type": "disabled"}},
            default_headers={
                "x-opencode-session": str(uuid.uuid4()),
                "User-Agent": "comic-rag-lab/1.0",
            },
        )
        return _LLM


def _parse(raw: str) -> list[str]:
    text = str(raw or "").strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [str(item).strip() for item in items if str(item).strip()]


def rewrite(query: str, n: int | None = None, force: bool = False) -> list[str]:
    """返回改写后的说法（不含原句）；失败或没配置 key 时返回空列表。

    `force=True` 忽略 `COMIC_RAG_REWRITE` 开关 —— 深度路径（口语型查询）专用：
    那条路径上改写是必需的一环，不能被全局默认值关掉。
    """
    if not force and not config.REWRITE_ENABLED:
        return []
    if not available():
        return []
    query = (query or "").strip()
    if not query:
        return []
    cached = _CACHE.get(query)
    if cached is not None:
        return list(cached)

    count = int(n or config.REWRITE_VARIANTS)
    try:
        response = _build_llm().invoke(_PROMPT.format(n=count, query=query))
        variants = [v for v in _parse(getattr(response, "content", "")) if v != query]
    except Exception as exc:  # noqa: BLE001 —— 改写失败不能拖垮检索
        _log.warning("查询改写失败（%s）：%s；本次只用原句", type(exc).__name__, exc)
        return []

    variants = list(dict.fromkeys(variants))[:count]
    _CACHE[query] = variants
    return variants
