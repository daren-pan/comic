"""lazy_transfer 分层下载策略测试（过期预判 + 现场重拉兜底）。

纯逻辑测试：内存 Fake 存储/图库/适配器，不连数据库、不写文件。
场景覆盖：
- t 已过期 → 跳过旧 URL，现场重拉新 URL 下载成功；
- t 未过期 → 直接用登记 URL 下载，不触发重拉；
- 无 t 参数（永久 URL，如 pepper）→ 直接下载；
- 过期但无适配器 / 适配器不支持重拉 → 转存失败；
- 未过期但下载 403 → 重拉兜底成功。

运行：python -m unittest discover -s tests -v（需 PYTHONPATH=src）
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.image_service import lazy_transfer

# 时间戳：PAST = 已过期；FUTURE = 远未来（未过期）
PAST = 1700000000  # 2023-11 已过期
FUTURE = 4102444800  # 2100 年未过期


def _row(**over) -> dict:
    base = {
        "page_id": 1,
        "page_no": 1,
        "source_url": "",
        "oss_url": None,
        "cached_status": "未转存",
        "comic_id": 10,
        "chapter_id": 20,
        "source_chapter_id": "200",
        "source": "fake",
        "source_comic_id": "100",
    }
    base.update(over)
    return base


class FakeStorage:
    """duck-type 存储：只实现 lazy_transfer 用到的两个方法。"""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.cached: list[tuple[int, str]] = []
        self.last_since = None
        self.last_until = None
        self.last_source = None

    def list_uncached_pages(
        self, limit: int = 200, since=None, until=None, source=None
    ) -> list[dict]:
        self.last_since = since
        self.last_until = until
        self.last_source = source
        return self.rows[:limit]

    def mark_page_cached(self, page_id: int, oss_url: str) -> None:
        self.cached.append((page_id, oss_url))


class FakeImageStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data


class FakeAdapter:
    """可重拉的适配器：fetch_source_page_urls 返回给定 URL 列表并计数。"""

    source_name = "fake"

    def __init__(self, urls: list[str] | None) -> None:
        self.urls = urls
        self.calls = 0

    def fetch_source_page_urls(self, source_comic_id: str, source_chapter_id: str):
        self.calls += 1
        return self.urls


class TestLazyTransferRefresh(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeImageStore()
        self.downloaded: list[str] = []  # 记录下载器实际收到的 URL

    def _downloader(self):
        def dl(url: str, key: str) -> bytes:
            self.downloaded.append(url)
            return b"IMG:" + url.encode()
        return dl

    def _run(self, rows: list[dict], adapter=None):
        storage = FakeStorage(rows)
        return (
            storage,
            lazy_transfer(
                storage,
                self.store,
                downloader=self._downloader(),
                adapter_provider=(lambda name: adapter) if adapter else None,
            ),
        )

    def test_expired_url_refetched(self):
        """t 过期：不用旧 URL，现场重拉新 URL 后下载成功。"""
        old = f"https://img.x/a.jpg?sign=x&t={PAST}"
        fresh = [f"https://img.x/a.jpg?sign=new&t={FUTURE}"]
        storage, stats = self._run(
            [_row(source_url=old)],
            adapter=FakeAdapter(fresh),
        )
        self.assertEqual(stats["transferred"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertNotIn(old, self.downloaded)  # 旧 URL 未被尝试
        self.assertEqual(self.downloaded, fresh)
        self.assertEqual(len(storage.cached), 1)

    def test_fresh_url_direct_no_refetch(self):
        """t 未过期：直接用登记 URL，不触发重拉。"""
        url = f"https://img.x/b.jpg?sign=x&t={FUTURE}"
        ad = FakeAdapter(["https://img.x/NEW.jpg?t=99"])
        storage, stats = self._run([_row(source_url=url)], adapter=ad)
        self.assertEqual(stats["transferred"], 1)
        self.assertEqual(self.downloaded, [url])
        self.assertEqual(ad.calls, 0)  # 未调用重拉

    def test_no_t_param_direct(self):
        """无 t（永久 URL，如 pepper）：直接下载。"""
        url = "https://cdn.pepper.example/img.jpg"
        storage, stats = self._run([_row(source_url=url)])
        self.assertEqual(stats["transferred"], 1)
        self.assertEqual(self.downloaded, [url])

    def test_expired_no_adapter_fails(self):
        """过期且无适配器（无法重拉）：转存失败。"""
        storage, stats = self._run(
            [_row(source_url=f"https://img.x/a.jpg?sign=x&t={PAST}")],
            adapter=None,
        )
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["transferred"], 0)
        self.assertEqual(self.downloaded, [])  # 旧 URL 未试、无重拉
        self.assertEqual(storage.cached, [])

    def test_expired_adapter_unsupported_fails(self):
        """过期且适配器不支持重拉（返回 None）：转存失败。"""
        storage, stats = self._run(
            [_row(source_url=f"https://img.x/a.jpg?sign=x&t={PAST}")],
            adapter=FakeAdapter(None),
        )
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["transferred"], 0)

    def test_download_failure_triggers_refetch(self):
        """t 未过期但下载失败（403）：重拉兜底一次后成功。"""
        old = f"https://img.x/c.jpg?sign=old&t={FUTURE}"
        fresh = ["https://img.x/c.jpg?sign=new&t=99"]
        storage = FakeStorage([_row(source_url=old)])
        ad = FakeAdapter(fresh)
        captured: list[str] = []
        store = FakeImageStore()

        def dl(url: str, key: str) -> bytes:
            captured.append(url)
            if url == old:
                raise Exception("403 Forbidden")
            return b"IMG:" + url.encode()

        stats = lazy_transfer(
            storage, store, downloader=dl, adapter_provider=(lambda name: ad)
        )
        self.assertEqual(stats["transferred"], 1)
        self.assertEqual(captured, [old, fresh[0]])  # 先试旧 → 失败 → 重拉成功
        self.assertEqual(ad.calls, 1)

    def test_since_until_passed_through(self):
        """since/until 透传给存储层（配合增量采集只转本次新收的页）。"""
        url = f"https://img.x/d.jpg?sign=x&t={FUTURE}"
        storage = FakeStorage([_row(source_url=url)])
        stats = lazy_transfer(
            storage,
            FakeImageStore(),
            downloader=self._downloader(),
            since="2026-09-07T16:25:00",
            until="2026-09-07T17:05:00",
            source="weebcentral",
        )
        self.assertEqual(storage.last_since, "2026-09-07T16:25:00")
        self.assertEqual(storage.last_until, "2026-09-07T17:05:00")
        self.assertEqual(storage.last_source, "weebcentral")  # 仅转存某源
        self.assertEqual(stats["transferred"], 1)


if __name__ == "__main__":
    unittest.main()
