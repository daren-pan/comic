"""heal_covers 封面自愈纯逻辑测试。

纯逻辑：内存 Fake 存储/图库/适配器，不连数据库、不联网、不写文件。
（ensure_cover_local 的真实下载被 mock —— 只验证 heal_covers 的分支决策与统计。）

运行：PYTHONPATH=src python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.scheduler import heal_covers  # noqa: E402


class FakeStorage:
    """duck-type 存储：只实现 heal_covers 用到的方法。"""

    def __init__(self, comics: list[dict]) -> None:
        self.comics = comics
        self.covers: dict[int, str] = {}

    def list_comics(self, page: int = 1, page_size: int = 12, **kw):
        return self.comics, len(self.comics)

    def set_comic_cover(self, comic_id: int, key: str) -> None:
        self.covers[comic_id] = key


class FakeStore:
    """内存图库：exists() 依据预置 key 集合判定。"""

    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or set()

    def exists(self, key: str) -> bool:
        return key in self.existing


class FakeAdapter:
    def __init__(self, cover_url: str) -> None:
        self.source_name = "fake"
        self.cover_url = cover_url
        self.pre = 0
        self.post = 0

    def pre_fetch(self) -> None:
        self.pre += 1

    def post_fetch(self) -> None:
        self.post += 1

    def fetch_comic_detail(self, brief):
        return SimpleNamespace(cover_url=self.cover_url)


def _row(cid: int, cover: str, source: str = "fake") -> dict:
    return {
        "id": cid,
        "source": source,
        "source_comic_id": str(1000 + cid),
        "title": f"作品{cid}",
        "cover_url": cover,
    }


def _fake_ensure(ok_urls: set[str], calls: list[tuple[int, str]]):
    """替身：url 在 ok_urls 内视为下载成功，回填相对 key。"""

    def _ensure(storage, image_store, comic_id, cover_url):
        calls.append((comic_id, cover_url))
        if cover_url in ok_urls:
            storage.set_comic_cover(comic_id, f"covers/{comic_id}.jpg")
            return True
        return False

    return _ensure


class TestHealCovers(unittest.TestCase):
    def _run(self, comics, existing=None, ok_urls=None, adapter_url=None, use_adapter=True):
        storage = FakeStorage(comics)
        store = FakeStore(existing)
        calls: list[tuple[int, str]] = []
        provider = (lambda name: FakeAdapter(adapter_url)) if use_adapter and adapter_url is not None else None
        with patch("comic_crawler.image_service.ensure_cover_local", _fake_ensure(ok_urls or set(), calls)):
            stats = heal_covers(storage, store, adapter_provider=provider)
        return storage, stats, calls

    def test_local_healthy_skipped(self):
        """本地 key 且文件存在 → 健康跳过，不下载。"""
        storage, stats, calls = self._run(
            [_row(1, "covers/1.jpg")], existing={"covers/1.jpg"}
        )
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["healed"], 0)
        self.assertEqual(calls, [])

    def test_external_redownloaded(self):
        """外链未落盘 → 直接重下成功。"""
        storage, stats, calls = self._run(
            [_row(2, "https://img.x/a.jpg")], ok_urls={"https://img.x/a.jpg"}
        )
        self.assertEqual(stats["healed"], 1)
        self.assertEqual(calls, [(2, "https://img.x/a.jpg")])
        self.assertEqual(storage.covers[2], "covers/2.jpg")

    def test_external_download_fails(self):
        """外链重下失败 → 计 failed（DB 保留原外链）。"""
        storage, stats, calls = self._run(
            [_row(3, "https://img.x/bad.jpg")], ok_urls=set()
        )
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["healed"], 0)

    def test_empty_refetch_via_adapter(self):
        """封面为空 → 回源取 cover_url 再落盘，adapter 生命周期各调一次。"""
        storage, stats, calls = self._run(
            [_row(4, "")], adapter_url="https://img.x/c.jpg", ok_urls={"https://img.x/c.jpg"}
        )
        self.assertEqual(stats["healed"], 1)
        self.assertEqual(calls, [(4, "https://img.x/c.jpg")])

    def test_empty_no_adapter_skipped(self):
        """封面为空但无适配器 → 跳过。"""
        storage, stats, calls = self._run([_row(5, "")], use_adapter=False)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["healed"], 0)
        self.assertEqual(calls, [])

    def test_local_missing_refetch(self):
        """本地 key 但图库文件缺失 → 回源重取封面落盘。"""
        storage, stats, calls = self._run(
            [_row(6, "covers/6.jpg")],
            existing=set(),
            adapter_url="https://img.x/d.jpg",
            ok_urls={"https://img.x/d.jpg"},
        )
        self.assertEqual(stats["healed"], 1)
        self.assertEqual(calls, [(6, "https://img.x/d.jpg")])

    def test_placeholder_path_skipped(self):
        """非外链非本地 key（如演示占位路径）→ 跳过。"""
        storage, stats, calls = self._run([_row(7, "/images/7/cover.jpg")], use_adapter=False)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(calls, [])

    def test_checked_counts_all(self):
        """checked 统计全部扫描到的作品数。"""
        comics = [_row(1, "covers/1.jpg"), _row(2, ""), _row(3, "https://img.x/e.jpg")]
        storage, stats, calls = self._run(
            comics, existing={"covers/1.jpg"}, ok_urls={"https://img.x/e.jpg"}, use_adapter=False
        )
        self.assertEqual(stats["checked"], 3)


if __name__ == "__main__":
    unittest.main()
