"""MCP 工具定义（stdio）。

Agent 的典型调用顺序：

1. `search_knowledge(query)` → 拿到精简命中；
2. 需要全文时 `read_knowledge(doc_id)`；
3. 不确定索引是否新鲜时 `knowledge_stats()`。

只读：不提供 reindex 工具。重建索引走 CLI（`python -m comic_rag_mcp.cli index`），
避免 Agent 在对话中误触发一次几百个 chunk 的全量重建。

错误语义：预期错误统一抛 `ToolError`，让 MCP 客户端看到 `isError=true`；
不要把 `{"error": ...}` 当正常结果返回，否则模型会把错误文本当资料继续编。
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from . import message_retriever, retriever

mcp = FastMCP("comic-knowledge")


@mcp.tool()
def search_knowledge(
    query: str,
    top_k: int = 5,
    kind: str | None = None,
    module: str | None = None,
    include_historical: bool = False,
    mode: str | None = None,
) -> dict:
    """Search the comic project knowledge base.

    Use this before answering questions about the project's architecture,
    modules, deployment, auth, database schema, API endpoints, or coding
    conventions. Results are concise hits (path + heading + snippet + score);
    call `read_knowledge` with a `doc_id` when the full section is needed.

    Retrieval is hybrid by default: semantic vectors plus BM25 keyword matching,
    fused by reciprocal rank. Each hit reports `sources` (`vector` / `lexical` /
    both) so you can tell why it was returned.

    Args:
        query: Natural-language question or keywords.
        top_k: Number of hits, 1-10 (default 5).
        kind: Optional filter: root_doc, module_readme, module_notes,
            module_design, module_ops, module_config, module_eval,
            design_doc, deploy_doc, source_readme, schema, api,
            ext_md, ext_word, ext_excel (user documents).
        module: Optional filter: project, core, crawler, api, scheduler,
            chat, web, front, deploy, docs, scripts, tools, knowledge,
            external (user documents).
        include_historical: Include known stale/historical docs (default false).
        mode: Retrieval mode: `hybrid` (default), `vector`, or `lexical`.
            Use `vector` to fall back to pure semantic search.
    """
    try:
        return retriever.search(
            query,
            top_k=top_k,
            kind=kind,
            module=module,
            include_historical=include_historical,
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc


@mcp.tool()
def read_knowledge(doc_id: str) -> dict:
    """Read the full section for a hit returned by `search_knowledge`.

    Markdown and SQL results return the matched section itself (not just the
    child chunk, and not an empty parent heading). OpenAPI results return the
    endpoint chunk. Word and Excel documents (kind `ext_word` / `ext_excel`)
    return the matched chunk only — the source file is not plain text, so there
    is no line range to re-read. Content is capped at 6000 chars and marked
    `truncated`.
    """
    try:
        return retriever.read(doc_id)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc


@mcp.tool()
def search_messages(
    query: str,
    top_k: int = 5,
    level: str | None = None,
    kind: str | None = None,
) -> dict:
    """Search the indexed `message` table (platform notifications / task messages).

    Use this for questions about recent task results, failures, announcements,
    or notification history. Results are concise hits; call `read_message` for
    the full message.

    Args:
        query: Natural-language question or keywords.
        top_k: Number of hits, 1-10 (default 5).
        level: Optional filter: info / warn / error.
        kind: Optional filter: sync / inspect / heal / import / schedule / system...
    """
    try:
        return message_retriever.search(
            query, top_k=top_k, level=level, kind=kind
        )
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc


@mcp.tool()
def read_message(doc_id: str) -> dict:
    """Read one message by the `doc_id` returned from `search_messages`."""
    try:
        return message_retriever.read(doc_id)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc


@mcp.tool()
def message_stats() -> dict:
    """Return message index status: collection, last id, count, build time."""
    try:
        return message_retriever.stats()
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc


@mcp.tool()
def knowledge_stats(detail: bool = False) -> dict:
    """Return index status: collection, embedding, counts, build time, staleness.

    By default this is a summary; set `detail=True` only when the full manifest
    (per-file sha1/chunks) is really needed.
    """
    try:
        return retriever.stats(detail=detail)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc
