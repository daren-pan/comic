"""Chroma 索引构建、就绪检查与新鲜度检测。

与 chat-service 的 `rag_lab` 分开：本模块只写 `project_rag` / `project_kb_*`。
集合名带 embedding + 切分/读取契约版本，换模型或换读法会自动落到新集合。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.indexing import InMemoryRecordManager

from . import config
from .corpus import CorpusResult

_log = logging.getLogger(__name__)


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

    ⚠️ 必须按 **metadata.doc_id** 查，不能用 `get(ids=...)`：集合主键现在是
    LangChain `index()` 写入的内容哈希，和我们的 doc_id 是两套东西。
    """
    if not doc_ids:
        return {}
    collection = raw_collection()

    from langchain_core.documents import Document

    out: dict[str, Document] = {}
    batch_size = 100
    unique = list(dict.fromkeys(doc_ids))
    for start in range(0, len(unique), batch_size):
        batch = unique[start : start + batch_size]
        result = collection.get(
            where={"doc_id": {"$in": batch}}, include=["documents", "metadatas"]
        )
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or [{} for _ in ids]
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


class JsonRecordManager(InMemoryRecordManager):
    """LangChain 的内存记录管理器 + **落盘**。

    `index()` 靠它判断"哪些文件变了"：键是 `(源文件, 内容哈希)`，值是更新时间。
    内存版进程一退就丢，下次会全量重算 —— 所以这里在每次写入后落一份 JSON。
    """

    def __init__(self, namespace: str, path: Path) -> None:
        super().__init__(namespace=namespace)
        self._path = Path(path)
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if payload.get("namespace") == self.namespace:
            self.records = dict(payload.get("records") or {})

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {"namespace": self.namespace, "records": self.records},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            # 落盘失败不影响本次索引，只是下次会退化成全量。
            pass

    def update(self, keys, *, group_ids=None, time_at_least=None) -> None:  # noqa: ANN001
        super().update(keys, group_ids=group_ids, time_at_least=time_at_least)
        self._save()

    def delete_keys(self, keys) -> None:  # noqa: ANN001
        super().delete_keys(keys)
        self._save()


def _can_incremental() -> bool:
    """集合存在、非空，**记录文件也在**，且 manifest 的 embedding / 切分版本与当前一致。

    ⚠️ 必须要求记录文件存在：否则「集合有数据、记录为空」会被判定成"全是新文档"，
    于是把整库再插一遍 —— 结果是一堆重复块，而且不报错。
    """
    try:
        if raw_collection_count() <= 0:
            return False
        if not (config.INDEX_DIR / "record_manager.json").exists():
            return False
        manifest = json.loads(config.MANIFEST_FILE.read_text(encoding="utf-8"))
        return (
            manifest.get("embedding") == config.embedding_info()
            and manifest.get("chunker_version") == config.CHUNKER_VERSION
        )
    except (OSError, ValueError):
        return False


def build_index(
    corpus: CorpusResult, *, batch_size: int = 32, incremental: bool = True
) -> dict:
    """建索引：**能增量就增量**（LangChain `index()`），否则全量重建。

    增量会把 `(源文件, 内容哈希)` 记在 `record_manager.json` 里，只重算变过的文件，
    并删掉源文件里已经不存在的旧块。切分版本 / embedding 变了必须全量
    （块 id 与向量空间都变了），`_can_incremental()` 会挡住这种情况。
    """
    if not corpus.documents:
        raise RuntimeError("没有可索引的文档：检查 corpus 扫描规则")

    started = time.perf_counter()
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)

    from langchain_core.indexing import index as lc_index

    # ⚠️ 批次必须能**装下一个文件的全部块**。
    #
    # LangChain 的 `cleanup="incremental"` 是**每批处理完就清理一次**：它把该批次里出现的
    # 源文件（group_id）中"更新时间早于本轮开始"的记录全删掉。如果某文件有 125 块、
    # 批次只有 32，那么第 1 批处理完就把这个文件**还没轮到**的 93 块当成"过期"删了，
    # 后面几批再把它们重新加回来 —— 结果就是「什么都没改，却新增 421 / 删除 421」。
    # 实测：batch=32 一次 26 秒且反复churn；batch≥单文件最大块数后 1.5 秒、0 增删。
    per_file: dict[str, int] = {}
    for doc in corpus.documents:
        path = str((doc.metadata or {}).get("path") or "")
        per_file[path] = per_file.get(path, 0) + 1
    largest_file = max(per_file.values(), default=0)
    # 单批装下整个语料（上限 4096）—— 这样清理只在最后跑一次，文件跨批次的问题从根上消失。
    effective_batch = max(batch_size, largest_file, min(len(corpus.documents), 4096))

    can_incremental = bool(incremental and _can_incremental())
    record_file = config.INDEX_DIR / "record_manager.json"

    if not can_incremental:
        # 全量：集合与记录一起清掉，否则「旧记录 + 新集合」会让增量判断错乱。
        try:
            get_store().delete_collection()
        except Exception:
            # 首次建索引时集合还不存在；正常情况，忽略。
            pass
        try:
            record_file.unlink()
        except FileNotFoundError:
            pass

    manager = JsonRecordManager(config.collection_name(), record_file)
    store = get_store()
    try:
        result = lc_index(
            corpus.documents,
            manager,
            store,
            batch_size=effective_batch,
            # 全量用 "full"：把源里已不存在的旧块删干净；增量只处理变化的文件。
            cleanup="incremental" if can_incremental else "full",
            source_id_key="path",      # 以「文件」为增量单位
        )
        mode = "incremental" if can_incremental else "full"
        counts = {
            "added": result["num_added"],
            "updated": result["num_updated"],
            "deleted": result["num_deleted"],
            "skipped": result["num_skipped"],
        }
    except Exception as exc:  # noqa: BLE001 —— 标准索引失败必须能退回手写写入
        _log.warning("LangChain index() 失败（%s）：%s；退回逐批写入", type(exc).__name__, exc)
        try:
            store.delete_collection()
        except Exception:
            pass
        store = get_store()
        for start in range(0, len(corpus.documents), batch_size):
            store.add_documents(corpus.documents[start : start + batch_size])
        mode = "full"
        counts = {}

    vectors = raw_collection_count()
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
        "mode": mode,
        "changes": counts,
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
