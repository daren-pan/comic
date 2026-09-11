"""采集服务单元测试：指纹去重、适配器解析（纯逻辑，不依赖数据库）。

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

from comic_crawler.sources import create_adapter
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


class TestDemoAdapter(unittest.TestCase):
    """演示源站适配器：解析 fixture HTML（纯逻辑，无外部依赖）。"""

    def setUp(self):
        self.adapter = create_adapter("demo_source")

    def test_list_parses_three_comics(self):
        result = self.adapter.fetch_comic_list(page=1)
        self.assertEqual(len(result.items), 3)
        self.assertTrue(result.has_next)
        self.assertEqual(result.items[0].title, "海贼王")
        self.assertEqual(result.items[2].status, "连载")

    def test_detail_parses_chapters(self):
        brief = self.adapter.fetch_comic_list(page=1).items[0]
        detail = self.adapter.fetch_comic_detail(brief)
        self.assertIn("路飞", detail.description)
        self.assertEqual(len(detail.chapters), 4)
        self.assertEqual(detail.chapters[0].chapter_no, 1080)

    def test_chapter_pages(self):
        brief = self.adapter.fetch_comic_list(page=1).items[0]
        detail = self.adapter.fetch_comic_detail(brief)
        pages = self.adapter.fetch_chapter_pages(detail, detail.chapters[0])
        self.assertEqual(len(pages), 5)
        self.assertEqual(pages[0].page_no, 1)
        self.assertIn("/images/", pages[0].source_url)


class TestTagsFrom(unittest.TestCase):
    """标签拆分回归测试：category 用 `/` 分隔时不得产生孤儿 `/` 标签。

    2026-09-05 修复前，_tags_from 分隔符优先级把「空格」排在「/」之前，
    导致「连载 / 国漫」先按空格切开 -> ['连载', '/', '国漫']，`/` 成为孤儿标签，
    前端标签栏据此聚合出一个「/ 33」（33 部漫画被错误关联到 `/`）。
    """

    @staticmethod
    def _mk(category: str):
        return ComicDetail(
            source="demo", source_comic_id="x", title="t", author="a",
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
