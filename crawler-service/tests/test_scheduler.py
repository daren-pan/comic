"""SyncScheduler 定时调度节奏测试（增量/全量/巡检的触发时机）。

纯逻辑测试：用内存版 FakeStorage 替代真实存储，不连任何数据库、不写临时文件。
运行：python -m unittest discover -s tests -v（需 PYTHONPATH=src）
注意：时间基准选在凌晨 0 点（hour < FULL_SYNC_HOUR=3），避免全量同步
（full_sync 复用 incremental_sync 实现）干扰增量计数；全量用例单独用 3 点后时间。
"""

from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.config import SourceConfig
from comic_crawler.models import ComicListResult
from comic_crawler.scheduler import SyncScheduler
from comic_crawler.storage import Storage

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

    def fetch_comic_list(self, page: int = 1, since=None) -> ComicListResult:
        self.list_calls += 1
        return ComicListResult(items=[], page=page, has_next=False)

    def fetch_comic_detail(self, comic):
        raise AssertionError("空列表不应触发详情抓取")

    def fetch_chapter_pages(self, detail, chapter):
        return []


class FakeStorage(Storage):
    """内存版存储：只记录同步日志，不落库（调度节奏测试无需真实持久化）。"""

    def __init__(self) -> None:
        self.logs: list[dict] = []

    # 调度器 tick 会触达的最小接口
    def log_sync(self, source: str, mode: str, stats) -> None:
        self.logs.append({"source": source, "mode": mode})

    def get_last_sync_time(self, source: str):
        return None  # 无历史完成时间：调度器按"首次"处理（since=None），保证测试节奏不变

    def list_uncached_pages(self, limit: int | None = None, since=None, until=None, source=None) -> list:
        return []

    def list_pages(self, limit: int = 500) -> list:
        return []

    # 其余抽象方法不参与调度节奏测试，统一占位
    def get_comic_id_by_fingerprint(self, fingerprint: str):
        return None

    def upsert_comic(self, detail, fingerprint):
        return 0, True

    def upsert_chapter(self, comic_id, chapter):
        return 0, True

    def upsert_pages(self, chapter_id, pages):
        return len(pages)

    def stats(self) -> dict:
        return {"comics": 0, "chapters": 0, "pages": 0}

    def mark_page_cached(self, page_id, oss_url) -> None:
        pass

    def mark_page_invalid(self, page_id) -> None:
        pass

    def count_pages_by_status(self) -> dict:
        return {}

    def list_comics(self, category=None, keyword=None, sort="updated", page=1, page_size=12):
        return [], 0

    def get_comic(self, comic_id):
        return None

    def get_chapters(self, comic_id):
        return []

    def get_chapter(self, chapter_id):
        return None

    def get_pages(self, chapter_id):
        return []

    def get_categories(self):
        return []

    def get_comic_tags(self, comic_id):
        return []

    def set_comic_cover(self, comic_id, cover_url) -> None:
        pass


class TestSyncScheduler(unittest.TestCase):
    def setUp(self):
        self.db = FakeStorage()
        self.adapter = FakeAdapter()
        self.source = SourceConfig(name="fake", crawl_interval_seconds=600, enabled=True)

    def _sched(self, source: SourceConfig | None = None) -> SyncScheduler:
        return SyncScheduler(
            adapters={"fake": self.adapter},
            storage=self.db,
            sources=[source or self.source],
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
        s = self._sched(SourceConfig(name="fake", crawl_interval_seconds=600, enabled=False))
        tasks = s.tick(now=T0)
        self.assertNotIn("fake::incremental", tasks)
        self.assertEqual(self.adapter.list_calls, 0)


if __name__ == "__main__":
    unittest.main()
