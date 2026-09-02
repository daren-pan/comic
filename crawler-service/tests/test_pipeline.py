"""采集服务单元测试：指纹去重、适配器解析、增量同步幂等。

运行：python -m unittest discover -s tests -v
（需在 crawler-service 目录下，或设置 PYTHONPATH=src）
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.adapter import create_adapter
from comic_crawler.fingerprint import build_fingerprint, normalize_title
from comic_crawler.image_store import LocalImageStore
from comic_crawler.storage import SQLiteStorage


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
    """演示源站适配器：解析 fixture HTML。"""

    def setUp(self):
        self.adapter = create_adapter("demo_source")
        self.tmp = tempfile.TemporaryDirectory()
        self.db = SQLiteStorage(db_path=str(Path(self.tmp.name) / "t.db"))

    def tearDown(self):
        self.tmp.cleanup()

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


class TestIncrementalSync(unittest.TestCase):
    """增量同步幂等：跑两遍，第二遍不产生新数据。"""

    def setUp(self):
        self.adapter = create_adapter("demo_source")
        self.tmp = tempfile.TemporaryDirectory()
        self.db = SQLiteStorage(db_path=str(Path(self.tmp.name) / "t.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_sync_twice_idempotent(self):
        from comic_crawler.scheduler import incremental_sync

        stats1 = incremental_sync(self.adapter, self.db)
        stats2 = incremental_sync(self.adapter, self.db)

        self.assertEqual(stats1.new_comics, 3)
        self.assertEqual(stats1.new_chapters, 4 + 3 + 3)  # 1001:4 + 1002:3 + 1003:3
        # 第二遍：全部命中指纹 → 0 新增
        self.assertEqual(stats2.new_comics, 0)
        self.assertEqual(stats2.new_chapters, 0)
        self.assertEqual(self.db.stats()["comics"], 3)

    def test_cross_source_merge(self):
        """两个源站同一作品 → 指纹合并，库内只有一条。"""
        from comic_crawler.models import ComicDetail
        from comic_crawler.fingerprint import build_fingerprint

        a = ComicDetail(source="siteA", source_comic_id="1", title="海贼王", author="尾田荣一郎")
        b = ComicDetail(source="siteB", source_comic_id="2", title="海贼王（重置版）", author="尾田荣一郎")

        id_a, new_a = self.db.upsert_comic(a, build_fingerprint(a.title, a.author))
        id_b, new_b = self.db.upsert_comic(b, build_fingerprint(b.title, b.author))

        self.assertTrue(new_a)
        self.assertFalse(new_b)
        self.assertEqual(id_a, id_b)
        self.assertEqual(self.db.stats()["comics"], 1)


class TestCrossSourcePipeline(unittest.TestCase):
    """流水线级跨站合并：源 A + 源 B 全量同步后，重复作品只保留一条。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = SQLiteStorage(db_path=str(Path(self.tmp.name) / "t.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_sources_merge(self):
        from comic_crawler.scheduler import incremental_sync

        adapter_a = create_adapter("demo_source")
        adapter_b = create_adapter("demo_source_b")

        sa = incremental_sync(adapter_a, self.db)          # 3 部（海贼王/进击的巨人/咒术回战）
        sb = incremental_sync(adapter_b, self.db)          # 2 部（海贼王重复 + 鬼灭之刃新增）

        self.assertEqual(sa.new_comics, 3)
        self.assertEqual(sb.new_comics, 1)                 # 只有鬼灭之刃是新增
        self.assertEqual(sb.updated_comics, 1)             # 海贼王（重置版）命中指纹 → 合并
        self.assertEqual(self.db.stats()["comics"], 4)     # 3 + 1，而不是 5


class TestImageTransfer(unittest.TestCase):
    """懒转存 + 失效巡检。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = SQLiteStorage(db_path=str(Path(self.tmp.name) / "t.db"))
        self.store = LocalImageStore(root=str(Path(self.tmp.name) / "oss"))
        from comic_crawler.scheduler import incremental_sync
        incremental_sync(create_adapter("demo_source"), self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lazy_transfer_all_pages(self):
        """同步后全部未转存 → 懒转存后全部已转存。"""
        from comic_crawler.image_service import lazy_transfer

        before = self.db.count_pages_by_status()
        self.assertEqual(before.get("未转存"), 50)

        stats = lazy_transfer(self.db, self.store)
        self.assertEqual(stats["transferred"], 50)

        after = self.db.count_pages_by_status()
        self.assertEqual(after.get("已转存"), 50)
        self.assertNotIn("未转存", after)

    def test_inspect_recovers_lost_object(self):
        """已转存对象被删 → 巡检标记失效并自动恢复。"""
        from comic_crawler.image_service import lazy_transfer
        from comic_crawler.scheduler import inspect_sync

        lazy_transfer(self.db, self.store)
        # 模拟 OSS 对象丢失：删掉第一个转存的文件
        first = self.db.list_pages(limit=1)[0]
        self.store.delete(first["oss_url"])
        self.assertFalse(self.store.exists(first["oss_url"]))

        stats = inspect_sync(self.db, image_store=self.store)
        self.assertGreaterEqual(stats["invalid"], 1)
        self.assertGreaterEqual(stats["recovered"], 1)
        self.assertEqual(self.db.count_pages_by_status().get("已转存"), 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
