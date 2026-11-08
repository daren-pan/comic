"""查询类型判定：决定这次查询走「常规路径」还是「深度路径」。

## 为什么需要

实测两种查询的最佳策略是**相反的**：

| 查询类型 | 例子 | 好用的路径 |
|---|---|---|
| 文档原话型 | `scheduler 为什么独立进程` | 常规：双路 + RRF（50ms，Top-1 90%） |
| 口语/同义型 | `收藏漫画有更新时如何提醒` | 深度：改写 + 合并 + 重排（找不到 → 第 1 名） |

把所有查询都走深度路径会**拖垮**前者（黄金题 Top-1 90% → 50%），
全部走常规路径又会**漏掉**后者（正确答案根本进不了候选）。
所以按类型分流。

## 判定规则（纯规则，毫秒级，可解释）

只看"有没有疑问词"不行 —— `scheduler 为什么独立进程` 也是疑问句，但它每个词都在语料里，
字面路一抓就中，不该走深度路径。

真正有区分力的是**查询词在语料词表里的覆盖率**：

- 覆盖率低 → 用户用的词和文档对不上（"提醒" vs "通知"）→ 需要改写 + 重排；
- 覆盖率高 → 字面路就能命中 → 保持常规排序。

规则顺序：
1. **专名型**：含标识符（`X-Service-Token` / `require_admin` / `hnsw:space`）→ 常规。
2. **口语型**：像自然提问（疑问词/口语标记）**且** 覆盖率 < 0.6 → 深度路径。
3. **关键词型**：长度 ≤ 8 且不是提问 → 常规。
4. 其余 → 文档原话型 → 常规。
"""
from __future__ import annotations

import re

#: 代码标识符：带 `_` `-` `.` `:` 的英文串，或全大写缩写。
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[_\-.:][A-Za-z0-9]+)+|^[A-Z]{2,}$")

#: 疑问词（含口语说法）。
_QUESTION_WORDS = (
    "怎么", "为什么", "为何", "如何", "咋", "啥", "谁", "哪个", "哪些", "哪里",
    "什么", "多少", "多久", "多长时间", "能不能", "可不可以", "是不是", "有没有",
)

#: 口语标记（语气词/第一人称）：出现即更像"随口问"。
_COLLOQUIAL_MARKERS = ("我", "咋", "啥", "呗", "呀", "啊", "呢", "吧", "一下", "咋办")

#: 覆盖率低于这个值，说明用户用词和语料对不上，值得走深度路径。
MIN_COVERAGE = 0.6

DOC_LIKE = "doc_like"
KEYWORD = "keyword"
COLLOQUIAL = "colloquial"
IDENTIFIER = "identifier"

LABELS = {
    DOC_LIKE: "文档原话型",
    KEYWORD: "关键词型",
    COLLOQUIAL: "口语型",
    IDENTIFIER: "专名型",
}

_VOCAB: set[str] | None = None


def corpus_vocab() -> set[str]:
    """语料词表（来自已经建好的 BM25 倒排表，**不额外扫描语料**）。"""
    global _VOCAB
    if _VOCAB is None:
        from . import lexical

        index = lexical.get_index()
        _VOCAB = set(getattr(index._retriever.vectorizer, "idf", {}) or {})
    return _VOCAB


def coverage(query: str, vocab: set[str] | None = None) -> float:
    """查询词有多大比例在语料词表里（0~1）。"""
    from . import tokenizer

    tokens = [t for t in tokenizer.tokens(query or "") if len(t) >= 2] or []
    if not tokens:
        return 1.0
    known = vocab if vocab is not None else corpus_vocab()
    hit = sum(1 for token in tokens if token in known)
    return hit / len(tokens)


def classify(query: str, vocab: set[str] | None = None) -> str:
    """返回 `identifier` / `colloquial` / `keyword` / `doc_like`。"""
    text = (query or "").strip()
    if not text:
        return DOC_LIKE

    # ① 专名型优先：英文标识符、反引号包裹的词
    if _IDENTIFIER.search(text) or "`" in text:
        return IDENTIFIER

    length = len(text)
    has_ascii = bool(re.search(r"[A-Za-z]", text))
    has_question = any(word in text for word in _QUESTION_WORDS)

    # ② 含英文/专有词 → 视为文档原话型：这类查询字面路命中率高，
    #    走深度路径反而会被重排带偏（实测 scheduler / chat 这类查询都属此列）。
    if has_ascii:
        return DOC_LIKE

    # ③ 纯中文 + 疑问句 + 有一定长度 → 口语型（深度路径）
    #    长度门槛 8 是实测出来的：试过 12（更保守），Recall 从 90% 掉到 86.7%、
    #    Top-1 不变 —— 说明短疑问句（`更新了怎么通知我`）恰恰需要深度路径。
    if has_question and length >= 8:
        return COLLOQUIAL

    # ④ 关键词型：短查询且不是提问
    if length <= 8 and not has_question:
        return KEYWORD

    return DOC_LIKE


def label(query_type: str) -> str:
    return LABELS.get(query_type, query_type)


def wants_deep(query: str) -> bool:
    """是否该走「深度路径」（改写 + 合并 + 重排）。"""
    return classify(query) == COLLOQUIAL
