"""巡检键集分页测试：确保 `inspect_sync` 遍历**全表**，不被固定条数截断。

背景（架构复审第 1 点）：旧实现是 `list_pages(limit=500)` + SQL `ORDER BY id`，
**每轮都只校验 id 最小的同一批 500 页**，其余已转存页从未被校验/恢复。
本测试用「总页数 > 单批上限」的假数据，断言全部页都被遍历到。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comic_crawler.scheduling.heal import SCAN_BATCH, inspect_sync  # noqa: E402
from comic_crawler.storage.base import Storage  # noqa: E402


class FakeStore:
    """内存图库：只记录「已存在的对象 key」。"""

    def __init__(self, keys: set[str] | None = None) -> None:
        self.keys: set[str] = set(keys or set())
        self.puts: list[str] = []

    def exists(self, key: str) -> bool:
        return key in self.keys

    def get(self, key: str) -> bytes | None:
        return b"X" if key in self.keys else None

    def put(self, key: str, data: bytes) -> str:
        self.keys.add(key)
        self.puts.append(key)
        return "file://" + key


class PagingStorage(Storage):
    """内存存储：`total` 页，`list_pages` 严格实现键集分页语义。"""

    def __init__(self, total: int, cached: bool = True, source: str = "zaimanhua") -> None:
        self.pages = [
            {
                "page_id": i,
                "page_no": 1,
                "source_url": f"fixture/page-{i}.jpg",  # 非 http(s)：走 default_downloader 的离线占位分支，不发起网络
                "oss_url": f"comic/1/{i}/001.jpg" if cached else "",
                "cached_status": "已转存" if cached else "未转存",
                "comic_id": 1,
                "chapter_id": i,
                "source": source,
            }
            for i in range(1, total + 1)
        ]
        self.invalid: list[int] = []
        self.recached: list[int] = []

    # ---- 巡检用到的接口 ----
    def list_pages(
        self, after_id: int = 0, limit: int = 1000, source: str | None = None
    ) -> list:
        rows = [p for p in self.pages if p["page_id"] > after_id]
        if source:
            rows = [r for r in rows if r["source"] == source]
        return rows[:limit]

    def list_uncached_pages(self, limit=None, since=None, until=None, source=None) -> list:
        return []

    def mark_page_invalid(self, page_id: int) -> None:
        self.invalid.append(page_id)

    def mark_page_cached(self, page_id: int, oss_url: str) -> None:
        self.recached.append(page_id)

    # ---- 其余抽象方法（本测试不触达，占位实现）----
    def get_comic_id_by_fingerprint(self, fingerprint: str):
        return None

    def upsert_comic(self, detail, fingerprint: str):
        return 0, True

    def upsert_chapter(self, comic_id: int, chapter):
        return 0, True

    def upsert_pages(self, chapter_id: int, pages) -> int:
        return len(pages)

    def log_sync(self, source: str, mode: str, stats) -> None:
        pass

    def get_last_sync_time(self, source: str):
        return None

    def stats(self) -> dict:
        return {}

    def count_pages_by_status(self) -> dict:
        return {}

    def list_comics(self, category=None, keyword=None, sort="updated", page=1, page_size=12):
        return [], 0

    def get_comic(self, comic_id: int):
        return None

    def get_chapters(self, comic_id: int) -> list:
        return []

    def get_chapter(self, chapter_id: int):
        return None

    def get_pages(self, chapter_id: int) -> list:
        return []

    def get_categories(self) -> list:
        return []

    def get_comic_tags(self, comic_id: int) -> list:
        return []

    def set_comic_cover(self, comic_id: int, cover_url: str) -> None:
        pass


class TestInspectPaging(unittest.TestCase):
    """巡检必须遍历全表，且能跨多批。"""

    def test_visits_all_pages_beyond_one_batch(self) -> None:
        """总页数 > 单批上限时全部页都要被校验（旧实现只会查一批）。"""
        total = SCAN_BATCH * 3 + 7  # 明确跨 4 批
        st = PagingStorage(total, cached=True)
        store = FakeStore()  # 图库为空 → 全部「对象丢失」，走恢复分支

        stats = inspect_sync(st, image_store=store, source="zaimanhua")

        self.assertEqual(stats["checked"], total)
        self.assertEqual(stats["invalid"], total)
        self.assertEqual(stats["recovered"], total)

    def test_healthy_pages_verified_without_recovery(self) -> None:
        """对象都在 → 全部 verified，且不误标失效。"""
        total = SCAN_BATCH + 5
        st = PagingStorage(total, cached=True)
        store = FakeStore({p["oss_url"] for p in st.pages})

        stats = inspect_sync(st, image_store=store, source="zaimanhua")

        self.assertEqual(stats["checked"], total)
        self.assertEqual(stats["verified"], total)
        self.assertEqual(stats["invalid"], 0)
        self.assertEqual(st.invalid, [])

    def test_source_filter_limits_scope(self) -> None:
        """source 过滤：只校验该源的页，其他源不计入。"""
        st = PagingStorage(SCAN_BATCH + 3, cached=True, source="other")

        stats = inspect_sync(st, image_store=FakeStore(), source="zaimanhua")

        self.assertEqual(stats["checked"], 0)


if __name__ == "__main__":
    unittest.main()
