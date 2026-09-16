"""采集服务单元测试：指纹归一（同语言内写法差异）、标签拆分（纯逻辑，不依赖数据库）。

运行：python -m unittest discover -s tests -v
（需在 crawler-service 目录下，或设置 PYTHONPATH=src；无需 MySQL，离线可跑。）
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.fingerprint import build_fingerprint, normalize_title
from comic_crawler.models import ComicDetail
from comic_crawler.storage.mysql import MySQLStorage


class TestFingerprint(unittest.TestCase):
    """指纹归一：同一语言内的写法差异命中同一指纹（指纹只作观测，不用于判重）。"""

    def test_same_comic_different_writing(self):
        fp1 = build_fingerprint("海贼王", "尾田荣一郎")
        fp2 = build_fingerprint("海贼王（重置版）", "尾田荣一郎")
        fp3 = build_fingerprint("海贼王【高清版】", "尾田荣一郎")
        self.assertEqual(fp1, fp2)
        self.assertEqual(fp1, fp3)

    def test_different_comic(self):
        self.assertNotEqual(
            build_fingerprint("海贼王", "尾田荣一郎"),
            build_fingerprint("进击的巨人", "谏山创"),
        )

    def test_normalize_halfwidth(self):
        self.assertEqual(normalize_title("ONE PIECE 海贼王"), normalize_title("one piece海贼王"))

    def test_simplified_and_traditional_are_separate(self):
        """繁简**不合并**（用户 2026-09-16 决策）：繁体（港台译本）与简体（大陆译本）
        是两个译本、章节进度往往不同，合并会丢掉其中一版的章节。

        指纹现在也不参与判重（判重看 `(source, source_comic_id)`），这里钉住的是
        "指纹不得折叠繁简"这条口径 —— 若哪天有人又往 `normalize_title` 里加繁转简，本用例会红。
        """
        self.assertNotEqual(
            build_fingerprint("電鋸人", "藤本タツキ"),
            build_fingerprint("电锯人", "藤本タツキ"),
        )
        self.assertNotEqual(normalize_title("虛構推理"), normalize_title("虚构推理"))
        # 同一语言内的写法差异仍然归一（这条是原有行为，别一起改坏）
        self.assertEqual(normalize_title("海贼王（重置版）"), normalize_title("海贼王"))


class TestTagsFrom(unittest.TestCase):
    """标签拆分回归测试：category 用 `/` 分隔时不得产生孤儿 `/` 标签。

    2026-09-05 修复前，_tags_from 分隔符优先级把「空格」排在「/」之前，
    导致「连载 / 国漫」先按空格切开 -> ['连载', '/', '国漫']，`/` 成为孤儿标签，
    前端标签栏据此聚合出一个「/ 33」（33 部漫画被错误关联到 `/`）。
    """

    @staticmethod
    def _mk(category: str):
        return ComicDetail(
            source="zaimanhua", source_comic_id="x", title="t", author="a",
            cover_url="", status="连载", category=category,
            description="", latest_chapter_title="", detail_url="", chapters=[],
        )

    def test_slash_separated_no_orphan(self):
        tags = MySQLStorage._tags_from(self._mk("连载 / 国漫"))
        self.assertEqual(tags, ["连载", "国漫"])
        self.assertNotIn("/", tags)

    def test_slash_separated_three(self):
        tags = MySQLStorage._tags_from(self._mk("热血 / 冒险 / 动作"))
        self.assertEqual(tags, ["热血", "冒险", "动作"])

    def test_comma_separated_unchanged(self):
        tags = MySQLStorage._tags_from(self._mk("爱情, 校园"))
        self.assertEqual(tags, ["爱情", "校园"])

    def test_interval_separated(self):
        tags = MySQLStorage._tags_from(self._mk("奇幻 · 冒险"))
        self.assertEqual(tags, ["奇幻", "冒险"])

    def test_mixed_tag_with_japanese(self):
        tags = MySQLStorage._tags_from(self._mk("爱情, 神鬼, ゆり, 奇幻"))
        self.assertEqual(tags, ["爱情", "神鬼", "ゆり", "奇幻"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
