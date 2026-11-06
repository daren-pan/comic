"""`message` 表的独立增量索引器。

数据流（**MCP 不直连 MySQL**）：

```text
GET /api/internal/knowledge/messages  （服务令牌，按 id 升序分页）
  → message_indexer 拉取
  → 转成一条条 Document
  → project_kb_message_<指纹> Chroma 集合
  → MCP search_messages / read_message
```

为什么单独一个集合：

- message 是**动态数据**，会不断追加；不能和项目文档的全量重建绑在一起；
- 消息行是**追加式**的（没有 updated_at），增量游标就是 `id > last_id`；
- `message` 表可能被 `purge` 清理，所以定期 `--full` 做一次全量对账（定时后续再加）。

边界：本模块只 **GET** 内部接口；删除只删本地 Chroma 向量，绝不改/删 MySQL。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

from . import config

#: 与 api-service/core/security.py 的本地默认值保持一致；生产必须显式设 COMIC_JWT_SECRET。
_DEFAULT_JWT_SECRET = "comic-demo-secret-change-me"


class MessageIndexError(RuntimeError):
    """消息索引不可用；消息应直接展示给用户。"""


def _service_token() -> str:
    """生成进程间服务令牌（HMAC，复用 COMIC_JWT_SECRET）。"""
    from comic_core.notify import make_service_token

    secret = os.environ.get("COMIC_JWT_SECRET") or _DEFAULT_JWT_SECRET
    return make_service_token(secret)


def fetch_page(cursor: int, limit: int = 200) -> dict:
    """从内部只读接口拉一页 message；失败抛可读错误。"""
    params = urllib.parse.urlencode({"cursor": int(cursor), "limit": int(limit)})
    url = f"{config.MESSAGE_API_URL}?{params}"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "X-Service-Token": _service_token(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=config.MESSAGE_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        raise MessageIndexError(
            f"拉取 message 接口失败（{url}）：{type(exc).__name__}: {exc}。"
            "先确认 api 已启动（bash scripts/dev.sh up api）。"
        ) from exc
    try:
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise MessageIndexError(f"message 接口返回非 JSON：{raw[:200]}") from exc
    if not isinstance(payload, dict) or "items" not in payload:
        raise MessageIndexError(f"message 接口返回格式不对：{raw[:200]}")
    return payload


def item_to_document(item: dict) -> dict | None:
    """一条 message → 一个 upsert 文档；空消息返回 None。

    文本只放 title + body；定向用户 id、min_role 等放 metadata，不进入 page_content。
    """
    try:
        message_id = int(item.get("id"))
    except (TypeError, ValueError):
        return None
    title = str(item.get("title") or "").strip()
    body = str(item.get("body") or "").strip()
    if not title and not body:
        return None
    text = "\n\n".join(part for part in (title, body) if part)
    if len(text) > config.MESSAGE_MAX_CHARS:
        text = text[: config.MESSAGE_MAX_CHARS].rstrip() + "\n\n…（已截断）"

    created = str(item.get("createdAt") or "")
    metadata = {
        "doc_id": f"message:{message_id}",
        "source": "message",
        "message_id": message_id,
        "kind": str(item.get("kind") or "system"),
        "level": str(item.get("level") or "info"),
        "title": title[:255],
        "task_id": str(item.get("taskId") or ""),
        "source_name": str(item.get("source") or ""),
        "username": str(item.get("username") or ""),
        "min_role": str(item.get("minRole") or ""),
        "created_at": created,
        "targeted": 1 if item.get("toUserId") is not None else 0,
        "read_mode": "chunk",
    }
    return {
        "id": f"message:{message_id}",
        "text": text,
        "metadata": metadata,
    }


def _manifest_path():
    return config.MESSAGE_MANIFEST_FILE


def read_manifest() -> dict | None:
    path = _manifest_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_manifest(payload: dict) -> None:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path = _manifest_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _collection(*, fresh: bool = False):
    import chromadb

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(config.INDEX_DIR))
    name = config.message_collection_name()
    if fresh:
        try:
            client.delete_collection(name)
        except Exception:
            pass
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def _embed(texts: list[str]) -> list[list[float]]:
    from comic_chat.rag.embeddings import get_embeddings

    return get_embeddings().embed_documents(texts)


def index(*, full: bool = False, limit: int = 200, max_pages: int | None = None) -> dict:
    """增量或全量构建 message 索引。

    - 默认增量：从 manifest.last_id 继续，`id > last_id`；
    - `full=True`：删本地集合后从头重建（用于清理 purge 留下的旧向量）；
    - 只 GET 接口，不修改 MySQL。
    """
    started = time.perf_counter()
    manifest = None if full else read_manifest()
    if manifest and manifest.get("collection") != config.message_collection_name():
        raise MessageIndexError(
            "message 索引集合配置已变化（embedding / 模板版本不一致）。"
            "重新运行：bash scripts/dev.sh message-index --full"
        )
    if manifest and manifest.get("schema_version") != 1:
        raise MessageIndexError(
            "message 接口 schema_version 变化，需要先升级索引器。"
        )

    last_id = 0 if full else int((manifest or {}).get("last_id") or 0)
    collection = _collection(fresh=full)
    pages = 0
    indexed = 0
    fetched = 0

    while True:
        page = fetch_page(last_id, limit=limit)
        items = page.get("items") or []
        if not items:
            break
        docs = [doc for item in items if (doc := item_to_document(item))]
        if docs:
            collection.upsert(
                ids=[doc["id"] for doc in docs],
                embeddings=_embed([doc["text"] for doc in docs]),
                documents=[doc["text"] for doc in docs],
                metadatas=[doc["metadata"] for doc in docs],
            )
            indexed += len(docs)
        fetched += len(items)
        last_id = max(int(item["id"]) for item in items)
        pages += 1
        if not page.get("hasMore"):
            break
        if max_pages is not None and pages >= max_pages:
            break

    count = int(collection.count())
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    payload = {
        "version": 1,
        "source": "message",
        "schema_version": 1,
        "collection": config.message_collection_name(),
        "embedding": config.embedding_info(),
        "message_index_version": config.MESSAGE_INDEX_VERSION,
        "built_at": (manifest or {}).get("built_at") or datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "last_id": last_id,
        "count": count,
        "fetched": fetched,
        "indexed": indexed,
        "pages": pages,
        "mode": "full" if full else "incremental",
        "elapsed_ms": elapsed_ms,
    }
    _write_manifest(payload)
    return payload


def stats() -> dict:
    """消息索引摘要（不加载 embedding）。"""
    manifest = read_manifest()
    live = 0
    try:
        live = int(_collection().count())
    except Exception:
        pass
    return {
        "source": "message",
        "collection": config.message_collection_name(),
        "manifest": manifest,
        "live_count": live,
        "ready": bool(manifest) and live > 0,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(prog="comic-message-indexer")
    parser.add_argument("--full", action="store_true", help="删本地集合后全量重建")
    parser.add_argument("--limit", type=int, default=200, help="每页条数，最大 200")
    parser.add_argument("--max-pages", type=int, default=None, help="调试用：最多拉几页")
    parser.add_argument("--stats", action="store_true", help="只看索引状态")
    args = parser.parse_args(argv)

    from comic_chat.runtime_env import prepare

    prepare()
    try:
        if args.stats:
            print(json.dumps(stats(), ensure_ascii=False, indent=2))
            return 0
        payload = index(full=args.full, limit=args.limit, max_pages=args.max_pages)
    except MessageIndexError as exc:
        print(f"[message-index] ❌ {exc}", file=sys.stderr)
        return 1
    print(
        f"[message-index] ✅ {payload['mode']}：last_id={payload['last_id']} "
        f"count={payload['count']} indexed={payload['indexed']} "
        f"→ {payload['collection']}（{payload['elapsed_ms']}ms）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
