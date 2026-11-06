"""BM25 词面召回（阶段二 P2.1：**只建索引，尚未接入检索**）。

## 它补的是什么

向量检索回答「**哪条意思最像**」，对**专有名词**很弱：用户问 `X-Service-Token`，
向量会把「鉴权 / JWT」那篇当成最像的，而真正写着这个词的那条排在后面。
BM25 不看语义，只数**词**：你问的词在这段里出现几次、这个词在库里有多稀有。

两者是**能力互补**，不是精度高低：

| 路 | 擅长 | 不擅长 |
|---|---|---|
| 向量 | 口语、错别字（「图骗打不开」） | 型号、报错码、函数名、专有名词 |
| BM25 | 字面精确命中 | 换一种说法就抓不到 |

## 公式（Okapi BM25）

    score(D, Q) = Σ  IDF(t) · f(t,D)·(k1+1) / ( f(t,D) + k1·(1 − b + b·|D|/avgdl) )
                 t∈Q

    IDF(t) = ln( 1 + (N − n(t) + 0.5) / (n(t) + 0.5) )

- `f(t,D)` 词频：出现越多越相关，但会**饱和**（k1 管）；
- `|D| / avgdl`：这篇比平均长多少 → 长文吃亏（b 管，b=0 关闭长度归一）；
- `n(t)`：出现过该词的文档数 → 越稀有越值钱。

## 三个必须写进注释的坑

1. **绝对分不能跨分词器比较**。同一个 chunk，bigram 下 3.058、jieba 下 1.050 ——
   因为加数个数不同。所以这里**刻意不设绝对阈值**：BM25 的分数只在同一次查询、
   同一套分词里可比，拿固定门槛去卡只会误伤。
2. **索引与向量库必须同源同生命周期**。所以索引**从 Chroma 现读**（用户提向量库里的
   `page_content`），而不是单独存一份 —— 两份索引必然漂移，而且不报错。
   `indexer.build_index()` 重建后要调 `invalidate()`。
3. **文档侧和查询侧必须同一套分词**（都走 `tokenizer`），否则词对不上，分数全错。

## 本阶段不做

- 不接进 `retriever.search()`（P2.2 才接），所以现有检索行为**完全不变**；
- 不做 RRF 融合（P2.2）、不做增量更新（重建成本约几十毫秒）。
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from . import config, tokenizer


@dataclass(frozen=True)
class LexicalHit:
    """一条词面命中。`matched` 留给调试：看这条是**被哪几个词**捞上来的。"""

    doc_id: str
    score: float
    matched: tuple[str, ...]


class BM25:
    """内存版 BM25（纯 Python，零依赖）。

    **故意不引入 `rank_bm25`**：30 行能写完，而第三方库既不管分词、也不管文档来源，
    省下的只有一次乘法 —— 代价是多一个要跟版本的依赖。

    构造分两种：`from_texts()`（生产用，自己分词）和直接传 token 列表（单测用，
    好写手算值）。分词器换了不影响这里的公式，只影响喂进来的 token。
    """

    def __init__(
        self,
        tokenized: Mapping[str, Sequence[str]],
        *,
        k1: float | None = None,
        b: float | None = None,
    ) -> None:
        self.k1 = config.LEXICAL_K1 if k1 is None else k1
        self.b = config.LEXICAL_B if b is None else b

        self._tf: dict[str, Counter] = {}
        self._dl: dict[str, int] = {}
        df: Counter = Counter()
        for doc_id, tokens in tokenized.items():
            tf = Counter(tokens)
            self._tf[doc_id] = tf
            self._dl[doc_id] = len(tokens)
            df.update(tf.keys())          # 每篇只算一次，避免词频影响 df

        self.documents = len(self._tf)
        self.avgdl = (sum(self._dl.values()) / self.documents) if self.documents else 0.0
        self._df = df
        # IDF 用 BM25 常见的 log(1 + ...) 形式：恒为正，不会像经典公式那样对高频词出负值
        self._idf = {
            term: math.log(1 + (self.documents - n + 0.5) / (n + 0.5))
            for term, n in df.items()
        }

    # ---- 构造 ----
    @classmethod
    def from_texts(
        cls,
        docs: Iterable[tuple[str, str]],
        *,
        k1: float | None = None,
        b: float | None = None,
    ) -> "BM25":
        """`[(doc_id, 正文)] → BM25`（正文用当前分词器切）。"""
        return cls(
            {doc_id: tokenizer.tokens(text) for doc_id, text in docs},
            k1=k1,
            b=b,
        )

    # ---- 查询 ----
    def score_tokens(self, query_tokens: Sequence[str]) -> list[LexicalHit]:
        """按查询词表打分；返回**降序**结果（分数 0 的不返回）。"""
        terms = list(dict.fromkeys(t for t in query_tokens if t))
        if not terms or not self.documents:
            return []

        hits: list[LexicalHit] = []
        for doc_id, tf in self._tf.items():
            dl = self._dl[doc_id]
            # 长度归一因子：文档越长，同样的词频得分越低
            norm = 1 - self.b + self.b * dl / self.avgdl
            score = 0.0
            matched: list[str] = []
            for term in terms:
                f = tf.get(term)
                if not f:
                    continue
                matched.append(term)
                score += self._idf.get(term, 0.0) * f * (self.k1 + 1) / (
                    f + self.k1 * norm
                )
            if score > 0:
                hits.append(
                    LexicalHit(doc_id=doc_id, score=round(score, 6), matched=tuple(matched))
                )
        hits.sort(key=lambda h: (-h.score, h.doc_id))
        return hits

    def search(self, query: str, k: int | None = None) -> list[LexicalHit]:
        """文本查询 → 前 k 条（默认 `config.LEXICAL_TOP_K`）。"""
        limit = config.LEXICAL_TOP_K if k is None else int(k)
        return self.score_tokens(tokenizer.tokens(query))[: max(0, limit)]

    def stats(self) -> dict:
        return {
            "documents": self.documents,
            "terms": len(self._df),
            "avgdl": round(self.avgdl, 2),
            "k1": self.k1,
            "b": self.b,
            "tokenizer": tokenizer.backend(),
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

    ⚠️ 数据来源是 **Chroma 里的 chunk**，与向量检索同一批文档：加文档只需重建向量索引，
    BM25 下次取用时会自动跟着更新，不会出现「向量有、词面没有」。
    ⚠️ 读取走 `indexer.all_documents()`，**不构造 embedding** —— 为了建词面索引
    白加载一次 bge 模型（约 1 秒）不划算。
    """
    from . import indexer

    global _INDEX
    if _INDEX is None or refresh:
        _INDEX = BM25.from_texts(indexer.all_documents())
    return _INDEX


def search(query: str, k: int | None = None) -> list[dict]:
    """给 CLI / 调试用的检索入口（P2.2 之前不接进 `retriever`）。"""
    index = get_index()
    return [
        {"doc_id": h.doc_id, "score": h.score, "matched": list(h.matched)}
        for h in index.search(query, k)
    ]


def stats() -> dict:
    return get_index().stats()
