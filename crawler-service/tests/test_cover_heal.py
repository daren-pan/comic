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

from comic_crawler.scheduling import heal_covers  # noqa: E402


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


def _fake_ensure(ok_urls: set[str], calls: list[tuple[int, str]], titles: dict | None = None):
    """替身：url 在 ok_urls 内视为下载成功，回填相对 key。

    `**kw` 用来吃掉调用方补充的 `comic_title` / `source`（只进日志，不影响落盘行为）——
    顺便断言它们确实被传了下来（`titles` 里收一份，供"日志要带作品名"的用例检查）。
    """

    def _ensure(storage, image_store, comic_id, cover_url, **kw):
        calls.append((comic_id, cover_url))
        if titles is not None:
            titles[comic_id] = kw.get("comic_title")
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
        self.titles: dict = {}
        provider = (lambda name: FakeAdapter(adapter_url)) if use_adapter and adapter_url is not None else None
        with patch(
            "comic_crawler.images.transfer.ensure_cover_local",
            _fake_ensure(ok_urls or set(), calls, self.titles),
        ):
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
        """外链重下失败且无适配器 → 计 failed（DB 保留原外链）。"""
        storage, stats, calls = self._run(
            [_row(3, "https://img.x/bad.jpg")], ok_urls=set()
        )
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["healed"], 0)
        self.assertEqual(calls, [(3, "https://img.x/bad.jpg")])

    def test_external_failed_then_refetch_heals(self):
        """外链地址失效 → 回源取最新地址再落盘（2026-09-18 补：登记地址失效后不再永远重试）。"""
        storage, stats, calls = self._run(
            [_row(8, "https://img.x/wrong.jpg")],
            adapter_url="https://img.x/right.jpeg",
            ok_urls={"https://img.x/right.jpeg"},
        )
        self.assertEqual(stats["healed"], 1)
        self.assertEqual(stats["failed"], 0)
        self.assertEqual(calls, [(8, "https://img.x/wrong.jpg"), (8, "https://img.x/right.jpeg")])
        self.assertEqual(storage.covers[8], "covers/8.jpg")

    def test_external_failed_refetch_same_url_not_retried(self):
        """回源拿到的还是同一个地址（刚已失败）→ 不再重复下载，计 failed。"""
        storage, stats, calls = self._run(
            [_row(9, "https://img.x/dead.jpg")],
            adapter_url="https://img.x/dead.jpg",
            ok_urls=set(),
        )
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(calls, [(9, "https://img.x/dead.jpg")])   # 只试了一次

    def test_external_failed_refetch_unavailable_skipped(self):
        """回源拿不到地址（作品下架等）→ 计 skipped，不误报 healed。"""
        storage, stats, _ = self._run(
            [_row(10, "https://img.x/dead.jpg")], adapter_url="", ok_urls=set()
        )
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["failed"], 0)
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

    def test_title_passed_to_cover_log(self):
        """封面落盘要**带上作品名**：日志里只写 comic_id 的话，看日志的人还得回库查是哪部。

        用户 2026-09-18 明确要求「消息中要显示具体漫画 id 和名称」—— 所以 heal 的两条
        落盘路径都必须把 title 透传下去（两条路径：外链重试、回源后落盘）。
        """
        self._run([_row(2, "https://img.x/a.jpg")], ok_urls={"https://img.x/a.jpg"})
        self.assertEqual(self.titles[2], "作品2")

        self._run(
            [_row(4, "")], adapter_url="https://img.x/c.jpg", ok_urls={"https://img.x/c.jpg"}
        )
        self.assertEqual(self.titles[4], "作品4")

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
