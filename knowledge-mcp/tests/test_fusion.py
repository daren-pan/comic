"""混合检索的融合逻辑单测（不需要 Chroma / 模型）。

融合**排序**由 LangChain 的 `EnsembleRetriever.weighted_reciprocal_rank` 负责，
这里钉住的是本项目附加的两件事：**分数怎么算**（手算值）与**来源怎么记**。

RRF 的行为很容易被误以为"分数越高越相关"，所以用**手算值**钉住：
两条列表各排第一 → 分最高；只在一条列表里出现 → 只拿一份；名次靠后 → 分更低。
"""
from __future__ import annotations

import unittest

from comic_rag_mcp import config
from comic_rag_mcp.retriever import _fuse_ranked, _passes, _rrf_weights


def _docs(*ids: str) -> dict:
    """伪造 `doc_id → Document`（`_fuse_ranked` 只用到 key）。"""
    return {doc_id: object() for doc_id in ids}


class RRFFusionTest(unittest.TestCase):
    def test_two_lists_merge_by_rank(self) -> None:
        ranked = [("vector", ["a", "b"]), ("lexical", ["b", "c"])]
        ordered = _fuse_ranked(ranked, _docs("a", "b", "c"))
        ids = [doc_id for doc_id, *_ in ordered]
        # b 在两路都出现（第 2 / 第 1），合并后必然第一
        self.assertEqual(ids[0], "b")
        by_id = {doc_id: score for doc_id, score, *_ in ordered}
        weight = _rrf_weights(2)
        # 期望值按当前配置推导，避免默认值一变单测就红
        self.assertAlmostEqual(
            by_id["b"], weight[0] / (config.RRF_K + 2) + weight[1] / (config.RRF_K + 1), places=6
        )
        self.assertAlmostEqual(by_id["a"], weight[0] / (config.RRF_K + 1), places=6)
        self.assertAlmostEqual(by_id["c"], weight[1] / (config.RRF_K + 2), places=6)

    def test_sources_recorded(self) -> None:
        ranked = [("vector", ["a", "b"]), ("lexical", ["b"])]
        ordered = _fuse_ranked(ranked, _docs("a", "b"))
        sources = {doc_id: srcs for doc_id, _, _, srcs in ordered}
        self.assertEqual(sources["b"], ["vector", "lexical"])
        self.assertEqual(sources["a"], ["vector"])

    def test_both_first_ties_only_when_equal_weight(self) -> None:
        """等权时两路各自第一名 RRF 分**完全相同** —— RRF"只合并、不裁决"的本性。

        现在默认权重是语义 0.75 / 字面 0.25，所以平局不再出现：语义第一直接胜出。
        这条测试同时钉住"权重确实生效"。
        """
        import comic_rag_mcp.config as config

        original = config.RRF_WEIGHTS
        try:
            config.RRF_WEIGHTS = [1.0, 1.0]
            tied = {d: s for d, s, *_ in _fuse_ranked([("vector", ["a"]), ("lexical", ["b"])], _docs("a", "b"))}
            self.assertAlmostEqual(tied["a"], tied["b"], places=9)

            config.RRF_WEIGHTS = [0.75, 0.25]
            weighted = {d: s for d, s, *_ in _fuse_ranked([("vector", ["a"]), ("lexical", ["b"])], _docs("a", "b"))}
            self.assertGreater(weighted["a"], weighted["b"])
        finally:
            config.RRF_WEIGHTS = original

    def test_empty_inputs(self) -> None:
        self.assertEqual(_fuse_ranked([], {}), [])
        self.assertEqual(_fuse_ranked([("vector", [])], {}), [])

    def test_larger_k_shrinks_scores_but_keeps_order(self) -> None:
        import comic_rag_mcp.config as config

        original = config.RRF_K
        try:
            config.RRF_K = 10
            small = {d: s for d, s, *_ in _fuse_ranked([("vector", ["a", "b"])], _docs("a", "b"))}
            config.RRF_K = 100
            large = {d: s for d, s, *_ in _fuse_ranked([("vector", ["a", "b"])], _docs("a", "b"))}
        finally:
            config.RRF_K = original
        self.assertGreater(small["a"], large["a"])
        self.assertGreater(small["a"], small["b"])
        self.assertGreater(large["a"], large["b"])


class RankingPreferenceTest(unittest.TestCase):
    """默认参数下的排序**偏好**（参考方向，不是数学必然）：

    1. 两路第一
    2. 一路第一 + 一路靠后
    3. 单路语义第一
    4. 单路字面第一
    5. 两路靠后
    6. 单路靠后

    六种情形是**互斥的假设**，没法塞进同一次 `_fuse_ranked` 调用里比较，
    所以这里按公式解析算分（`score = w / (k + rank)`，两路都命中就累加）。
    """

    #: 每路候选数上限，决定"靠后"是第几名。
    RANK_FAR = 20

    @staticmethod
    def _scores(k: int, weights: list[float]) -> dict[str, float]:
        w_first, w_second = weights
        far = RankingPreferenceTest.RANK_FAR
        return {
            "两路第一": (w_first + w_second) / (k + 1),
            "一路第一+一路靠后": w_first / (k + 1) + w_second / (k + far),
            "单路语义第一": w_first / (k + 1),
            "单路字面第一": w_second / (k + 1),
            "两路靠后": (w_first + w_second) / (k + far),
            "单路靠后": min(w_first, w_second) / (k + far),
        }

    def test_default_params_follow_preference(self) -> None:
        scores = self._scores(config.RRF_K, config.RRF_WEIGHTS)
        order = sorted(scores, key=lambda name: -scores[name])
        self.assertEqual(
            order,
            ["两路第一", "一路第一+一路靠后", "单路语义第一", "单路字面第一", "两路靠后", "单路靠后"],
            f"实际顺序：{order}",
        )

    def test_large_k_favours_two_list(self) -> None:
        """k 很大时「两路都靠后」会压过「单路字面第一」—— 这是原先混合 Top-1 低的原因之一。"""
        scores = self._scores(60, [1.0, 1.0])
        self.assertGreater(scores["两路靠后"], scores["单路字面第一"])


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
