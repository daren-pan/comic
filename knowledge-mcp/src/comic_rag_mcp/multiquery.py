"""多查询检索：原句 + 改写变体各跑一遍，合并候选后再排序。

## 它补的是什么

单次检索的候选池只有 20 条，正确答案如果不在池子里，后面做任何事都救不回来
（实测「收藏漫画有更新时如何提醒」：正确答案排第 9，融合后直接掉出前 20）。

改写能把它带进池子（含「通知」的说法让字面路命中「收藏更新通知」），
但**合成一个榜单时仍会被泛词段落压住** —— 因为融合只看名次。
所以这里的顺序是：**先扩池，再交给重排读内容**。

## 合并方式

每个变体各自跑一遍完整检索，得到一份**已排序的 doc_id 列表**；再用
`_fuse_ranked` 做跨变体的 RRF（原句权重 1.0、变体 0.7）。
不用"把所有通道的候选倒进一个大池子"：那样"每个变体都出现"的泛文档会被反复计分。

## 与重排的关系

`rerank` 开关打开时，合并后的候选（默认前 20）交给交叉编码器重新打分。
实测 20 条候选在 CPU 上约 **12~17 秒**，所以重排默认关闭。
"""
from __future__ import annotations

import time

from . import config, query_rewrite, query_type, rerank
from .retriever import _fuse_ranked, search


def search_multi(
    query: str,
    *,
    top_k: int = config.TOP_K,
    kind: str | None = None,
    module: str | None = None,
    include_historical: bool = False,
    mode: str | None = None,
    rerank_override: bool | None = None,
) -> dict:
    """原句 + N 个改写变体分别检索，合并后返回（**形状与 `retriever.search` 一致**）。

    `rerank_override=True` 强制对合并池重排（口语型查询的深度路径用）。
    """
    started = time.perf_counter()
    variants = query_rewrite.rewrite(query, force=True)
    queries = [query, *variants]
    use_rerank = rerank.enabled() if rerank_override is None else rerank_override

    hits_by_id: dict[str, dict] = {}
    ranked: list[tuple[str, list[str]]] = []
    weights: list[float] = []
    for index, variant in enumerate(queries):
        result = search(
            variant,
            top_k=config.REWRITE_CANDIDATES,
            kind=kind,
            module=module,
            include_historical=include_historical,
            mode=mode,
            rewrite=False,  # ⚠️ 必须显式关掉，否则 search → search_multi 无限递归
        )
        doc_ids = [hit["doc_id"] for hit in result["hits"]]
        for hit in result["hits"]:
            hits_by_id.setdefault(hit["doc_id"], hit)
        ranked.append((f"variant{index}", doc_ids))
        weights.append(1.0 if index == 0 else config.REWRITE_WEIGHT)

    if not ranked:
        return search(query, top_k=top_k, kind=kind, module=module, mode=mode)

    docs = {doc_id: None for doc_id in hits_by_id}
    merged = _fuse_ranked(ranked, docs, weights=weights)

    # 重排（可选）：**对整个合并池**重新打分。
    # ⚠️ 不能只重排 RRF 前 N（默认 10）：目标文档常常排在 15 名开外，
    # 截断等于没救 —— 实测截到 10 时「收藏更新提醒」仍排在错误段落后面。
    if use_rerank and merged:
        from langchain_core.documents import Document

        head = merged[: config.REWRITE_CANDIDATES]
        payload = [
            Document(page_content=hits_by_id[doc_id]["body"] or hits_by_id[doc_id]["snippet"],
                     metadata={"doc_id": doc_id})
            for doc_id, *_ in head
            if doc_id in hits_by_id
        ]
        compressor = rerank.get_compressor()
        scores = compressor.model.score([(query, d.page_content) for d in payload])
        scored = sorted(
            ((doc.metadata["doc_id"], float(score)) for doc, score in zip(payload, scores)),
            key=lambda item: -item[1],
        )
        seen = {doc_id for doc_id, _ in scored}
        merged = [(doc_id, score, None, ["rerank"]) for doc_id, score in scored] + [
            item for item in merged if item[0] not in seen
        ]

    hits: list[dict] = []
    for doc_id, score, rrf, sources in merged:
        base = hits_by_id.get(doc_id)
        if base is None:
            continue
        hit = dict(base)
        hit["score"] = round(float(score), 4)
        hit["rrf"] = None if rrf is None else round(float(rrf), 6)
        hit["sources"] = sorted({src for src in sources if not src.startswith("variant")}) or ["vector"]
        hits.append(hit)
        if len(hits) >= top_k:
            break

    return {
        "query": query,
        "mode": mode or "hybrid",
        "route": "deep",
        "query_type": query_type.label(query_type.classify(query)),
        "variants": variants,
        "hits": hits,
        "count": len(hits),
        "backend": config.embedding_info()["backend"],
        "collection": config.collection_name(),
        "candidates": {"merged": len(hits_by_id)},
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
