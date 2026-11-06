"""检索与回读：MCP 的 `search_knowledge` / `read_knowledge` 真正干活的地方。

检索只返回**精简命中**（默认 top 5、snippet 300 字），全文由 `read_knowledge` 按
`parent_start` / `parent_end` 回源读取 —— 避免把整篇文档塞进 Agent 上下文。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from . import config, indexer, lexical, tokenizer

_log = logging.getLogger(__name__)


def _where(kind: str | None, module: str | None) -> dict | None:
    clauses = []
    if kind:
        clauses.append({"kind": kind})
    if module:
        clauses.append({"module": module})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _snippet(text: str, limit: int = 300) -> str:
    one_line = " ".join((text or "").split())
    if len(one_line) <= limit:
        return one_line
    return one_line[:limit].rstrip() + "…"


def _lexical_tokens(query: str) -> list[str]:
    """词项（**去重**），用于标题 / 模块 / 正文的命中比例加权。

    切法统一由 `tokenizer` 决定（`jieba` 或 `bigram`，见 `COMIC_KB_TOKENIZER`），
    这里只负责去重 —— 加权算的是"命中比例"，同一个词重复出现不该重复计分。

    ⚠️ 换分词器会改变加权分母（`len(tokens)`），进而改变排序。
    这是**打分刻度变化**，不是 bug：换后端后必须重跑评估集并重标阈值。
    """
    return tokenizer.unique_tokens(query)


def _heading_boost(query: str, meta: dict) -> float:
    """标题/路径命中给一点加权（最多 0.12），不改变向量分的主体地位。"""
    tokens = _lexical_tokens(query)
    if not tokens:
        return 0.0
    # ⚠️ 只用 section heading，不用 title / path：文档标题对所有 chunk 都一样，
    #    拿它加权会让“同一篇文档的所有 chunk”一起涨，反而淹没真正匹配的小节。
    haystack = str(meta.get("heading", "")).lower()
    matched = sum(1 for token in tokens if token in haystack)
    return round(min(0.12, 0.12 * matched / len(tokens)), 4)


#: 查询意图 → 模块；只做很小的加分，不替代向量检索。
_MODULE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("crawler", ("爬虫", "源站", "采集", "source", "adapter", "封面", "图床", "占位图", "图片")),
    ("scheduler", ("定时", "scheduler", "cron")),
    ("chat", ("chat", "rag", "向量", "embedding", "客服")),
    ("api", ("api", "接口", "鉴权", "jwt", "登录", "token", "消息", "已读", "管理台")),
    # `core` 必须排在 `deploy` 前面：`mysql` 是强信号，而“端口”太泛，
    # 否则“MySQL 宿主端口”会被误判成部署模块。
    ("core", ("comic-core", "数据库", "mysql", "表", "schema", "迁移")),
    ("deploy", ("部署", "docker", "compose", "nginx", "端口", "上线")),
    ("web", ("comic-web", "vue")),
    ("front", ("comic-front", "uni-app")),
)


def _module_hint(query: str) -> str:
    lowered = query.lower()
    for module, words in _MODULE_HINTS:
        if any(word in lowered for word in words):
            return module
    return ""


def _module_boost(meta: dict, hint: str) -> float:
    if not hint:
        return 0.0
    if meta.get("module") == hint:
        return 0.06
    # 表结构 / 接口文档虽然模块不同，但经常是同一问题的权威答案。
    if hint == "api" and meta.get("kind") == "schema":
        return 0.03
    return 0.0


def _body_boost(query: str, text: str) -> float:
    """正文关键词命中给一点加权（最多 0.08）。

    纯向量对“端口 / 文件名 / 表名”这类精确事实经常排不到最前；正文词面重合
    是最便宜的补充信号，不引入第二套检索服务。

    ⚠️ 上限不能太大：`knowledge-mcp/NOTES` 这类自文档会引用真实问题原句，
    0.10 足以把“讲这个查询的笔记”顶到真正答案前面；0.08 能保留词面收益，
    又不会压过 heading/module 的正确信号。
    """
    tokens = _lexical_tokens(query)
    if not tokens:
        return 0.0
    # 去掉第一行 heading，避免和 heading_boost 重复计分。
    body = "\n".join((text or "").splitlines()[1:]).lower()
    if not body:
        return 0.0
    matched = sum(1 for token in tokens if token in body)
    return round(min(0.08, 0.08 * matched / len(tokens)), 4)


def _hit(
    doc,
    score: float,
    vector_score: float,
    heading_boost: float,
    module_boost: float,
    body_boost: float,
    *,
    lexical_score: float | None = None,
    rrf: float | None = None,
    sources: list[str] | None = None,
    matched: tuple[str, ...] | None = None,
) -> dict:
    """单条命中 → 展示结构。

    `sources` / `rrf` / `lexical_score` / `matched_terms` 是**混合检索的可观测性**：
    看到一条结果时，第一句话往往是"它凭什么在这"。没有这几个字段，融合层就是黑盒。
    """
    meta = doc.metadata or {}
    return {
        "doc_id": meta.get("doc_id") or getattr(doc, "id", ""),
        "title": meta.get("title", ""),
        "path": meta.get("path", ""),
        "heading": meta.get("heading", ""),
        "heading_path": meta.get("heading_path", ""),
        "kind": meta.get("kind", ""),
        "module": meta.get("module", ""),
        "status": meta.get("status", "current"),
        "score": round(float(score), 4),
        "vector_score": round(float(vector_score), 4),
        "heading_boost": round(float(heading_boost), 4),
        "module_boost": round(float(module_boost), 4),
        "body_boost": round(float(body_boost), 4),
        "sources": list(sources or []),
        "rrf": None if rrf is None else round(float(rrf), 6),
        "lexical_score": (
            None if lexical_score is None else round(float(lexical_score), 4)
        ),
        "matched_terms": list(matched or ()),
        "snippet": _snippet(doc.page_content),
        "start_line": meta.get("start_line", 0),
        "parent_start": meta.get("parent_start", 0),
        "parent_end": meta.get("parent_end", 0),
    }


#: `search()` 支持的三种模式。
_MODES = ("hybrid", "vector", "lexical")


def _rrf_merge(
    ranked: list[tuple[str, list[str]]], k: int
) -> dict[str, dict]:
    """Reciprocal Rank Fusion：多路结果**只按名次**合并。

    `ranked = [(来源名, 已按相关性排好的 doc_id 列表), ...]`

    为什么不用分数相加：向量分是 0~1 余弦、BM25 是无上界实数，两者**不可比**。
    直接相加，量级大的那一路永远赢，等于另一路白做。
    """
    fused: dict[str, dict] = {}
    for label, doc_ids in ranked:
        for rank, doc_id in enumerate(doc_ids, start=1):
            item = fused.setdefault(doc_id, {"rrf": 0.0, "sources": [], "ranks": {}})
            item["rrf"] += 1.0 / (k + rank)
            item["sources"].append(label)
            item["ranks"][label] = rank
    return fused


def _passes(meta: dict, kind: str | None, module: str | None, include_historical: bool) -> bool:
    """向量那路的 `filter=...` 在词面那路没有对应能力，只能后置过滤，保持两边口径一致。"""
    if kind and meta.get("kind") != kind:
        return False
    if module and meta.get("module") != module:
        return False
    if not include_historical and meta.get("status") == "historical":
        return False
    return True


def search(
    query: str,
    *,
    top_k: int = config.TOP_K,
    kind: str | None = None,
    module: str | None = None,
    include_historical: bool = False,
    min_score: float | None = config.MIN_SCORE,
    mode: str | None = None,
) -> dict:
    """检索；默认**双路 + RRF 融合**，返回精简命中（不返回全文）。

    | mode | 行为 | 用途 |
    |---|---|---|
    | `hybrid`（默认） | 向量 + BM25，按名次融合 | 生产 |
    | `vector` | 只走语义 | 回退 / 对照（等价于改动前） |
    | `lexical` | 只走 BM25 | 调试"字面到底能捞到什么" |

    ⚠️ **阈值只作用在向量那一路**（`min_score`）：融合后的 RRF 分是 `1/(60+名次)`
    量级（约 0.016），拿 0.45 去卡会一条不剩。这是刻度问题，不是阈值该不该留。
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    top_k = max(1, min(int(top_k), 10))
    mode = (mode or ("hybrid" if config.HYBRID_ENABLED else "vector")).strip().lower()
    if mode not in _MODES:
        raise ValueError(f"未知的检索模式：{mode}（可选：{' / '.join(_MODES)}）")
    started = time.perf_counter()

    # 索引缺失/为空时明确报错，不能返回空 hits 让 Agent 误以为“资料不存在”。
    indexer.ensure_ready()
    store = indexer.get_store()
    # 多取一些候选：先按 metadata 过滤，再在后处理里剔除 historical。
    pairs = store.similarity_search_with_relevance_scores(
        query,
        k=max(top_k * 4, top_k),
        filter=_where(kind, module),
    )

    # ---- ① 向量那一路：现有逻辑原样保留（含三种 boost 与阈值）----
    hint = _module_hint(query)
    vector: dict[str, tuple] = {}
    for doc, score in pairs:
        meta = doc.metadata or {}
        if not include_historical and meta.get("status") == "historical":
            continue
        vector_score = float(score)
        heading_boost = _heading_boost(query, meta)
        module_boost = _module_boost(meta, hint)
        body_boost = _body_boost(query, doc.page_content)
        final_score = vector_score + heading_boost + module_boost + body_boost
        if min_score is not None and final_score < float(min_score):
            continue
        doc_id = str(meta.get("doc_id") or getattr(doc, "id", ""))
        vector[doc_id] = (final_score, vector_score, heading_boost, module_boost, body_boost, doc)
    # boost 可能改变顺序；先排好，融合时才有名次可用。
    vector_order = [d for d, _ in sorted(vector.items(), key=lambda kv: -kv[1][0])]

    # ---- ② 词面那一路（BM25）----
    lex_map: dict[str, object] = {}
    lex_order: list[str] = []
    if mode in {"lexical", "hybrid"}:
        try:
            for hit in lexical.get_index().search(query, config.LEXICAL_TOP_K):
                lex_map[hit.doc_id] = hit
                lex_order.append(hit.doc_id)
        except Exception as exc:  # noqa: BLE001 —— 词面挂了不该拖垮整条检索
            _log.warning("词面索引不可用（%s）：%s；本次仅向量", type(exc).__name__, exc)

    # ---- ③ 回填正文：词面那一路只带了 doc_id ----
    docs: dict[str, object] = {doc_id: payload[5] for doc_id, payload in vector.items()}
    missing = [d for d in lex_order if d not in docs]
    if missing:
        docs.update(indexer.documents_by_ids(missing))
    lex_order = [
        d
        for d in lex_order
        if d in docs and _passes((docs[d].metadata or {}), kind, module, include_historical)
    ]

    # ---- ④ 排序：按模式决定用哪个分数 ----
    if mode == "vector":
        ordered = [(d, vector[d][0], None, ["vector"]) for d in vector_order]
    elif mode == "lexical":
        ordered = [(d, lex_map[d].score, None, ["lexical"]) for d in lex_order]
    else:
        fused = _rrf_merge(
            [("vector", vector_order), ("lexical", lex_order)], config.RRF_K
        )
        ordered = [
            (doc_id, info["rrf"], info["rrf"], info["sources"])
            for doc_id, info in sorted(fused.items(), key=lambda kv: (-kv[1]["rrf"], kv[0]))
        ]

    # ---- ⑤ 去重取 top_k：同一 H2/H3 的多个 child 只留分最高的一个 ----
    hits: list[dict] = []
    seen_sections: set[tuple[str, str]] = set()
    for doc_id, score, rrf, sources in ordered:
        doc = docs.get(doc_id)
        if doc is None:
            continue
        meta = doc.metadata or {}
        if not _passes(meta, kind, module, include_historical):
            continue
        # 只有向量那路给出的 doc 才在 vector 里；纯词面命中没有 vector 分。
        payload = vector.get(doc_id)
        if payload is not None:
            _, vector_score, heading_boost, module_boost, body_boost = payload[:5]
        else:
            vector_score = heading_boost = module_boost = body_boost = 0.0
        lex_hit = lex_map.get(doc_id)
        key = (str(meta.get("path", "")), str(meta.get("heading_path", "")))
        if key in seen_sections:
            continue
        seen_sections.add(key)
        hits.append(
            _hit(
                doc,
                score,
                vector_score,
                heading_boost,
                module_boost,
                body_boost,
                lexical_score=(lex_hit.score if lex_hit is not None else None),
                rrf=rrf,
                sources=sources,
                matched=(lex_hit.matched if lex_hit is not None else ()),
            )
        )
        if len(hits) >= top_k:
            break

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "query": query,
        "mode": mode,
        "hits": hits,
        "count": len(hits),
        "backend": config.embedding_info()["backend"],
        "collection": config.collection_name(),
        "candidates": {"vector": len(vector_order), "lexical": len(lex_order)},
        "elapsed_ms": elapsed_ms,
        "hint": "需要全文时调用 read_knowledge(doc_id=...)。",
    }


def _load_from_file(meta: dict) -> tuple[str, bool]:
    rel = str(meta.get("path") or "")
    if not rel:
        return "", False
    root = config.ROOT.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return "", False
    if path.suffix.lower() not in {".md", ".sql", ".json"}:
        return "", False
    start = int(meta.get("parent_start") or 0)
    end = int(meta.get("parent_end") or 0)
    if start <= 0 or end < start:
        return "", False
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    text = "\n".join(lines[start - 1 : end])
    truncated = False
    if len(text) > config.READ_MAX_CHARS:
        text = text[: config.READ_MAX_CHARS].rstrip() + "\n\n…（已截断，原文见文件）"
        truncated = True
    return text, truncated


def _raw_collection():
    """只读 collection 句柄：不构造 embedding，避免 `read_knowledge` 白加载一次模型。"""
    import chromadb

    client = chromadb.PersistentClient(path=str(config.INDEX_DIR))
    try:
        return client.get_collection(config.collection_name())
    except Exception as exc:  # noqa: BLE001
        raise indexer.KnowledgeIndexError(
            "知识库集合不存在。先运行：bash scripts/dev.sh knowledge-index"
        ) from exc


def read(doc_id: str) -> dict:
    """按 doc_id 回读：Markdown/SQL 读 section 行号；OpenAPI 读完整 chunk。"""
    doc_id = (doc_id or "").strip()
    if not doc_id:
        raise ValueError("doc_id 不能为空")

    indexer.ensure_ready()
    collection = _raw_collection()
    result = collection.get(ids=[doc_id], include=["documents", "metadatas"])
    ids = result.get("ids") or []
    if not ids:
        # 兼容：某些版本 / 手工写入时 id 与 metadata.doc_id 不一致。
        result = collection.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
        ids = result.get("ids") or []
    if not ids:
        raise KeyError(f"未找到 doc_id：{doc_id}")

    meta = (result.get("metadatas") or [{}])[0] or {}
    chunk_text = (result.get("documents") or [""])[0] or ""
    text, truncated = "", False
    if meta.get("read_mode") == "lines":
        text, truncated = _load_from_file(meta)
    if not text:
        text = chunk_text
        if len(text) > config.READ_MAX_CHARS:
            text = text[: config.READ_MAX_CHARS].rstrip() + "\n\n…（已截断）"
            truncated = True

    return {
        "doc_id": meta.get("doc_id") or ids[0],
        "path": meta.get("path", ""),
        "title": meta.get("title", ""),
        "heading": meta.get("heading", ""),
        "heading_path": meta.get("heading_path", ""),
        "kind": meta.get("kind", ""),
        "module": meta.get("module", ""),
        "status": meta.get("status", "current"),
        "start_line": meta.get("parent_start", meta.get("start_line", 0)),
        "end_line": meta.get("parent_end", meta.get("end_line", 0)),
        "content": text,
        "truncated": truncated,
    }


def stats(*, detail: bool = False) -> dict:
    """索引摘要；默认不返回完整 manifest，避免 Agent 上下文被文件清单淹没。"""
    return indexer.stats(detail=detail, live=False)
