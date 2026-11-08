"""检索与回读：MCP 的 `search_knowledge` / `read_knowledge` 真正干活的地方。

检索只返回**精简命中**（默认 top 5、snippet 300 字），全文由 `read_knowledge` 按
`parent_start` / `parent_end` 回源读取 —— 避免把整篇文档塞进 Agent 上下文。
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from . import config, indexer, lexical, rerank, tokenizer

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


#: 三种检索模式的**中文名** —— 界面、命令行、文档统一用它。
#: 代码与配置仍用英文键（`vector` / `lexical` / `hybrid`），只在这层做展示与别名归一。
MODE_LABELS: dict[str, str] = {
    "vector": "语义检索",
    "lexical": "字面检索",
    "hybrid": "混合检索",
}

#: 允许用户直接写中文（`--mode 语义检索` / `?mode=混合`）。
MODE_ALIASES: dict[str, str] = {
    **{key: key for key in MODE_LABELS},
    **{label: key for key, label in MODE_LABELS.items()},
    "向量": "vector",
    "语义": "vector",
    "词面": "lexical",
    "字面": "lexical",
    "关键词": "lexical",
    "混合": "hybrid",
    "融合": "hybrid",
}


def normalize_mode(value: str | None) -> str:
    """把用户输入的模式名归一成英文键；无法识别时抛出带中文提示的错误。"""
    if not value:
        return "hybrid" if config.HYBRID_ENABLED else "vector"
    key = MODE_ALIASES.get(str(value).strip())
    if key is None:
        choices = " / ".join(f"{label}（{k}）" for k, label in MODE_LABELS.items())
        raise ValueError(f"未知的检索模式：{value!r}。可选：{choices}")
    return key


def mode_label(mode: str) -> str:
    """英文键 → 中文名（未知原样返回）。"""
    return MODE_LABELS.get(mode, mode)


#: 语义分的加成策略：`module`（默认）/ `none` / `heading` / `body` / `all`。
#: 标准检索器只给余弦；加成是我们自己的业务后处理，所以做成可关可换的。
#: 实测（20 条黄金题，语义检索）：module → Recall 20/20、MRR 0.950、Top-1 90%；
#: none → 18/20、0.810、75%；all（三项全开）→ 20/20、0.825、70%。
BOOST_MODE = os.environ.get("COMIC_RAG_BOOST", "module")

#: 查询意图 → 模块；只做很小的加分，不替代语义检索。
_MODULE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("crawler", ("爬虫", "源站", "采集", "source", "adapter", "封面", "图床", "占位图", "图片")),
    ("scheduler", ("定时", "scheduler", "cron")),
    ("chat", ("chat", "rag", "向量", "embedding", "客服")),
    ("api", ("api", "接口", "鉴权", "jwt", "登录", "token", "消息", "已读", "管理台")),
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


def _boost_score(query: str, meta: dict, body_text: str) -> float:
    """语义分的加成（最多 +0.12/+0.06/+0.08，看 `BOOST_MODE`）。

    历史：三项加权全开时语义 Recall 20/20、Top-1 70%；全关时 18/20、Top-1 75%。
    这里保留单项开关，是为了能只留最有用的那一个。
    """
    mode = BOOST_MODE
    if mode == "none":
        return 0.0
    tokens = tokenizer.unique_tokens(query)
    if not tokens:
        return 0.0

    total = 0.0
    if mode in {"heading", "all"}:
        haystack = str(meta.get("heading", "")).lower()
        matched = sum(1 for token in tokens if token in haystack)
        total += min(0.12, 0.12 * matched / len(tokens))
    if mode in {"module", "all"}:
        hint = _module_hint(query)
        if hint and meta.get("module") == hint:
            total += 0.06
        elif hint == "api" and meta.get("kind") == "schema":
            total += 0.03
    if mode in {"body", "all"}:
        body = "\n".join((body_text or "").splitlines()[1:]).lower()
        if body:
            matched = sum(1 for token in tokens if token in body)
            total += min(0.08, 0.08 * matched / len(tokens))
    return round(total, 4)


def _hit(
    doc,
    score: float,
    vector_score: float,
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
    # `page_content` = `heading_path` 前缀 + 正文；前缀是给向量用的拼接痕迹，
    # 展示"命中的那块"时要剥掉，否则和原文对不上。
    page = doc.page_content or ""
    prefix = f"{meta.get('heading_path', '')}\n"
    body_text = page[len(prefix) :] if page.startswith(prefix) else page
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
        "sources": list(sources or []),
        "rrf": None if rrf is None else round(float(rrf), 6),
        "lexical_score": (
            None if lexical_score is None else round(float(lexical_score), 4)
        ),
        "matched_terms": list(matched or ()),
        "body": body_text,
        "snippet": _snippet(doc.page_content),
        "start_line": meta.get("start_line", 0),
        "parent_start": meta.get("parent_start", 0),
        "parent_end": meta.get("parent_end", 0),
    }


#: `search()` 支持的三种模式。
_MODES = ("hybrid", "vector", "lexical")


def _rrf_weights(n_lists: int) -> list[float]:
    """取融合权重：默认等权；`config.RRF_WEIGHTS` 长度不符时退回等权。"""
    configured = list(getattr(config, "RRF_WEIGHTS", []) or [])
    if len(configured) == n_lists and any(w > 0 for w in configured):
        return configured
    return [1.0] * n_lists


def _fuse_ranked(
    ranked: list[tuple[str, list[str]]],
    docs: dict[str, object],
) -> list[tuple[str, float, float | None, list[str]]]:
    """用 LangChain 的 `EnsembleRetriever` 做加权 RRF 融合。

    `ranked = [(来源名, 已按相关性排好的 doc_id 列表), ...]`

    为什么用 RRF 而不是分数相加：向量分是 0~1 余弦、BM25 是无上界实数，两者**不可比**；
    直接相加，量级大的那一路永远赢，等于另一路白做。

    ⚠️ 融合**排序**完全交给 `EnsembleRetriever.weighted_reciprocal_rank`；
    子类只把每个 doc 的融合分留下来给界面展示（父类不返回分数）。
    """
    from langchain_classic.retrievers import EnsembleRetriever
    from langchain_core.documents import Document
    from langchain_core.retrievers import BaseRetriever

    # 空输入直接返回：EnsembleRetriever 在 retrievers=[] 时算权重会除零。
    if not ranked or not any(doc_ids for _, doc_ids in ranked):
        return []

    class _Noop(BaseRetriever):
        """只为满足 `EnsembleRetriever` 的「weights 数 == retrievers 数」校验。

        融合时传的是**已经算好的排名列表**，这两个检索器不会被调用。
        """

        def _get_relevant_documents(self, query, *, run_manager):  # noqa: ANN001
            return []

    class _Scored(EnsembleRetriever):
        scores: dict[str, float] = {}

        def weighted_reciprocal_rank(self, doc_lists):  # noqa: ANN001
            ordered = super().weighted_reciprocal_rank(doc_lists)
            merged: dict[str, float] = {}
            for documents, weight in zip(doc_lists, self.weights):
                for rank, document in enumerate(documents, start=1):
                    key = str(document.metadata[self.id_key])
                    merged[key] = merged.get(key, 0.0) + weight / (rank + self.c)
            self.scores = merged
            return ordered

    doc_lists = [
        [Document(page_content="", metadata={"doc_id": doc_id}) for doc_id in doc_ids]
        for _, doc_ids in ranked
    ]
    ensemble = _Scored(
        retrievers=[_Noop() for _ in ranked],
        # 权重按 `ranked` 顺序给（语义在前、字面在后），由 `config.RRF_WEIGHTS` 控制。
        weights=_rrf_weights(len(ranked)),
        id_key="doc_id",
        c=int(config.RRF_K),
    )
    fused_docs = ensemble.weighted_reciprocal_rank(doc_lists)

    sources_by_id: dict[str, list[str]] = {}
    for label, doc_ids in ranked:
        for doc_id in doc_ids:
            sources_by_id.setdefault(doc_id, []).append(label)

    ordered: list[tuple[str, float, float | None, list[str]]] = []
    for document in fused_docs:
        doc_id = str(document.metadata["doc_id"])
        if doc_id not in docs:
            continue
        score = round(ensemble.scores.get(doc_id, 0.0), 6)
        ordered.append((doc_id, score, score, sources_by_id.get(doc_id, [])))
    return ordered


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
    # 允许传中文（语义检索 / 字面检索 / 混合检索）—— 与界面、命令行统一。
    mode = normalize_mode(mode)
    started = time.perf_counter()

    # 索引缺失/为空时明确报错，不能返回空 hits 让 Agent 误以为“资料不存在”。
    indexer.ensure_ready()
    store = indexer.get_store()

    # ---- ① 语义那一路：LangChain 标准向量检索器 ----
    # `as_retriever(search_type="similarity")` 是 `VectorStoreRetriever`：
    # 它内部就是 `similarity_search_with_relevance_scores` + 按 k 截断。
    # ⚠️ 检索器**只返回 Document、不带分数**，而加权与展示都要分数，
    # 所以再调一次标准 store API 取分数（同一批 k、同一个 filter，集合一致）。
    candidates = max(top_k * 4, top_k)
    where = _where(kind, module)
    # 向量检索的 search_type：similarity（默认）/ mmr（最大边际相关，刻意去冗余）。
    search_type = os.environ.get("COMIC_RAG_VECTOR_SEARCH", "similarity")
    if search_type == "mmr":
        search_kwargs = {"k": candidates, "fetch_k": candidates * 2, "lambda_mult": 0.5}
    else:
        search_kwargs = {"k": candidates}
    if where:
        search_kwargs["filter"] = where
    vector_retriever = store.as_retriever(
        search_type=search_type,
        search_kwargs=search_kwargs,
    )
    candidate_docs = vector_retriever.invoke(query)

    score_by_id: dict[str, float] = {}
    for doc, score in store.similarity_search_with_relevance_scores(
        query, k=candidates, filter=where
    ):
        meta = doc.metadata or {}
        score_by_id[str(meta.get("doc_id") or getattr(doc, "id", ""))] = float(score)

    # 只用于界面高亮「这几个字在正文里出现过」，**不参与打分**。
    query_terms = tokenizer.unique_tokens(query)
    vector: dict[str, tuple] = {}
    for doc in candidate_docs:
        meta = doc.metadata or {}
        if not include_historical and meta.get("status") == "historical":
            continue
        doc_id = str(meta.get("doc_id") or getattr(doc, "id", ""))
        vector_score = score_by_id.get(doc_id)
        if vector_score is None:
            continue
        # 语义分 = 余弦 + 加成（加成策略见 BOOST_MODE；阈值卡的是加权后的分）。
        final_score = vector_score + _boost_score(query, meta, doc.page_content)
        if min_score is not None and final_score < float(min_score):
            continue
        lowered = (doc.page_content or "").lower()
        display_terms = tuple(t for t in query_terms if t in lowered)
        vector[doc_id] = (final_score, vector_score, doc, display_terms)
    # 先排好，融合时才有名次可用。
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
    docs: dict[str, object] = {doc_id: payload[2] for doc_id, payload in vector.items()}
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
        ordered = _fuse_ranked([("vector", vector_order), ("lexical", lex_order)], docs)

    # ---- ④.5 重排（可选，默认关）：把候选真正读一遍，再决定顺序 ----
    if ordered and rerank.enabled():
        ordered = rerank.rerank(query, ordered, docs, top_k)

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
        # 只有语义那路给出的 doc 才在 vector 里；纯字面命中没有语义分。
        payload = vector.get(doc_id)
        if payload is not None:
            _, vector_score, _doc, display_terms = payload
        else:
            vector_score = 0.0
            display_terms = ()
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
                lexical_score=(lex_hit.score if lex_hit is not None else None),
                rrf=rrf,
                sources=sources,
                matched=(lex_hit.matched if lex_hit is not None else display_terms),
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
    # ⚠️ 先按 metadata.doc_id 查：`index()` 写进去的集合主键是内容哈希，
    # 和我们的 doc_id 不是一回事；`get(ids=...)` 只在旧的手工写入索引上才碰得上。
    result = collection.get(
        where={"doc_id": doc_id}, include=["documents", "metadatas"]
    )
    ids = result.get("ids") or []
    if not ids:
        result = collection.get(ids=[doc_id], include=["documents", "metadatas"])
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
