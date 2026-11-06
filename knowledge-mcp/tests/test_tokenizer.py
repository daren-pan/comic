"""分词器单测。

两条原则：
1. **没有 jieba 也必须全绿** —— 它是可选依赖，缺了要能干净地退回 bigram；
2. 装了 jieba 才跑真分词断言（用 `skipUnless` 跳过），不假装验证过。
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from comic_rag_mcp import tokenizer

HAS_JIEBA = tokenizer._jieba_module() is not None


def _env(value: str):
    return mock.patch.dict(os.environ, {"COMIC_KB_TOKENIZER": value})


class BigramTokenTest(unittest.TestCase):
    def test_english_words_kept_whole(self) -> None:
        self.assertEqual(
            tokenizer.bigram_tokens("X-Service-Token 怎么配"),
            ["service", "token", "怎么", "么配"],
        )

    def test_chinese_uses_bigram_window(self) -> None:
        self.assertEqual(
            tokenizer.bigram_tokens("图片加载不出来"),
            ["图片", "片加", "加载", "载不", "不出", "出来"],
        )

    def test_single_char_dropped(self) -> None:
        self.assertEqual(tokenizer.bigram_tokens("章"), [])
        # 单个汉字不成词，但英文数字只要够 2 位就保留
        self.assertEqual(tokenizer.bigram_tokens("K8s 部署"), ["k8s", "部署"])

    def test_forced_bigram_ignores_jieba(self) -> None:
        with _env("bigram"):
            self.assertEqual(tokenizer.backend(), "bigram")
            self.assertEqual(
                tokenizer.tokens("南京市长江大桥"),
                tokenizer.bigram_tokens("南京市长江大桥"),
            )

    def test_unique_tokens_dedup(self) -> None:
        with _env("bigram"):
            got = tokenizer.unique_tokens("token token token 过期")
            self.assertEqual(got, list(dict.fromkeys(got)))
            self.assertEqual(got.count("token"), 1)

    def test_keep_duplicates_for_tf(self) -> None:
        """BM25 要词频，`tokens()` 不能去重。"""
        with _env("bigram"):
            self.assertEqual(tokenizer.tokens("token token").count("token"), 2)


class BackendSelectionTest(unittest.TestCase):
    def test_invalid_value_falls_back_to_auto(self) -> None:
        with _env("随便写的值"):
            self.assertEqual(tokenizer.chosen(), "auto")

    def test_auto_follows_jieba_availability(self) -> None:
        """auto = 装了 jieba 走 mixed（jieba 的超集），没装退回零依赖的 bigram。"""
        with _env("auto"):
            self.assertEqual(tokenizer.backend(), "mixed" if HAS_JIEBA else "bigram")

    @unittest.skipIf(HAS_JIEBA, "装了 jieba 时这条不适用")
    def test_forced_jieba_without_package_raises(self) -> None:
        """显式要求 jieba 却不满足时必须报错，不能静默降级。"""
        with _env("jieba"):
            with self.assertRaises(RuntimeError) as ctx:
                tokenizer.backend()
            self.assertIn("pip install jieba", str(ctx.exception))

    def test_describe_has_backend(self) -> None:
        info = tokenizer.describe()
        self.assertIn(info["backend"], {"jieba", "bigram", "mixed"})
        self.assertTrue(info["userDict"].endswith("terms.txt"))


@unittest.skipUnless(HAS_JIEBA, "未安装 jieba，跳过真分词断言")
class JiebaTokenTest(unittest.TestCase):
    def test_dictionary_segmentation(self) -> None:
        with _env("jieba"):
            self.assertEqual(tokenizer.backend(), "jieba")
            self.assertEqual(
                tokenizer.tokens("南京市长江大桥"), ["南京市", "长江大桥"]
            )

    def test_user_dict_terms_stay_whole(self) -> None:
        """用户词典里的项目术语不能被切碎（否则上 jieba 反而更难用）。"""
        with _env("jieba"):
            for term in ("判重", "图床", "管理台", "按需导入"):
                self.assertIn(term, tokenizer.tokens(term + "怎么做"))

    def test_auto_prefers_mixed_when_available(self) -> None:
        with _env("auto"):
            self.assertEqual(tokenizer.backend(), "mixed")


@unittest.skipUnless(HAS_JIEBA, "mixed 后端依赖 jieba")
class MixedTokenTest(unittest.TestCase):
    """`mixed` = 标识符整体保留 + 部件展开 + 中文走 jieba。"""

    def test_identifier_kept_and_split(self) -> None:
        with _env("mixed"):
            self.assertEqual(tokenizer.backend(), "mixed")
            got = tokenizer.tokens("X-Service-Token 怎么配")
            # 整体（精确匹配）+ 部件（部分匹配）+ 中文词
            self.assertIn("x-service-token", got)
            self.assertIn("service", got)
            self.assertIn("token", got)
            self.assertIn("怎么", got)

    def test_underscore_identifier_expanded(self) -> None:
        with _env("mixed"):
            got = tokenizer.tokens("require_admin 是哪个装饰器")
            for token in ("require_admin", "require", "admin"):
                self.assertIn(token, got)

    def test_chinese_side_has_no_cross_boundary_noise(self) -> None:
        """中文段交给 jieba：`…是什么` 不该产出 `是什` 这种假词。"""
        with _env("mixed"):
            got = tokenizer.tokens("同源判重键是什么")
            self.assertNotIn("是什", got)
            self.assertIn("判重", got)

    def test_single_letter_identifier_dropped(self) -> None:
        with _env("mixed"):
            self.assertNotIn("x", tokenizer.tokens("X 是什么"))

    def test_trailing_punctuation_not_glued(self) -> None:
        with _env("mixed"):
            got = tokenizer.tokens("用 require_admin。")
            self.assertIn("require_admin", got)
            self.assertNotIn("require_admin。", got)

    def test_mixed_requires_jieba(self) -> None:
        """没有 jieba 时必须报错（不能悄悄退回 bigram）。"""
        if HAS_JIEBA:
            self.skipTest("本机已装 jieba")
        with _env("mixed"), mock.patch.object(tokenizer, "_jieba_module", return_value=None):
            with self.assertRaises(RuntimeError):
                tokenizer.backend()


if __name__ == "__main__":
    unittest.main()
