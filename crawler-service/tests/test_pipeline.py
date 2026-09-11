"""采集服务单元测试：指纹去重、标签拆分（纯逻辑，不依赖数据库）。

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
    """跨站去重：不同写法命中同一指纹。"""

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
