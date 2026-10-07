"""翻页安全阀：`MAX_PAGES_PER_SYNC`（2026-10-07 由 50 页降到 **5 页**）。

为什么：一页约 20 部 → 5 页 ≈ 100 部，而每部都要抓详情 + 补齐缺失章节（一部可能几百章），
再大就容易一轮跑很久、也更容易撞源站风控。它是**硬上限**，增量与全量一视同仁。

这里用"永远还有下一页"的假适配器把阀门逼出来：数它被请求了几页即可。
运行：python -m unittest discover -s tests（离线可跑，不连库）
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_core.models import ComicListResult  # noqa: E402

from comic_crawler.scheduling.sync import MAX_PAGES_PER_SYNC, incremental_sync  # noqa: E402


class _PagingAdapter:
    """按 `natural_end` 决定还有没有下一页；条目为空 —— 只为把翻页阀门逼出来。"""

    source_name = "fake"

    def __init__(self, natural_end: int | None = None) -> None:
        self._natural_end = natural_end          # None = 永远还有下一页
        self.pages_requested: list[int] = []
        self.since_seen: list[object] = []

    def pre_fetch(self) -> None:
        pass

    def post_fetch(self) -> None:
        pass

    def fetch_comic_list(self, *, page=1, since=None):
        self.pages_requested.append(page)
        self.since_seen.append(since)
        has_next = True if self._natural_end is None else page < self._natural_end
        return ComicListResult(items=[], page=page, has_next=has_next)


class _Storage:
    """只实现翻页用得到的几个方法；`last_sync` 由用例给定（None = 没有水位）。"""

    def __init__(self, last_sync: datetime | None = None) -> None:
        self._last_sync = last_sync

    def get_last_sync_time(self, source):
        return self._last_sync

    def upsert_comic(self, detail, fingerprint):        # 本用例列表为空，不会走到入库
        raise AssertionError("列表为空，不该走到入库")

    def touch_comic_sync_time(self, comic_id, when=None) -> None:
        raise AssertionError("列表为空，不该走到这里")

    def log_sync(self, source, mode, stats) -> None:
        pass


class TestPageSafetyValve(unittest.TestCase):
    def test_valve_is_five_pages(self):
        """阀门值就是 5 页（改动点本身，钉住防止被随手调回去）。"""
        self.assertEqual(MAX_PAGES_PER_SYNC, 5)

    def test_first_run_stops_at_valve(self):
        """首次（无水位）→ 翻到 5 页就停。"""
        adapter = _PagingAdapter()
        incremental_sync(adapter, _Storage(last_sync=None))
        self.assertEqual(adapter.pages_requested, [1, 2, 3, 4, 5])

    def test_with_watermark_also_stops_at_valve(self):
        """有水位（增量接着上次跑）→ 同样是 5 页硬上限（不是"只有首次受限"）。"""
        adapter = _PagingAdapter()
        incremental_sync(adapter, _Storage(last_sync=datetime.now() - timedelta(days=1)))
        self.assertEqual(len(adapter.pages_requested), MAX_PAGES_PER_SYNC)
        self.assertIsNotNone(adapter.since_seen[0], "水位要作为 since 传给适配器")

    def test_manual_since_also_stops_at_valve(self):
        """手动指定 since → 也受同一个阀门约束。"""
        adapter = _PagingAdapter()
        incremental_sync(adapter, _Storage(last_sync=None), since="2026-10-01")
        self.assertEqual(len(adapter.pages_requested), MAX_PAGES_PER_SYNC)
        self.assertIsInstance(adapter.since_seen[0], datetime, "ISO 字符串要转成 datetime")

    def test_full_mode_also_stops_at_valve(self):
        """全量模式同样受阀门约束（想彻底翻完只能分批）。"""
        adapter = _PagingAdapter()
        incremental_sync(adapter, _Storage(last_sync=None), mode="full")
        self.assertEqual(len(adapter.pages_requested), MAX_PAGES_PER_SYNC)

    def test_list_ending_earlier_is_respected(self):
        """列表先结束就结束 —— 阀门不会硬凑页数。"""
        adapter = _PagingAdapter(natural_end=3)
        incremental_sync(adapter, _Storage(last_sync=None))
        self.assertEqual(adapter.pages_requested, [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
