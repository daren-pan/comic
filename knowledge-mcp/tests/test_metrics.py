"""评估指标单测：用**手算值**断言，不依赖检索实现。

指标算错时最难看出来的地方是"数值一直在 0.9 附近"，所以这里刻意选能算出
精确分数的例子（第 1 名 = 1.0、第 2 名 = 1/log2(3)、第 3 名 = 0.5）。
"""
from __future__ import annotations

import math
import unittest

from comic_rag_mcp import metrics


EXPECT = ["a.md", "b.md"]


class RankTest(unittest.TestCase):
    def test_first_hit_at_top(self) -> None:
        self.assertEqual(metrics.rank_of_first_hit(["a.md", "x.md"], EXPECT, 5), 1)

    def test_first_hit_later(self) -> None:
        self.assertEqual(metrics.rank_of_first_hit(["x.md", "y.md", "b.md"], EXPECT, 5), 3)

    def test_any_of_expect_counts(self) -> None:
        """期望集合是"任一即可"，b.md 命中同样算对。"""
        self.assertEqual(metrics.rank_of_first_hit(["x.md", "b.md"], EXPECT, 5), 2)

    def test_outside_k_is_miss(self) -> None:
        self.assertIsNone(metrics.rank_of_first_hit(["x.md", "y.md", "a.md"], EXPECT, 2))

    def test_empty(self) -> None:
        self.assertIsNone(metrics.rank_of_first_hit([], EXPECT, 5))


class MetricValueTest(unittest.TestCase):
    def test_recall(self) -> None:
        self.assertEqual(metrics.recall_at_k(["a.md"], EXPECT, 5), 1.0)
        self.assertEqual(metrics.recall_at_k(["x.md"], EXPECT, 5), 0.0)

    def test_reciprocal_rank(self) -> None:
        self.assertAlmostEqual(metrics.reciprocal_rank(["a.md"], EXPECT, 5), 1.0)
        self.assertAlmostEqual(metrics.reciprocal_rank(["x.md", "a.md"], EXPECT, 5), 0.5)
        self.assertAlmostEqual(metrics.reciprocal_rank(["x.md", "y.md", "z.md"], EXPECT, 5), 0.0)

    def test_ndcg_rank1_is_one(self) -> None:
        self.assertAlmostEqual(metrics.ndcg_at_k(["a.md"], EXPECT, 5), 1.0)

    def test_ndcg_rank2(self) -> None:
        # DCG = 1/log2(3)，IDCG = 1 → 0.6309
        self.assertAlmostEqual(metrics.ndcg_at_k(["x.md", "a.md"], EXPECT, 5), 1 / math.log2(3))

    def test_ndcg_rank3(self) -> None:
        # DCG = 1/log2(4) = 0.5
        self.assertAlmostEqual(metrics.ndcg_at_k(["x.md", "y.md", "a.md"], EXPECT, 5), 0.5)

    def test_ndcg_is_monotonic_in_rank(self) -> None:
        first = metrics.ndcg_at_k(["a.md"], EXPECT, 5)
        second = metrics.ndcg_at_k(["x.md", "a.md"], EXPECT, 5)
        third = metrics.ndcg_at_k(["x.md", "y.md", "a.md"], EXPECT, 5)
        self.assertGreater(first, second)
        self.assertGreater(second, third)

    def test_ndcg_miss_is_zero(self) -> None:
        self.assertEqual(metrics.ndcg_at_k(["x.md", "y.md"], EXPECT, 5), 0.0)


class SummarizeTest(unittest.TestCase):
    def test_bundle(self) -> None:
        rows = [
            {"paths": ["a.md", "x.md"], "expect": EXPECT},          # 第 1 名
            {"paths": ["x.md", "a.md"], "expect": EXPECT},          # 第 2 名
            {"paths": ["x.md", "y.md"], "expect": EXPECT},          # 未命中
        ]
        s = metrics.summarize(rows, 5)
        self.assertEqual(s["total"], 3)
        self.assertAlmostEqual(s["recall"], 2 / 3)
        self.assertAlmostEqual(s["mrr"], (1.0 + 0.5 + 0.0) / 3)
        self.assertAlmostEqual(
            s["ndcg"], (1.0 + 1 / math.log2(3) + 0.0) / 3
        )
        self.assertAlmostEqual(s["top1"], 1 / 3)
        self.assertEqual(s["hit_but_not_first"], 1)
        self.assertEqual(s["miss"], 1)

    def test_empty_rows(self) -> None:
        s = metrics.summarize([], 5)
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["recall"], 0.0)
        self.assertEqual(s["mrr"], 0.0)


if __name__ == "__main__":
    unittest.main()
