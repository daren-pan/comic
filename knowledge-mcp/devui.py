"""知识库调试界面（**只在本地用**）。

为什么单独做一个：CLI 的输出是给眼睛扫的表格，调参时想反复改问题、改模式、看分数构成，
命令行很别扭。这里起一个小页面，直接调同一套 `retriever` / `eval`，不复制任何检索逻辑。

    bash scripts/kb-ui.sh          # 或见下方的 uvicorn 命令
    浏览器打开 http://127.0.0.1:8899

三个页签：
  搜索   —— 单条查询，看每条命中的分数构成 / 来源 / 命中词，可展开回读全文
  对比   —— 同一个问题跑 vector / lexical / hybrid，并排看差别
  评测   —— 跑 20 条黄金题，看 Recall / MRR / nDCG / Top-1 与逐题明细

⚠️ 安全：只绑定 127.0.0.1，无鉴权。**不要改成 0.0.0.0**，也不要对外暴露。
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

# 允许直接 `python knowledge-mcp/devui.py` 跑；uvicorn 方式则由调用方设 PYTHONPATH。
_ROOT = Path(__file__).resolve().parent
for _rel in ("src", "../chat-service/src", "../comic-core/src"):
    _p = str((_ROOT / _rel).resolve())
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from comic_rag_mcp import config, lexical, tokenizer  # noqa: E402
from comic_rag_mcp.metrics import ndcg_at_k, rank_of_first_hit, summarize  # noqa: E402
from comic_rag_mcp.retriever import read, search, stats  # noqa: E402

# Chroma 的 Rust SQLite 直接读系统临时目录；必须先修环境再碰检索。
from comic_chat.runtime_env import prepare as _prepare_runtime  # noqa: E402

_prepare_runtime()

#: 重建索引是重活（约 40 秒），用非阻塞锁挡住并发触发。
_BUILD_LOCK = threading.Lock()

app = FastAPI(title="知识库调试 API", docs_url="/docs", redoc_url=None)


@app.on_event("startup")
def _warm_reranker() -> None:
    """后台预热：重排模型 + 向量模型 + BM25 索引。

    不预热的话，进程启动后**第一个**问题要付三笔固定开销：
    重排模型加载 ~25 秒、向量模型加载 ~2 秒、BM25 索引重建 ~1.4 秒。
    预热后实测：首问 6.8 秒 → 后续 3.3 秒。
    """
    from comic_rag_mcp import config, rerank
    from comic_rag_mcp.retriever import search

    def _warm() -> None:
        try:
            search("预热", top_k=1, mode="hybrid", rewrite=False)
        except Exception:  # noqa: BLE001 —— 预热失败不影响正常服务
            pass
        if config.AUTO_ROUTE and config.DEEP_RERANK:
            rerank.warm_up()

    threading.Thread(target=_warm, name="kb-warmup", daemon=True).start()

# 界面跑在 Vite（:5175）且通过 `/api` 代理转发；直连时也放行这两个来源。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5175",
        "http://localhost:5175",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchBody(BaseModel):
    query: str
    mode: str = "hybrid"
    top_k: int = 5
    kind: str | None = None
    module: str | None = None
    # 融合参数（可选）：不传就用配置默认值，方便页面上现场 A/B。
    rrf_k: int | None = None
    rrf_semantic_weight: float | None = None
    rrf_lexical_weight: float | None = None

    def fusion_args(self) -> dict:
        weights = None
        if self.rrf_semantic_weight is not None or self.rrf_lexical_weight is not None:
            weights = [
                float(self.rrf_semantic_weight if self.rrf_semantic_weight is not None else 0.75),
                float(self.rrf_lexical_weight if self.rrf_lexical_weight is not None else 0.25),
            ]
        return {
            "rrf_k": None if self.rrf_k is None else int(self.rrf_k),
            "rrf_weights": weights,
        }


class ReadBody(BaseModel):
    doc_id: str


@app.get("/api/status")
def api_status() -> dict:
    """顶部状态条：后端、分词、索引条数、是否过期。"""
    corpus_size = None
    stale = None
    try:
        from comic_rag_mcp.corpus import load_corpus

        corpus_size = len(load_corpus(config.ROOT).documents)
    except Exception as exc:  # noqa: BLE001 —— 调试页要能显示错误而不是 500
        corpus_size = f"读取失败：{exc}"
    try:
        payload = stats()
        stale = payload.get("stale")
        manifest = payload.get("counts") or {}
    except Exception:  # noqa: BLE001
        manifest = {}
    lex = {}
    try:
        lex = lexical.stats()
    except Exception:  # noqa: BLE001
        pass
    return {
        "embedding": config.embedding_info(),
        "tokenizer": tokenizer.describe(),
        "collection": config.collection_name(),
        "chunk_version": config.CHUNKER_VERSION,
        "corpus_chunks": corpus_size,
        "indexed": manifest,
        "stale": stale,
        "lexical": lex,
        "index_dir": str(config.INDEX_DIR),
    }


@app.post("/api/search")
def api_search(body: SearchBody) -> dict:
    return search(
        body.query,
        top_k=max(1, min(body.top_k, 20)),
        kind=body.kind or None,
        module=body.module or None,
        mode=body.mode,
        **body.fusion_args(),
    )


@app.post("/api/compare")
def api_compare(body: SearchBody) -> dict:
    """同一个问题跑三种模式，供并排对比。"""
    out = {}
    for mode in ("vector", "lexical", "hybrid"):
        out[mode] = search(
            body.query,
            top_k=max(1, min(body.top_k, 20)),
            kind=body.kind or None,
            module=body.module or None,
            mode=mode,
            **body.fusion_args(),
        )
    return out


@app.post("/api/read")
def api_read(body: ReadBody) -> dict:
    return read(body.doc_id)


@app.post("/api/index")
def api_index() -> dict:
    """全量重建索引（页面上的「重建索引」按钮）。

    约 40 秒。用非阻塞锁挡住并发重建；重建期间来的检索请求可能短暂报错 ——
    本地调试工具，能接受。重建完 `lexical.invalidate()` 让词面索引按新语料重建，
    向量句柄由 `get_store()` 每次新建，不用清缓存。
    """
    from comic_rag_mcp import lexical
    from comic_rag_mcp.corpus import load_corpus
    from comic_rag_mcp.indexer import build_index

    if not _BUILD_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "已有重建任务在跑，请等它结束"}
    try:
        corpus = load_corpus(config.ROOT)
        payload = build_index(corpus)
        lexical.invalidate()
        return {
            "ok": True,
            "files": len(corpus.files),
            "chunks": len(corpus.documents),
            "collection": payload.get("collection"),
            "counts": payload.get("counts"),
            "elapsed_ms": payload.get("elapsed_ms"),
        }
    except Exception as exc:  # noqa: BLE001 —— 错误要回给页面，不能 500 掉
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _BUILD_LOCK.release()


@app.post("/api/section")
def api_section(body: ReadBody) -> dict:
    """按**检索单元**（chunk）回读：返回整节原文 + 每一块在里面的字符区间。

    为什么要返回偏移：切分器只给"整节"记了行号（`start_line` 是 section 的），
    每块没有独立行号。这里用块正文在整节里的**顺序查找**定位，前端才能把原文
    切成块渲染（命中块标红），同时保证"块拼起来 = 原文"这件事看得见。

    对没有行号的源（Word / Excel / OpenAPI，`read_mode=chunk`）退化成单块。
    """
    from comic_rag_mcp.indexer import all_documents, documents_by_ids

    doc = documents_by_ids([body.doc_id]).get(body.doc_id)
    if doc is None:
        return {"ok": False, "error": f"找不到 chunk：{body.doc_id}"}

    meta = doc.metadata or {}
    full = read(body.doc_id)
    heading_path = str(meta.get("heading_path", ""))
    section_text = str(full.get("content") or "")

    # 同一小节的所有块（doc_id 末尾是块序号）
    siblings = []
    for doc_id, page in all_documents():
        if doc_id.rsplit("-", 1)[0] == body.doc_id.rsplit("-", 1)[0]:
            prefix = f"{heading_path}\n"
            text = page[len(prefix) :] if page.startswith(prefix) else page
            try:
                index = int(doc_id.rsplit("-", 1)[1])
            except (ValueError, IndexError):
                index = 0
            siblings.append({"doc_id": doc_id, "index": index, "text": text})
    siblings.sort(key=lambda item: item["index"])

    # 顺序定位：容忍 _hard_split 的 50 字重叠（下一块可能从上一个游标之前开始）
    blocks = []
    cursor = 0
    overlap = int(config.OVERLAP_CHARS) if hasattr(config, "OVERLAP_CHARS") else 0
    for item in siblings:
        text = item["text"]
        pos = section_text.find(text, max(0, cursor - overlap)) if text else -1
        if pos < 0:
            pos = section_text.find(text) if text else -1
        if pos < 0:
            blocks.append(
                {
                    "index": item["index"],
                    "doc_id": item["doc_id"],
                    "start": None,
                    "end": None,
                    "chars": len(text),
                    "matched": item["doc_id"] == body.doc_id,
                }
            )
            continue
        blocks.append(
            {
                "index": item["index"],
                "doc_id": item["doc_id"],
                "start": pos,
                "end": pos + len(text),
                "chars": len(text),
                "matched": item["doc_id"] == body.doc_id,
            }
        )
        cursor = pos + len(text)

    covered = sum(b["chars"] for b in blocks if b["start"] is not None)
    return {
        "ok": True,
        "doc_id": body.doc_id,
        "path": meta.get("path", ""),
        "heading_path": heading_path,
        "read_mode": meta.get("read_mode", "lines"),
        "start_line": full.get("start_line"),
        "end_line": full.get("end_line"),
        "text": section_text,
        "blocks": blocks,
        "stats": {
            "blocks": len(blocks),
            "total_chars": len(section_text),
            "covered_chars": covered,
            # >0 说明有块之间重叠（`_hard_split` 的 50 字重叠），=0 说明无缝拼接
            "overlap_chars": covered - len(section_text),
        },
    }


@app.get("/api/eval")
def api_eval(mode: str = "hybrid", top_k: int = 5) -> dict:
    from comic_rag_mcp.eval_cases import CASES

    rows = []
    for case in CASES:
        result = search(case["query"], top_k=top_k, mode=mode)
        hits = result.get("hits") or []
        paths = [hit["path"] for hit in hits]
        rank = rank_of_first_hit(paths, case["expect"], top_k)
        rows.append(
            {
                "query": case["query"],
                "expect": list(case["expect"]),
                "paths": paths,
                "rank": rank,
                "rr": (1.0 / rank) if rank else 0.0,
                "ndcg": ndcg_at_k(paths, case["expect"], top_k),
                "hits": [
                    {
                        "path": hit["path"],
                        "heading": hit["heading"],
                        "score": hit["score"],
                        "vector_score": hit["vector_score"],
                        "lexical_score": hit.get("lexical_score"),
                        "sources": hit.get("sources") or [],
                    }
                    for hit in hits
                ],
            }
        )
    return {"mode": mode, "k": top_k, "summary": summarize(rows, top_k), "cases": rows}


@app.get("/")
def index() -> dict:
    """后端只提供 API；界面在 `devui-web/`（Vue + Vite），由 vite 代理 `/api` 过来。"""
    return {
        "service": "knowledge-mcp devui",
        "docs": "/docs",
        "ui": "cd knowledge-mcp/devui-web && npm run dev  → http://127.0.0.1:5175",
    }





def main() -> None:
    import os

    import uvicorn

    port = int(os.environ.get("KB_UI_PORT", "8899"))
    print(f"[kb-ui] 打开 http://127.0.0.1:{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
