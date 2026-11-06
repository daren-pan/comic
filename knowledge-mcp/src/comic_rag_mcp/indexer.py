"""Chroma 索引构建、就绪检查与新鲜度检测。

与 chat-service 的 `rag_lab` 分开：本模块只写 `project_rag` / `project_kb_*`。
集合名带 embedding + 切分/读取契约版本，换模型或换读法会自动落到新集合。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from langchain_chroma import Chroma

from . import config
from .corpus import CorpusResult


class KnowledgeIndexError(RuntimeError):
    """知识库未就绪 / 配置不匹配；消息应直接展示给用户或 Agent。"""


def get_store() -> Chroma:
    """打开（不存在则创建）项目知识库的 Chroma 句柄。"""
    from comic_chat.rag.embeddings import get_embeddings

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=config.collection_name(),
        embedding_function=get_embeddings(),
        persist_directory=str(config.INDEX_DIR),
        collection_metadata={"hnsw:space": "cosine"},
    )


def raw_collection():
    """只读 collection 句柄：**不构造 embedding**，用于就绪检查和 read。"""
    import chromadb

    client = chromadb.PersistentClient(path=str(config.INDEX_DIR))
    return client.get_collection(config.collection_name())


def raw_collection_count() -> int:
    """真实集合条数；不加载 bge。集合不存在时返回 0。"""
    try:
        return int(raw_collection().count())
    except Exception:
        return 0


def all_documents() -> list[tuple[str, str]]:
    """取出集合里全部 `(doc_id, page_content)`，**不构造 embedding**。

    用途是给词面索引（`lexical.py`）供数据。走 `raw_collection()` 而不是 `get_store()`：
    后者会加载 bge ONNX（约 1 秒），为了数词白付这个代价不划算（与 `read()` 同一考虑）。

    `doc_id` 以 metadata 为准（与 `read()` 的查找口径一致）；缺失时退回 Chroma 的 id。
    """
    collection = raw_collection()
    result = collection.get(include=["documents", "metadatas"])
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or [{} for _ in ids]
    return [
        ((meta or {}).get("doc_id") or doc_id, text or "")
        for doc_id, text, meta in zip(ids, documents, metadatas)
    ]


def documents_by_ids(doc_ids: list[str]) -> dict[str, "Document"]:  # noqa: F821
    """按 `doc_id` 批量取回 Document（**不构造 embedding**）。

    融合时词面那一路只带了 doc_id，需要回填正文与元数据；一次批量取完，避免逐条查。
    """
    if not doc_ids:
        return {}
    collection = raw_collection()
    result = collection.get(ids=list(doc_ids), include=["documents", "metadatas"])
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or [{} for _ in ids]

    from langchain_core.documents import Document

    out: dict[str, Document] = {}
    for doc_id, text, meta in zip(ids, documents, metadatas):
        meta = meta or {}
        key = str(meta.get("doc_id") or doc_id)
        out[key] = Document(id=key, page_content=text or "", metadata=meta)
    return out


def _write_manifest(payload: dict) -> None:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.MANIFEST_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(config.MANIFEST_FILE)


def build_index(corpus: CorpusResult, *, batch_size: int = 32) -> dict:
    """全量重建：删集合 → 重开 → 分批写入 → 写 manifest。

    第一版不做增量：项目文档不到 1MB，全量重建比维护「按文件 diff + 删除旧 chunk」
    的复杂度低得多；等文档量上来再按 manifest 的 `sha1` 做增量。
    """
    if not corpus.documents:
        raise RuntimeError("没有可索引的文档：检查 corpus 扫描规则")

    started = time.perf_counter()
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)

    try:
        get_store().delete_collection()
    except Exception:
        # 首次建索引时集合还不存在；正常情况，忽略。
        pass

    store = get_store()
    for start in range(0, len(corpus.documents), batch_size):
        batch = corpus.documents[start : start + batch_size]
        store.add_documents(batch)

    vectors = store._collection.count()  # noqa: SLF001 —— 取真实写入条数做校验
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    # 词面索引是从集合现读的内存结构，重建后必须让它重新读一遍。
    # 漏了这一句会变成「向量是新的、BM25 还是旧的」—— 不报错，只是查不到新文档。
    from . import lexical

    lexical.invalidate()
    embedding = config.embedding_info()
    payload = {
        "version": 2,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(config.ROOT),
        "index_dir": str(config.INDEX_DIR),
        "collection": config.collection_name(),
        "embedding": embedding,
        "chunker_version": config.CHUNKER_VERSION,
        "chunking": {
            "target_chars": config.TARGET_CHARS,
            "max_chars": config.MAX_CHARS,
            "max_tokens": config.MAX_TOKENS,
        },
        "files": corpus.files,
        "counts": {
            "files": len(corpus.files),
            "documents": len(corpus.documents),
            "vectors": int(vectors),
        },
        "skipped": corpus.skipped,
        "elapsed_ms": elapsed_ms,
    }
    _write_manifest(payload)
    return payload


def read_manifest() -> dict | None:
    if not config.MANIFEST_FILE.is_file():
        return None
    try:
        return json.loads(config.MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def check_stale(
    corpus: CorpusResult | None = None,
    manifest: dict | None = None,
) -> dict:
    """对比当前文件与 manifest，判断索引是否过期。

    只扫文件 sha1，不加载 embedding；`knowledge-index --check` 和
    `knowledge_stats` 共用这一份逻辑。
    """
    from .corpus import load_corpus

    manifest = manifest if manifest is not None else read_manifest()
    corpus = corpus or load_corpus()
    current = corpus.files

    if not manifest:
        return {
            "stale": True,
            "reasons": ["manifest-missing"],
            "built_at": None,
            "collection": None,
            "current_collection": config.collection_name(),
            "changed_files": [],
            "new_files": sorted(current),
            "missing_files": [],
            "checked_files": len(current),
        }

    old_files = manifest.get("files") or {}
    changed = sorted(
        rel
        for rel in current
        if rel in old_files and current[rel].get("sha1") != old_files[rel].get("sha1")
    )
    new = sorted(rel for rel in current if rel not in old_files)
    missing = sorted(rel for rel in old_files if rel not in current)

    reasons: list[str] = []
    if manifest.get("collection") != config.collection_name():
        reasons.append("collection-changed")
    if manifest.get("chunker_version") != config.CHUNKER_VERSION:
        reasons.append("chunker-version-changed")
    if manifest.get("embedding") != config.embedding_info():
        reasons.append("embedding-changed")
    if changed:
        reasons.append("files-changed")
    if new:
        reasons.append("files-added")
    if missing:
        reasons.append("files-removed")

    return {
        "stale": bool(reasons),
        "reasons": reasons,
        "built_at": manifest.get("built_at"),
        "collection": manifest.get("collection"),
        "current_collection": config.collection_name(),
        "changed_files": changed,
        "new_files": new,
        "missing_files": missing,
        "checked_files": len(current),
    }


def ensure_ready() -> dict:
    """search/read 前的就绪检查；失败时抛出可直接展示的中文错误。"""
    if not config.MANIFEST_FILE.is_file():
        raise KnowledgeIndexError(
            "知识库索引不存在。先运行：bash scripts/dev.sh knowledge-index"
        )
    manifest = read_manifest()
    if not manifest:
        raise KnowledgeIndexError(
            "知识库 manifest 无法读取。重新运行：bash scripts/dev.sh knowledge-index"
        )
    if manifest.get("collection") != config.collection_name():
        raise KnowledgeIndexError(
            "知识库索引配置已变化（collection 不一致）。"
            "重新运行：bash scripts/dev.sh knowledge-index"
        )
    if manifest.get("chunker_version") != config.CHUNKER_VERSION:
        raise KnowledgeIndexError(
            "知识库索引版本过旧（chunker_version 不一致）。"
            "重新运行：bash scripts/dev.sh knowledge-index"
        )
    count = raw_collection_count()
    if count <= 0:
        raise KnowledgeIndexError(
            "知识库集合为空。重新运行：bash scripts/dev.sh knowledge-index"
        )
    return manifest


def collection_count() -> int:
    """真实集合条数；不加载 embedding。"""
    return raw_collection_count()


def stats(*, detail: bool = False, live: bool = False) -> dict:
    """索引摘要（默认不返回完整 manifest，避免 Agent 上下文被文件清单淹没）。"""
    manifest = read_manifest()
    stale = check_stale(manifest=manifest)
    result = {
        "root": str(config.ROOT),
        "index_dir": str(config.INDEX_DIR),
        "collection": config.collection_name(),
        "embedding": config.embedding_info(),
        "chunker_version": config.CHUNKER_VERSION,
        "built_at": manifest.get("built_at") if manifest else None,
        "counts": manifest.get("counts") if manifest else None,
        "stale": stale["stale"],
        "stale_reasons": stale["reasons"],
        "changed_files": stale["changed_files"][:20],
        "new_files": stale["new_files"][:20],
        "missing_files": stale["missing_files"][:20],
        "changed_count": len(stale["changed_files"]),
        "new_count": len(stale["new_files"]),
        "missing_count": len(stale["missing_files"]),
        "skipped": len(manifest.get("skipped") or []) if manifest else 0,
    }
    if live:
        result["vectors"] = raw_collection_count()
    if detail:
        result["manifest"] = manifest
    return result
