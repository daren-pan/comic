"""MCP 检索 vs 不检索的延迟 / 准确率小基准。

用途：回答“简单/复杂问题下，调 MCP 和不调 MCP 到底差多少”。

四种模式：

| 模式 | 链路 |
|---|---|
| `direct` | 不检索、不读文件，直接让模型答（下限基线，不是真实 Agent） |
| `file_agent` | 不调 MCP：词面检索文件 → 读命中窗口 → 模型答（模拟 grep/read） |
| `mcp_single` | MCP 检索 + 一次模型生成（理想的一次性 RAG） |
| `mcp_agent` | 先让模型决定检索词（1 次模型调用）→ MCP 检索 → 再生成（第 2 次模型调用） |

`mcp_agent` 才是 Agent + MCP 的真实结构；它比 `mcp_single` 多的就是
“决策/工具调用”那一轮模型调用。`file_agent` 是“不调 MCP 的真实 Agent”的近似。

运行（在仓库根）：

```bash
PYTHONPATH="knowledge-mcp/src;chat-service/src;comic-core/src" \
  crawler-service/.venv/Scripts/python.exe knowledge-mcp/bench.py
```

⚠️ 会真实调用对话模型（读 `chat-service/src/comic_chat/rag/.env` 的 key），
产生少量 token 费用；不会回显 key。
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for rel in ("knowledge-mcp/src", "chat-service/src", "comic-core/src"):
    path = str(ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)

# DSH 受限会话的临时目录 / 模型缓存，必须在 chromadb 导入前准备。
from comic_chat.runtime_env import prepare  # noqa: E402

prepare()

from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from comic_chat.rag.chain import _build_llm  # noqa: E402
from comic_chat.rag import settings  # noqa: E402
from comic_rag_mcp import config  # noqa: E402
from comic_rag_mcp.corpus import iter_markdown_files  # noqa: E402
from comic_rag_mcp.retriever import _lexical_tokens  # noqa: E402

BASE_SYSTEM = """你是「聚漫画」项目的技术助手。
只依据提供的资料回答；资料里没有的信息，直接说「资料里没有」，不要编造。
用简体中文，尽量控制在 3 句话以内。"""

PLANNER_SYSTEM = """你是检索规划器。用户会问一个关于 comic 项目的问题。
你只有一个工具：search_knowledge(query)。
请判断是否需要检索，并给出最适合检索的短查询。
只输出 JSON，不要解释：
{"query": "检索词"}
如果问题完全不需要项目知识，输出 {"query": ""}。"""


@dataclass
class Case:
    qid: str
    kind: str  # simple / complex
    question: str
    must: list[str]
    expect_path: str = ""


CASES = [
    Case("S1", "simple", "本地开发时 MySQL 的宿主端口是多少？", ["3309"], "AGENTS.md"),
    Case("S2", "simple", "chat-service 监听哪个端口？", ["8001"], "chat-service/README.md"),
    Case("S3", "simple", "api-service 的健康检查路径是什么？", ["/api/health"], "api-service/README.md"),
    Case(
        "S4",
        "simple",
        "scheduler 的运行态写进哪个文件？",
        ["schedule_state.json"],
        "comic-scheduler/README.md",
    ),
    Case(
        "C1",
        "complex",
        "scheduler 为什么独立成进程？它和 api 通过哪三个文件交换？分别谁写谁读？",
        ["独立", "schedule.json", "schedule_state.json", "schedule_run_now.json"],
        "comic-scheduler/README.md",
    ),
    Case(
        "C2",
        "complex",
        "JWT 角色有哪三档？两道门分别是什么？",
        ["user", "admin", "superadmin", "require_admin", "require_superadmin"],
        "docs/auth.md",
    ),
    Case(
        "C3",
        "complex",
        "消息中心的可见范围由哪两个字段决定？已读记录在哪张表？",
        ["to_user_id", "min_role", "message_read"],
        "api-service/README.md",
    ),
    Case(
        "C4",
        "complex",
        "chat-service 的索引目录和集合名前缀是什么？为什么它要单独一个容器？",
        ["rag_lab", "comic_kb", "独立"],
        "chat-service/README.md",
    ),
]


#: 问句里的功能词，不参与文件词面打分。
_STOP = {
    "多少", "什么", "哪个", "哪些", "怎么", "如何", "为什么", "是否", "可以",
    "需要", "一个", "这个", "那个", "以及", "还是", "分别", "时候", "目前",
    "默认", "具体", "相关", "信息", "问题", "项目", "服务", "内容", "实现",
    "使用", "进行", "没有", "不是", "就是", "如果", "因为", "所以",
}


def _load_file_corpus() -> list[tuple[str, str]]:
    """不调 MCP 时的“文件工具”语料：Markdown + SQL + OpenAPI 原文。"""
    docs: list[tuple[str, str]] = []
    for path in iter_markdown_files(config.ROOT):
        rel = path.resolve().relative_to(config.ROOT).as_posix()
        docs.append((rel, path.read_text(encoding="utf-8", errors="replace")))
    for rel in (config.SQL_SCHEMA_FILE, config.OPENAPI_FILE):
        path = config.ROOT / rel
        if path.is_file():
            docs.append((rel, path.read_text(encoding="utf-8", errors="replace")))
    return docs


FILE_DOCS = _load_file_corpus()
_FILE_DF: Counter[str] = Counter()
for _rel, _text in FILE_DOCS:
    for _token in set(_lexical_tokens(_text)):
        _FILE_DF[_token] += 1
_FILE_IDF = {
    token: math.log((len(FILE_DOCS) + 1) / (df + 1)) + 1
    for token, df in _FILE_DF.items()
}


def _best_window(text: str, tokens: list[str], size: int = 4500) -> str:
    """在文件里找 token 最密集的窗口，模拟“grep 后读附近段落”。"""
    lowered = text.lower()
    half = size // 2
    best_start, best_score = 0, -1
    positions: list[int] = []
    for token in tokens:
        start = 0
        while True:
            index = lowered.find(token, start)
            if index < 0:
                break
            positions.append(index)
            start = index + len(token)
            if len(positions) > 800:  # 防止大 JSON 把扫描拖慢
                break
    for position in positions:
        start = max(0, position - half)
        window = lowered[start : start + size]
        score = sum(
            _FILE_IDF.get(token, 1.0) * min(window.count(token), 5)
            for token in tokens
        )
        if score > best_score:
            best_start, best_score = start, score
    return text[best_start : best_start + size]


def file_retrieve(question: str, *, top_files: int = 3) -> tuple[str, int, list[str]]:
    """不调 MCP 的基线：词面检索文件 → 读命中窗口。

    这不是“全文硬塞”：先按 query 词项给文件打分（TF-IDF），再在文件里取
    token 最密集的 4500 字窗口，模拟 Agent 用 grep/read 找段落。
    """
    started = time.perf_counter()
    tokens = [t for t in _lexical_tokens(question) if t not in _STOP]
    if not tokens:
        tokens = [question.lower()]

    ranked: list[tuple[float, str, str]] = []
    for rel, text in FILE_DOCS:
        lowered = text.lower()
        body_score = sum(
            _FILE_IDF.get(token, 1.0) * min(lowered.count(token), 5)
            for token in tokens
        )
        path_score = 3.0 * sum(
            _FILE_IDF.get(token, 1.0) for token in tokens if token in rel.lower()
        )
        ranked.append((body_score + path_score, rel, text))
    ranked.sort(key=lambda item: item[0], reverse=True)

    context_parts = []
    files: list[str] = []
    for _, rel, text in ranked[:top_files]:
        files.append(rel)
        context_parts.append(f"【文件】{rel}\n{_best_window(text, tokens)}")
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return "\n\n".join(context_parts), elapsed_ms, files


def score(answer: str, must: list[str]) -> float:
    """极简关键词评分：全中 1.0，中一半 0.5，否则 0。

    角色题允许中英文同义词（文档里用 `user/admin/superadmin`，模型常答
    “普通用户/管理员/超级管理员”）。
    """
    # 去掉空白 / 下划线 / 连字符：兼容 to_user_id 与 toUserId 两种写法。
    normalized = re.sub(r"[\s_-]+", "", answer.lower())
    # 先替换长词，避免“超级管理员”被“管理员”先吃掉。
    for source, target in (
        ("超级管理员", "superadmin"),
        ("超级管理", "superadmin"),
        ("普通用户", "user"),
        ("管理员", "admin"),
    ):
        normalized = normalized.replace(source, target)
    matched = 0
    for term in must:
        needle = re.sub(r"[\s_-]+", "", term.lower())
        if needle and needle in normalized:
            matched += 1
    if matched == len(must):
        return 1.0
    # 答案明确说“资料里没有”时，不能因为里面顺带提到关键词就算对。
    negative = any(
        marker in normalized
        for marker in ("资料里没有", "没有提到", "未提及", "没有明确", "无法回答", "不知道")
    )
    if negative and matched < len(must):
        return 0.0 if len(must) <= 3 else 0.25
    if matched >= max(1, len(must) / 2):
        return 0.5
    return 0.0


def parse_planner_query(text: str, fallback: str) -> str:
    text = text.strip()
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        try:
            payload = json.loads(match.group(0))
            query = str(payload.get("query") or "").strip()
            return query or fallback
        except Exception:
            pass
    return fallback


def _usage(response) -> dict:
    meta = getattr(response, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or meta.get("usage") or {}
    return usage if isinstance(usage, dict) else {}


async def call_llm(llm, system: str, human: str) -> tuple[str, int, dict]:
    started = time.perf_counter()
    response = await asyncio.to_thread(
        llm.invoke,
        [SystemMessage(content=system), HumanMessage(content=human)],
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    content = response.content
    if isinstance(content, list):
        content = "".join(str(part) for part in content)
    return str(content).strip(), elapsed_ms, _usage(response)


async def mcp_retrieve(
    session: ClientSession, query: str, *, top_k: int = 3, read_top: int = 3
) -> tuple[str, int, list[dict]]:
    """检索 + 回读前 N 个父小节，返回拼好的 context / 耗时 / hits。

    回读 top3 是有意为之：chat-service 也是拿 top4 的完整短文档；只读 top1
    会让“一个事实在第二个小节”这类问题被误判成“资料里没有”。
    """
    started = time.perf_counter()
    result = await session.call_tool(
        "search_knowledge", {"query": query, "top_k": top_k}
    )
    if result.isError:
        raise RuntimeError(result.content[0].text)
    payload = json.loads(result.content[0].text)
    hits = payload.get("hits") or []
    retrieve_ms = int((time.perf_counter() - started) * 1000)

    context_parts: list[str] = []
    for index, hit in enumerate(hits[:read_top], start=1):
        read_started = time.perf_counter()
        read_result = await session.call_tool(
            "read_knowledge", {"doc_id": hit["doc_id"]}
        )
        retrieve_ms += int((time.perf_counter() - read_started) * 1000)
        if read_result.isError:
            continue
        body = json.loads(read_result.content[0].text)
        context_parts.append(
            f"【资料 {index}】{body.get('path')} / {body.get('heading_path')}\n"
            f"{str(body.get('content', ''))[:3500]}"
        )
    for index, hit in enumerate(hits[read_top:], start=read_top + 1):
        context_parts.append(
            f"【资料 {index}】{hit.get('path')} / {hit.get('heading_path')}\n"
            f"{hit.get('snippet', '')}"
        )
    return "\n\n".join(context_parts), retrieve_ms, hits


async def run_case(
    mode: str, case: Case, llm, session: ClientSession
) -> dict:
    started = time.perf_counter()
    planner_ms = 0
    retrieve_ms = 0
    llm_ms = 0
    hits: list[dict] = []
    files: list[str] = []
    context = ""

    if mode == "direct":
        answer, llm_ms, usage = await call_llm(llm, BASE_SYSTEM, case.question)
    elif mode == "file_agent":
        context, retrieve_ms, files = file_retrieve(case.question)
        system = f"{BASE_SYSTEM}\n\n【参考资料】\n{context}"
        answer, llm_ms, usage = await call_llm(llm, system, case.question)
    elif mode == "mcp_single":
        context, retrieve_ms, hits = await mcp_retrieve(
            session, case.question, top_k=3, read_top=3
        )
        system = f"{BASE_SYSTEM}\n\n【参考资料】\n{context}"
        answer, llm_ms, usage = await call_llm(llm, system, case.question)
    elif mode == "mcp_agent":
        planner_answer, planner_ms, _ = await call_llm(
            llm, PLANNER_SYSTEM, case.question
        )
        query = parse_planner_query(planner_answer, case.question)
        context, retrieve_ms, hits = await mcp_retrieve(
            session, query, top_k=3, read_top=3
        )
        system = f"{BASE_SYSTEM}\n\n【参考资料】\n{context}"
        answer, llm_ms, usage = await call_llm(llm, system, case.question)
    else:
        raise ValueError(mode)

    total_ms = int((time.perf_counter() - started) * 1000)
    usage = usage or {}
    return {
        "mode": mode,
        "qid": case.qid,
        "kind": case.kind,
        "question": case.question,
        "answer": answer,
        "score": score(answer, case.must),
        "total_ms": total_ms,
        "llm_ms": llm_ms,
        "planner_ms": planner_ms,
        "retrieve_ms": retrieve_ms,
        "files_read": len(files) if files else (min(3, len(hits)) if hits else 0),
        "context_chars": len(context),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "hit_top": (files[0] if files else (hits[0]["path"] if hits else "")),
        "hit_heading": hits[0]["heading"] if hits else "",
        "usage": usage,
    }


def aggregate(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["mode"], row["kind"]), []).append(row)
    output = []
    for (mode, kind), items in sorted(groups.items()):
        totals = [item["total_ms"] for item in items]
        output.append(
            {
                "mode": mode,
                "kind": kind,
                "n": len(items),
                "avg_total_ms": round(statistics.mean(totals)),
                "p50_total_ms": round(statistics.median(totals)),
                "avg_llm_ms": round(statistics.mean(item["llm_ms"] for item in items)),
                "avg_retrieve_ms": round(
                    statistics.mean(item["retrieve_ms"] for item in items)
                ),
                "avg_files": round(
                    statistics.mean(item["files_read"] for item in items), 1
                ),
                "avg_context_chars": round(
                    statistics.mean(item["context_chars"] for item in items)
                ),
                "avg_prompt_tokens": round(
                    statistics.mean(item["prompt_tokens"] for item in items)
                ),
                "avg_completion_tokens": round(
                    statistics.mean(item["completion_tokens"] for item in items)
                ),
                "avg_score": round(statistics.mean(item["score"] for item in items), 2),
            }
        )
    return output


async def main() -> None:
    import os

    if not settings.llm_ready():
        print("COMIC_LLM_API_KEY 未配置，无法跑模型基准", file=sys.stderr)
        raise SystemExit(2)

    llm = _build_llm(0.0, True)  # 关 thinking，降低方差
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "knowledge-mcp" / "run_mcp.py")],
        env=dict(os.environ),
        cwd=str(ROOT),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 预热：MCP 首次检索会加载 bge；模型首次调用会建 TLS 连接。
            warm_mcp = time.perf_counter()
            await session.call_tool(
                "search_knowledge", {"query": "预热", "top_k": 1}
            )
            mcp_warm_ms = int((time.perf_counter() - warm_mcp) * 1000)
            warm_llm = time.perf_counter()
            await call_llm(llm, "只回复 ok", "ok")
            llm_warm_ms = int((time.perf_counter() - warm_llm) * 1000)
            print(f"warmup: mcp={mcp_warm_ms}ms llm={llm_warm_ms}ms")

            print(f"file corpus: {len(FILE_DOCS)} files")
            rows: list[dict] = []
            for mode in ("direct", "file_agent", "mcp_single", "mcp_agent"):
                for case in CASES:
                    row = await run_case(mode, case, llm, session)
                    rows.append(row)
                    print(
                        f"{mode:10s} {case.qid:2s} {case.kind:7s} "
                        f"total={row['total_ms']:5d}ms "
                        f"llm={row['llm_ms']:5d}ms "
                        f"ret={row['retrieve_ms']:4d}ms "
                        f"files={row['files_read']} "
                        f"ctx={row['context_chars']:5d} "
                        f"tok={row['prompt_tokens']:4d}/{row['completion_tokens']:3d} "
                        f"score={row['score']:.1f} "
                        f"top={row['hit_top'] or '-'}"
                    )

    print("\n=== 汇总 ===")
    for item in aggregate(rows):
        print(
            f"{item['mode']:10s} {item['kind']:7s} n={item['n']} "
            f"avg={item['avg_total_ms']}ms p50={item['p50_total_ms']}ms "
            f"llm={item['avg_llm_ms']}ms ret={item['avg_retrieve_ms']}ms "
            f"files={item['avg_files']} ctx={item['avg_context_chars']} "
            f"tok={item['avg_prompt_tokens']}/{item['avg_completion_tokens']} "
            f"score={item['avg_score']}"
        )

    out = ROOT / "knowledge-mcp" / "bench_results.json"
    out.write_text(
        json.dumps({"rows": rows, "aggregate": aggregate(rows)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n明细已写入 {out}")


if __name__ == "__main__":
    asyncio.run(main())
