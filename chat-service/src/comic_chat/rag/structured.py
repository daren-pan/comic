"""结构化召回：用字段做精确匹配，补上向量检索的两块盲区。

## 为什么需要这一路

向量检索回答的是「**哪一条最像**」（单点语义匹配）。它做不好两类查询：

| 查询 | 向量的问题（实测 2026-10-30） | 结构化怎么解 |
|---|---|---|
| 「有没有科幻的」 | 这是**集合筛选**，正确答案是 6 部；向量只返回 1 条最像的，**top4 里 0 条相关** | 标签字段含「科幻」的全部返回 → **6/6** |
| 「유산도」（韩文作者） | `bge-small-zh` 词表里没有韩文，完全失效（0.455，答成《HIGH不起来的约会》） | 作者字段精确包含 → **0.95** |

这不是「精度高低」的差别，是**能力类型**的差别：
- 向量 = 找最像的那一条
- 结构化 = 找出符合某属性的全部

## 匹配策略：反向包含

判断「**书名 / 作者是否出现在提问里**」，而不是「提问是否出现在文档里」。
因为用户问句长（「五十岚正邦的作品」，8 字）、字段短（「五十岚正邦」，5 字），
只有反方向才成立 —— 正向包含在本项目里几乎永远匹配不上。

## 分数是固定档位，不是余弦相似度

| 命中方式 | 分数 | 依据 |
|---|---|---|
| 书名出现在提问里 | 1.00 | 用户报了确切书名，就该 100% 命中 |
| 作者出现在提问里 | 0.95 | 作者名比书名更长、更唯一 |
| 标签出现在提问里 | 0.85 | 一个标签对应多部作品，精确度略低 |

> 标签的唯一来源是 `comic_tag` 关联的 `tag` 表。`comic.category` 是采集侧早期存的
> 原始分类串（`'爱情, 校园'` 这种多值字符串），**已废弃、不参与检索** —— 两边都用会让
> 同一部作品出现两套互相矛盾的题材。
| 2 字片段交集 ≥ 3 个 | 0.60 + n×0.05 | 兜底：长标题用户记不全时（「转生恶役小姐的哥哥」） |

**刻意和向量的分数直接混排**：用户报了确切书名时，不该被向量模型打个 0.79 还排在
另一部作品后面。结构化命中的分数天然高于阈值，不会被 `_retrieve()` 的过滤筛掉。

## 为什么不做分词

中文分词要引入 `jieba`（约 20MB + 词典加载），而这里只有 54 部作品、字段总量不到 20KB。
用 2 字滑窗做交集已经够用，且零依赖。**数据量涨到几千部时再考虑倒排索引**，
届时这份「全表扫」的注释就是该动手的信号。
"""
from __future__ import annotations

import re

from zhconv import convert as zh_convert

from .documents import ComicFact, comic_facts

#: 书名/作者出现在提问里时的分数（按可信度排序）
SCORE_TITLE = 1.00
SCORE_AUTHOR = 0.95
SCORE_TAG = 0.85

#: 兜底策略：提问的 2 字片段与书名重叠数达到这个门槛才认为相关。
#: 定 3 而不是 2 —— 实测「短发女孩和猫的故事」在交集 2 时会误命中
#: 《態度冷淡的店員小姐的故事》（只共享「的故」这类虚词片段），3 就不会。
_MIN_OVERLAP = 3

#: 兜底分数的起点与步长（交集越多越可信，但不超过标签档）
_OVERLAP_BASE = 0.60
_OVERLAP_STEP = 0.05
_OVERLAP_CAP = 0.90

_CJK = re.compile(r"[\u4e00-\u9fff]")
_TAG_SPLIT = re.compile(r"[、,，/]")


def _bigrams(text: str) -> set[str]:
    """2 字滑窗，只保留纯中文片段（英文/韩文走另一条匹配路径）。"""
    return {
        text[i : i + 2]
        for i in range(len(text) - 1)
        if _CJK.match(text[i]) and _CJK.match(text[i + 1])
    }


def _strip_book_marks(title: str) -> str:
    """去掉 `《》` —— 站内标题不带书名号，但用户可能照着 UI 加进去。"""
    return title.strip("《》「」 ")


def match(question: str, limit: int = 8) -> list[tuple[ComicFact, float, str]]:
    """结构化匹配，返回 `[(ComicFact, score, reason)]`，按分数降序。

    `reason` 只用于调试（`/lab/search` 会展示），不进 prompt。

    没有命中时返回空列表 —— 调用方继续用向量结果，不要把它当成「查不到」的结论。
    """
    if not question or not question.strip():
        return []

    # 统一转简体：站内标题大量是繁体（《創世的大河》《電鋸人》），用户打简体时
    # 字面完全对不上。向量能扛一部分，字面匹配一点都扛不了。
    query = zh_convert(question, "zh-cn")
    query_grams = _bigrams(query)

    hits: list[tuple[ComicFact, float, str]] = []
    for fact in comic_facts():
        title = _strip_book_marks(fact.title_cn)

        # ① 书名：用户直接报书名的场景（「杜鹃的婚约最新话」也走这条）
        if len(title) >= 2 and title in query:
            hits.append((fact, SCORE_TITLE, "标题"))
            continue

        # ② 作者：一条作品多个作者时用「、」拼，逐个看
        if fact.author_cn != "未知":
            authors = [a.strip() for a in _TAG_SPLIT.split(fact.author_cn) if a.strip()]
            if any(len(a) >= 2 and a in query for a in authors):
                hits.append((fact, SCORE_AUTHOR, "作者"))
                continue

        # ③ 标签：支撑「有没有科幻的」这类集合筛选。
        #
        # ⚠️ **只认 `comic_tag` 关联出来的标签，不碰 `comic.category`** ——
        # 后者是采集侧早期存的原始分类串（`'爱情, 校园'` 这种多值字符串），
        # 已废弃，权威来源是 tag 字典表 + comic_tag 关联（见 `comic_schema.sql`）。
        # 拿废弃字段兜底会让「同一部作品有两个真相」，且 tags 更新后旧值还在参与匹配。
        matched_label = next((t for t in fact.tags_cn if t in query), None)
        if matched_label:
            hits.append((fact, SCORE_TAG, f"标签:{matched_label}"))
            continue

        # ④ 兜底：长标题用户记不全时（「转生恶役小姐的哥哥」vs 站内 40 字全名）
        overlap = len(query_grams & _bigrams(title))
        if overlap >= _MIN_OVERLAP:
            score = min(_OVERLAP_BASE + overlap * _OVERLAP_STEP, _OVERLAP_CAP)
            hits.append((fact, score, f"交集x{overlap}"))

    hits.sort(key=lambda x: -x[1])
    return hits[:limit]
