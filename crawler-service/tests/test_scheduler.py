"""SyncScheduler 定时调度节奏测试（增量/全量/巡检的触发时机）。

运行：python -m unittest discover -s tests -v（需 PYTHONPATH=src）
注意：时间基准选在凌晨 0 点（hour < FULL_SYNC_HOUR=3），避免全量同步
（full_sync 复用 incremental_sync 实现）干扰增量计数；全量用例单独用 3 点后时间。
"""

from __future__ import annotations

import datetime
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.config import SourceConfig
from comic_crawler.image_store import LocalImageStore
from comic_crawler.models import ComicListResult
from comic_crawler.scheduler import SyncScheduler
from comic_crawler.storage import SQLiteStorage

# 凌晨 0:30（不触发每日全量）
T0 = datetime.datetime(2026, 9, 2, 0, 30).timestamp()
# 凌晨 3:30（触发每日全量）
T_FULL = datetime.datetime(2026, 9, 2, 3, 30).timestamp()
T_NEXT_DAY = datetime.datetime(2026, 9, 3, 3, 30).timestamp()


class FakeAdapter:
    """最小适配器：列表恒为空，只统计调用次数。"""

    source_name = "fake"

    def __init__(self) -> None:
        self.list_calls = 0

    def pre_fetch(self) -> None:
        pass

    def post_fetch(self) -> None:
        pass

    def fetch_comic_list(self, page: int = 1) -> ComicListResult:
        self.list_calls += 1
        return ComicListResult(items=[], page=page, has_next=False)

    def fetch_comic_detail(self, comic):
        raise AssertionError("空列表不应触发详情抓取")

    def fetch_chapter_pages(self, detail, chapter):
        return []


class TestSyncScheduler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = SQLiteStorage(db_path=str(Path(self.tmp.name) / "s.db"))
        self.store = LocalImageStore(root=str(Path(self.tmp.name) / "store"))
        self.adapter = FakeAdapter()
        self.source = SourceConfig(name="fake", crawl_interval_seconds=600, enabled=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _sched(self) -> SyncScheduler:
        return SyncScheduler(
            adapters={"fake": self.adapter},
            storage=self.db,
            sources=[self.source],
            image_store=self.store,
            inspect_interval_seconds=3600,
        )

    def test_first_tick_runs_incremental(self):
        s = self._sched()
        tasks = s.tick(now=T0)
        self.assertIn("fake::incremental", tasks)
        self.assertEqual(self.adapter.list_calls, 1)

    def test_interval_not_reached_skips(self):
        s = self._sched()
        s.tick(now=T0)
        tasks = s.tick(now=T0 + 599)  # 600s 间隔未到
        self.assertEqual(tasks, [])
        self.assertEqual(self.adapter.list_calls, 1)

    def test_interval_reached_runs_again(self):
        s = self._sched()
        s.tick(now=T0)
        s.tick(now=T0 + 601)
        self.assertEqual(self.adapter.list_calls, 2)

    def test_full_sync_once_per_day(self):
        s = self._sched()
        tasks = s.tick(now=T_FULL)  # 凌晨 3 点后：增量 + 全量
        self.assertIn("fake::full", tasks)
        tasks = s.tick(now=T_FULL + 3600)  # 同日不再重复全量
        self.assertNotIn("fake::full", tasks)
        tasks = s.tick(now=T_NEXT_DAY)  # 次日再跑一次全量
        self.assertIn("fake::full", tasks)

    def test_inspect_interval(self):
        s = self._sched()
        tasks = s.tick(now=T0)
        self.assertIn("inspect", tasks)
        tasks = s.tick(now=T0 + 3599)
        self.assertNotIn("inspect", tasks)
        tasks = s.tick(now=T0 + 3601)
        self.assertIn("inspect", tasks)

    def test_disabled_source_skipped(self):
        self.source = SourceConfig(name="fake", crawl_interval_seconds=600, enabled=False)
        s = self._sched()
        tasks = s.tick(now=T0)
        self.assertNotIn("fake::incremental", tasks)
        self.assertEqual(self.adapter.list_calls, 0)


if __name__ == "__main__":
    unittest.main()
