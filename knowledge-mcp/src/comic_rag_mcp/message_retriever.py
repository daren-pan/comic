"""message 数据源的 MCP 检索 / 回读。

与项目文档检索分开：消息是动态、短文本、按条索引；MCP 只读本地
`project_kb_message_*` 集合，不调用内部接口，也不碰 MySQL。
"""
from __future__ import annotations

import time

from . import config, message_indexer


class MessageIndexError(RuntimeError):
    """消息索引未就绪。"""


def _ready() -> None:
    manifest = message_indexer.read_manifest()
    if not manifest:
        raise MessageIndexError(
            "message 索引不存在。先运行：bash scripts/dev.sh message-index"
        )
    if manifest.get("collection") != config.message_collection_name():
        raise MessageIndexError(
            "message 索引配置已变化。重新运行：bash scripts/dev.sh message-index --full"
        )
    if int(manifest.get("count") or 0) <= 0:
        raise MessageIndexError(
            "message 索引为空。运行：bash scripts/dev.sh message-index --full"
        )


def _snippet(text: str, size: int = 320) -> str:
    text = " ".join((text or "").split())
    return text[:size] + ("…" if len(text) > size else "")


def _where(level: str | None, kind: str | None) -> dict | None:
    clauses = []
    if level:
        clauses.append({"level": str(level)})
    if kind:
        clauses.append({"kind": str(kind)})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def search(
    query: str,
    *,
    top_k: int = 5,
    level: str | None = None,
    kind: str | None = None,
    min_score: float | None = config.MESSAGE_MIN_SCORE,
) -> dict:
    """检索 message 索引；返回精简命中，不返回全文。"""
    query = (query or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    _ready()
    top_k = max(1, min(int(top_k), 10))
    started = time.perf_counter()

    from comic_chat.rag.embeddings import get_embeddings

    collection = message_indexer._collection()
    total = int(collection.count())
    if total <= 0:
        raise MessageIndexError(
            "message 索引为空。运行：bash scripts/dev.sh message-index --full"
        )
    result = collection.query(
        query_embeddings=[get_embeddings().embed_query(query)],
        n_results=max(1, min(top_k * 3, total)),
        where=_where(level, kind),
        include=["documents", "metadatas", "distances"],
    )
    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    hits = []
    seen: set[str] = set()
    for index, doc_id in enumerate(ids):
        meta = metas[index] or {}
        if doc_id in seen:
            continue
        score = 1.0 - float(distances[index])
        if min_score is not None and score < float(min_score):
            continue
        seen.add(doc_id)
        hits.append({
            "doc_id": doc_id,
            "message_id": meta.get("message_id"),
            "title": meta.get("title", ""),
            "kind": meta.get("kind", ""),
            "level": meta.get("level", ""),
            "source": meta.get("source_name", ""),
            "task_id": meta.get("task_id", ""),
            "created_at": meta.get("created_at", ""),
            "score": round(score, 4),
            "snippet": _snippet(docs[index] if index < len(docs) else ""),
        })
        if len(hits) >= top_k:
            break

    return {
        "query": query,
        "source": "message",
        "hits": hits,
        "count": len(hits),
        "collection": config.message_collection_name(),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "hint": "需要全文时调用 read_message(doc_id=...)。",
    }


def read(doc_id: str) -> dict:
    """按 doc_id 回读一条消息的完整文本。"""
    doc_id = (doc_id or "").strip()
    if not doc_id:
        raise ValueError("doc_id 不能为空")
    if not doc_id.startswith("message:"):
        raise ValueError("doc_id 必须是 message:<id>")
    _ready()
    collection = message_indexer._collection()
    # 按 metadata 查（集合主键可能是自动生成的 uuid，不等于 doc_id）
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
    text = (result.get("documents") or [""])[0] or ""
    return {
        "doc_id": ids[0],
        "message_id": meta.get("message_id"),
        "title": meta.get("title", ""),
        "kind": meta.get("kind", ""),
        "level": meta.get("level", ""),
        "source": meta.get("source_name", ""),
        "task_id": meta.get("task_id", ""),
        "username": meta.get("username", ""),
        "min_role": meta.get("min_role", ""),
        "created_at": meta.get("created_at", ""),
        "content": text,
        "truncated": "…（已截断）" in text,
    }


def stats() -> dict:
    return message_indexer.stats()
