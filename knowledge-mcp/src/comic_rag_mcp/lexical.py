"""BM25 字面召回：**直接调用 LangChain 的 `BM25Retriever`**，这里只做适配。

## 它补的是什么

语义检索回答「**哪条意思最像**」，对**专有名词**很弱：用户问 `X-Service-Token`，
语义会把「鉴权 / JWT」那篇当成最像的，而真正写着这个词的那条排在后面。
BM25 不看语义，只数**词**：你问的词在这段里出现几次、这个词在库里有多稀有。

| 路 | 擅长 | 不擅长 |
|---|---|---|
| 语义 | 口语、错别字（「图骗打不开」） | 型号、报错码、函数名、专有名词 |
| 字面 | 字面精确命中 | 换一种说法就抓不到 |

## 为什么用库而不是自己写

公式三十行能写完，真正麻烦的是**边界情况**：`n(t) > N/2` 时经典 IDF 会变负数、
文档长度为 0、查询词不在词表、`k1/b` 取极值……这些 `BM25Retriever`（底层 `rank_bm25`）
都处理过了。**我们只负责它替代不了的两件事**：

1. **分词**：文档侧与查询侧都走 `tokenizer`（`preprocess_func=tokenizer.tokens`）；
2. **文档来源**：索引**从 Chroma 现读**，与向量库同源同生命周期。

## 三个必须记住的坑

1. **绝对分不能跨分词器比较**，所以这里**刻意不设绝对阈值**。
2. **索引与向量库必须同源**：`indexer.build_index()` 之后要调 `invalidate()`。
3. **文档侧和查询侧必须同一套分词**，否则词对不上，分数全错。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from . import config, tokenizer


@dataclass(frozen=True)
class LexicalHit:
    """一条词面命中。`matched` 留给调试：看这条是**被哪几个词**捞上来的。"""

    doc_id: str
    score: float
    matched: tuple[str, ...]


class BM25:
    """`BM25Retriever` 的薄适配层。

    LangChain 的检索器只返回 `Document`、不带分数；而界面要显示 BM25 分、
    融合也要能解释，所以这里补两件事：**把分数取出来**、**算出命中词**。
    打分本身完全由 `BM25Retriever.vectorizer`（`rank_bm25.BM25Okapi`）完成。
    """

    def __init__(self, retriever: BM25Retriever) -> None:
        self._retriever = retriever
        # doc_id → 在 retriever.docs 里的下标，用于把分数对回文档
        self._index = {
            str((doc.metadata or {}).get("doc_id", "")): pos
            for pos, doc in enumerate(retriever.docs)
        }
        self._token_sets = {
            str((doc.metadata or {}).get("doc_id", "")): set(tokenizer.tokens(doc.page_content))
            for doc in retriever.docs
        }

    # ---- 构造 ----
    @classmethod
    def from_texts(cls, docs: Iterable[tuple[str, str]], k: int | None = None) -> "BM25":
        """`[(doc_id, 正文)] → BM25`（正文用当前分词器切）。"""
        documents = [
            Document(page_content=text, metadata={"doc_id": doc_id})
            for doc_id, text in docs
            if text.strip()
        ]
        retriever = BM25Retriever.from_documents(
            documents,
            preprocess_func=tokenizer.tokens,
            bm25_params={"k1": config.LEXICAL_K1, "b": config.LEXICAL_B},
        )
        retriever.k = int(k or config.LEXICAL_TOP_K)
        return cls(retriever)

    # ---- 查询 ----
    def score_tokens(self, query_tokens) -> list[LexicalHit]:
        """按查询词表打分；返回**降序**结果（分数 0 的不返回）。"""
        terms = [t for t in dict.fromkeys(query_tokens) if t]
        if not terms or not self._retriever.docs:
            return []

        scores = self._retriever.vectorizer.get_scores(terms)
        hits: list[LexicalHit] = []
        for doc in self._retriever.docs:
            doc_id = str((doc.metadata or {}).get("doc_id", ""))
            pos = self._index.get(doc_id)
            if pos is None:
                continue
            value = float(scores[pos])
            if value <= 0:
                continue
            sets = self._token_sets.get(doc_id, set())
            hits.append(
                LexicalHit(
                    doc_id=doc_id,
                    score=round(value, 6),
                    matched=tuple(t for t in terms if t in sets),
                )
            )
        hits.sort(key=lambda h: (-h.score, h.doc_id))
        return hits

    def search(self, query: str, k: int | None = None) -> list[LexicalHit]:
        """文本查询 → 前 k 条（默认 `config.LEXICAL_TOP_K`）。

        `k` 小于索引默认值时临时调小 `retriever.k`（LangChain 检索器按它截断）。
        """
        limit = int(k) if k is not None else config.LEXICAL_TOP_K
        original = self._retriever.k
        try:
            self._retriever.k = limit
            documents = self._retriever.invoke(query)   # ← 直接调 LangChain 检索器
        finally:
            self._retriever.k = original

        by_id = {h.doc_id: h for h in self.score_tokens(tokenizer.tokens(query))}
        # ⚠️ 用 get 而不是下标：`BM25Retriever` 的 get_top_n 会"凑满 k 个"，
        # 查询词一个都不在词表里时照样返回 k 条 **0 分**文档 —— 下标取分会 KeyError。
        hits = [
            by_id.get(str((document.metadata or {}).get("doc_id", "")))
            for document in documents
        ]
        return [hit for hit in hits if hit is not None]

    def stats(self) -> dict:
        vectorizer = self._retriever.vectorizer
        return {
            "documents": len(self._retriever.docs),
            "terms": len(getattr(vectorizer, "idf", {}) or {}),
            # `avgdl` 是 BM25Okapi 的平均文档长度，`doctor` 会展示它；
            # 缺了它会抛 KeyError，被 doctor 当成"词面索引不可用"。
            "avgdl": round(float(getattr(vectorizer, "avgdl", 0.0)), 2),
            "k1": config.LEXICAL_K1,
            "b": config.LEXICAL_B,
            "tokenizer": tokenizer.backend(),
            "engine": "langchain_community.BM25Retriever",
        }


# ---------------------------------------------------------------------------
# 进程级单例：索引从向量库现读，避免「两份索引漂移」
# ---------------------------------------------------------------------------
_INDEX: BM25 | None = None


def invalidate() -> None:
    """丢弃缓存（`indexer.build_index()` 之后必须调）。"""
    global _INDEX
    _INDEX = None


def get_index(*, refresh: bool = False) -> BM25:
    """取（必要时建）BM25 索引。

    ⚠️ 数据来源是 **Chroma 里的 chunk**，与向量检索同一批文档。
    ⚠️ 读取走 `indexer.all_documents()`，**不构造 embedding**。
    """
    from . import indexer

    global _INDEX
    if _INDEX is None or refresh:
        _INDEX = BM25.from_texts(indexer.all_documents())
    return _INDEX


def search(query: str, k: int | None = None) -> list[dict]:
    """给 CLI / 调试用的检索入口。"""
    index = get_index()
    return [
        {"doc_id": h.doc_id, "score": h.score, "matched": list(h.matched)}
        for h in index.search(query, k)
    ]


def stats() -> dict:
    return get_index().stats()
