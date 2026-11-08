"""检索评估指标：Recall@k / MRR@k / nDCG@k。

**只看名次，不碰分数。** 三种模式的分数不可比（余弦 0~1 / BM25 无上界 / RRF ≈0.016），
指标若依赖绝对分值，A/B 就会在错误的尺子上比较。

## 期望集合是"任一即可"

`eval_cases.CASES` 里的 `expect` 是**可选答案列表**（命中其中任意一个都算对），
所以理想排序的 DCG 取 **1.0** —— 正确文档排在第一位即满分。
不要按 `len(expect)` 算 IDCG，那会假设"所有候选都要被找到"，与本项目的标注语义不符。
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def rank_of_first_hit(
    ranked_paths: Sequence[str],
    expect: Iterable[str],
    k: int | None = None,
) -> int | None:
    """首个命中期望集合的名次（**1 起**）；前 k 条里没有返回 None。"""
    wanted = set(expect)
    limit = len(ranked_paths) if k is None else min(k, len(ranked_paths))
    for index in range(limit):
        if ranked_paths[index] in wanted:
            return index + 1
    return None


def recall_at_k(ranked_paths: Sequence[str], expect: Iterable[str], k: int = 5) -> float:
    """前 k 条里有没有正确文档（0 或 1）。"""
    return 1.0 if rank_of_first_hit(ranked_paths, expect, k) else 0.0


def reciprocal_rank(ranked_paths: Sequence[str], expect: Iterable[str], k: int = 5) -> float:
    """1 / 名次；没命中记 0。第 1 名 = 1.0，第 4 名 = 0.25。"""
    rank = rank_of_first_hit(ranked_paths, expect, k)
    return 1.0 / rank if rank else 0.0


def ndcg_at_k(ranked_paths: Sequence[str], expect: Iterable[str], k: int = 5) -> float:
    """二值增益的 nDCG@k。

    增益只区分"是不是期望文档"：命中 1、否则 0；IDCG 取 1.0（见模块注释）。
    分档（如"同一文档的相邻小节"记 0.7）留到有标注数据后再开 ——
    没有数据支撑的权重比不做更糟。
    """
    wanted = set(expect)
    gains = [1.0 if path in wanted else 0.0 for path in ranked_paths[:k]]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    return min(dcg, 1.0)


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(rows: Sequence[dict], k: int = 5) -> dict:
    """把逐题记录汇总成一张指标表。

    `rows` 每项至少要有 `paths`（按名次）与 `expect`。
    """
    recalls: list[float] = []
    rrs: list[float] = []
    ndcgs: list[float] = []
    top1 = 0
    hit_but_not_first = 0
    for row in rows:
        rank = rank_of_first_hit(row["paths"], row["expect"], k)
        recalls.append(1.0 if rank else 0.0)
        rrs.append(1.0 / rank if rank else 0.0)
        ndcgs.append(ndcg_at_k(row["paths"], row["expect"], k))
        if rank == 1:
            top1 += 1
        elif rank:
            hit_but_not_first += 1
    total = len(rows)
    return {
        "total": total,
        "k": k,
        "recall": mean(recalls),
        "mrr": mean(rrs),
        "ndcg": mean(ndcgs),
        "top1": (top1 / total) if total else 0.0,
        "hit_but_not_first": hit_but_not_first,
        "miss": total - top1 - hit_but_not_first,
    }
