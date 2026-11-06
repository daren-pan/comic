"""混合检索的融合逻辑单测（纯函数，不需要 Chroma / 模型）。

RRF 的行为很容易被误以为"分数越高越相关"，所以这里用**手算值**钉住：
两条列表各排第一 → 分最高；只在一条列表里出现 → 只拿一份；名次靠后 → 分更低。
"""
from __future__ import annotations

import unittest

from comic_rag_mcp.retriever import _passes, _rrf_merge


class RRFFusionTest(unittest.TestCase):
    def test_two_lists_merge_by_rank(self) -> None:
        fused = _rrf_merge([("vector", ["a", "b"]), ("lexical", ["b", "c"])], k=60)
        # b 在两路都出现（第 2 / 第 1），合并后必然第一
        order = sorted(fused, key=lambda d: (-fused[d]["rrf"], d))
        self.assertEqual(order[0], "b")
        self.assertAlmostEqual(fused["b"]["rrf"], 1 / 62 + 1 / 61, places=9)
        self.assertAlmostEqual(fused["a"]["rrf"], 1 / 61, places=9)
        self.assertAlmostEqual(fused["c"]["rrf"], 1 / 62, places=9)

    def test_sources_and_ranks_recorded(self) -> None:
        fused = _rrf_merge([("vector", ["a", "b"]), ("lexical", ["b"])], k=60)
        self.assertEqual(fused["b"]["sources"], ["vector", "lexical"])
        self.assertEqual(fused["b"]["ranks"], {"vector": 2, "lexical": 1})
        self.assertEqual(fused["a"]["sources"], ["vector"])

    def test_both_first_is_a_tie(self) -> None:
        """两路各自的第一名，RRF 分会**完全相同** —— 这就是它"只合并、不裁决"的本性。

        实际系统里这种平局要靠 rerank（或精确匹配规则）打破，不能指望调 k 解决。
        """
        fused = _rrf_merge([("vector", ["a"]), ("lexical", ["b"])], k=60)
        self.assertAlmostEqual(fused["a"]["rrf"], fused["b"]["rrf"], places=9)

    def test_empty_inputs(self) -> None:
        self.assertEqual(_rrf_merge([], k=60), {})
        self.assertEqual(_rrf_merge([("vector", [])], k=60), {})

    def test_larger_k_shrinks_scores_but_keeps_order(self) -> None:
        small = _rrf_merge([("vector", ["a", "b"])], k=10)
        large = _rrf_merge([("vector", ["a", "b"])], k=100)
        self.assertGreater(small["a"]["rrf"], large["a"]["rrf"])
        self.assertGreater(small["a"]["rrf"], small["b"]["rrf"])
        self.assertGreater(large["a"]["rrf"], large["b"]["rrf"])


class FilterTest(unittest.TestCase):
    def test_kind_and_module_filters(self) -> None:
        meta = {"kind": "module_readme", "module": "api", "status": "current"}
        self.assertTrue(_passes(meta, None, None, False))
        self.assertTrue(_passes(meta, "module_readme", None, False))
        self.assertFalse(_passes(meta, "schema", None, False))
        self.assertTrue(_passes(meta, None, "api", False))
        self.assertFalse(_passes(meta, None, "web", False))

    def test_historical_excluded_unless_requested(self) -> None:
        meta = {"status": "historical"}
        self.assertFalse(_passes(meta, None, None, False))
        self.assertTrue(_passes(meta, None, None, True))


if __name__ == "__main__":
    unittest.main()
