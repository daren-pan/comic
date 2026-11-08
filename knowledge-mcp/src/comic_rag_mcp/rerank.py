"""重排（rerank）：用**中文交叉编码器**给候选重新打分。

## 它补的是什么

第一轮检索（余弦 / BM25 / RRF）都是**粗排**：只比较"向量距离"或"词频"，
从没把「问题」和「文档」放在一起读过。于是会出现：

- 两路各自的第一名分数完全相同（RRF 无法裁决）；
- 文档里"提到过"某个词（比如笔记里举例引用问题原句）就排到真答案前面。

重排把 `(问题, 文档)` **拼成一对**喂给交叉编码器，输出一个相关性分 ——
它读得到上下文，所以能区分"回答了"和"只是提到了"。

## 用哪个组件

标准实现：`langchain_classic` 的 `CrossEncoderReranker` +
`sentence-transformers` 的 `CrossEncoder`（模型 `BAAI/bge-reranker-v2-m3`，多语言，中文可用）。

⚠️ 没走 `FlashrankRerank`：它唯一支持中文的 `ms-marco-MultiBERT-L-12` 是英文 MS MARCO
训练的，实测对中文真实命中**打分饱和**（全是 0.999x），接上等于不排。

## 为什么默认关闭

模型 2.1 GB、CPU 上重排 10 条约 1 秒（检索本身才 50 ms）。默认关，显式开：

```
COMIC_RAG_RERANK=1
```
"""
from __future__ import annotations

import logging
import os
import threading

from . import config

_log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_COMPRESSOR = None


def enabled() -> bool:
    """重排是否开启。运行期读环境变量，方便 A/B（不用重启进程改 config）。"""
    return config.RERANK_ENABLED or os.environ.get("COMIC_RAG_RERANK", "").strip() in {
        "1",
        "true",
        "on",
    }


def get_compressor():
    """懒加载并缓存 `CrossEncoderReranker`（模型加载约 5 秒，只做一次）。"""
    global _COMPRESSOR
    if _COMPRESSOR is not None:
        return _COMPRESSOR

    with _LOCK:
        if _COMPRESSOR is not None:
            return _COMPRESSOR
        from langchain_classic.retrievers.document_compressors import (
            CrossEncoderReranker,
        )
        # ⚠️ 必须用 LangChain 自己的 `BaseCrossEncoder` 包装，
        # 直接传 sentence-transformers 的 CrossEncoder 会被 pydantic 校验拒掉。
        from langchain_community.cross_encoders import HuggingFaceCrossEncoder

        model_path = str(config.RERANK_MODEL)
        if not os.path.isdir(model_path):
            raise FileNotFoundError(f"重排模型不存在：{model_path}")
        _log.info("加载重排模型：%s", model_path)
        encoder = HuggingFaceCrossEncoder(
            model_name=model_path,
            model_kwargs={"max_length": config.RERANK_MAX_LENGTH},
        )
        _COMPRESSOR = CrossEncoderReranker(model=encoder, top_n=config.RERANK_CANDIDATES)
        return _COMPRESSOR


def rerank(query: str, documents: list[dict], docs_by_id: dict, top_n: int) -> list[dict]:
    """把命中按重排分重排，返回新列表（元素是 `_hit` 用的 dict）。

    `documents` 是 `search()` 里排好序的 `(doc_id, score, rrf, sources)` 列表；
    这里只重排**前 N 条**，其余原样接在后面（它们本来就排在后面，重排也不会进 top_k）。
    """
    from langchain_core.documents import Document

    compressor = get_compressor()
    head = documents[: config.RERANK_CANDIDATES]
    tail = documents[config.RERANK_CANDIDATES :]

    pairs = []
    index_by_offset = {}
    for offset, item in enumerate(head):
        doc_id = item[0]
        doc = docs_by_id.get(doc_id)
        if doc is None:
            continue
        index_by_offset[offset] = doc_id
        pairs.append(Document(page_content=doc.page_content, metadata={"doc_id": doc_id}))

    if not pairs:
        return documents

    # ⚠️ 不用 `compress_documents`：它只返回排好序的 Document，**把分数丢了**。
    # 这里直接调它内部的同一个打分器，自己留分数（排序逻辑保持一致）。
    compressor = get_compressor()
    scores = compressor.model.score([(query, doc.page_content) for doc in pairs])
    by_id = {item[0]: item for item in head}
    ranked = sorted(
        ((doc.metadata["doc_id"], float(score)) for doc, score in zip(pairs, scores)),
        key=lambda pair: -pair[1],
    )

    out: list[dict] = []
    for doc_id, score in ranked:
        item = by_id.get(doc_id)
        if item is None:
            continue
        # 第一列（score）换成重排分，方便界面/CLI 直接看；rrf 仍保留原始融合分。
        out.append((doc_id, score, item[2], item[3]))
    # 没进重排结果（被截掉的）接到后面，避免凭空丢候选。
    seen = {item[0] for item in out}
    out.extend(item for item in head if item[0] not in seen)
    out.extend(tail)
    return out
