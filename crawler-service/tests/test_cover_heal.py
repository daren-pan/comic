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
    """duck-type 存储：只实现 heal_covers 用到的方法。

    `list_comics` 记下最近一次收到的 `source`（供「自愈要按源限定」用例断言）——
    真实的 MySQLStorage.list_comics 会据此只返回该源的作品。
    `find_comics` 记下收到的筛选参数（`last_find`）并按 id/标题子串做内存过滤，
    供「按作品筛选」用例断言（真实的走主键 IN / title LIKE）。
    """

    def __init__(self, comics: list[dict]) -> None:
        self.comics = comics
        self.covers: dict[int, str] = {}
        self.last_source = "<unset>"
        self.last_find: dict | None = None

    def list_comics(self, page: int = 1, page_size: int = 12, **kw):
        self.last_source = kw.get("source", "<missing>")
        return self.comics, len(self.comics)

    def find_comics(self, comic_ids=None, title_like=None, source=None):
        self.last_find = {"comic_ids": comic_ids, "title_like": title_like, "source": source}
        ids = set(comic_ids or [])
        names = [str(t) for t in (title_like or [])]
        return [
            c for c in self.comics
            if c["id"] in ids or any(n in str(c.get("title") or "") for n in names)
        ]

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


def _fake_ensure(ok_urls: set[str], calls: list[tuple[int, str]], titles: dict | None = None,
                 forces: list | None = None):
    """替身：url 在 ok_urls 内视为下载成功，回填相对 key。

    `**kw` 用来吃掉调用方补充的 `comic_title` / `source` / `force`（只进日志与落盘分支，
    不影响统计）—— 顺便断言它们确实被传了下来（`titles` / `forces` 各收一份，
    供"日志要带作品名" / "force 要透传"的用例检查）。
    """

    def _ensure(storage, image_store, comic_id, cover_url, **kw):
        calls.append((comic_id, cover_url))
        if titles is not None:
            titles[comic_id] = kw.get("comic_title")
        if forces is not None:
            forces.append(kw.get("force"))
        if cover_url in ok_urls:
            storage.set_comic_cover(comic_id, f"covers/{comic_id}.jpg")
            return True
        return False

    return _ensure


class TestHealCovers(unittest.TestCase):
    def _run(self, comics, existing=None, ok_urls=None, adapter_url=None, use_adapter=True,
             source=None, force=False, comic_ids=None, title_like=None):
        storage = FakeStorage(comics)
        store = FakeStore(existing)
        calls: list[tuple[int, str]] = []
        self.titles: dict = {}
        self.forces: list = []
        provider = (lambda name: FakeAdapter(adapter_url)) if use_adapter and adapter_url is not None else None
        with patch(
            "comic_crawler.images.transfer.ensure_cover_local",
            _fake_ensure(ok_urls or set(), calls, self.titles, self.forces),
        ):
            stats = heal_covers(
                storage, store, adapter_provider=provider, source=source,
                force=force, comic_ids=comic_ids, title_like=title_like,
            )
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

    def test_source_forwarded_to_list_comics(self):
        """给了 source → 原样透传给 list_comics，只自愈该源。"""
        storage, _, _ = self._run([_row(1, "covers/1.jpg")], source="copymanga")
        self.assertEqual(storage.last_source, "copymanga")

    def test_no_source_scans_all(self):
        """不给 source → 传 None（= 全库），保持默认全量兜底语义。"""
        storage, _, _ = self._run([_row(1, "covers/1.jpg")])
        self.assertIsNone(storage.last_source)

    # ---------------- 按作品筛选 + force 强制重下（2026-09-20） ----------------

    def test_force_redownloads_healthy_cover(self):
        """force=True：文件在也强制回源重下覆盖 —— 修「文件在但内容是错的」封面。

        这是普通自愈做不到的：判据只看文件在不在、不看内容，错图会被当健康跳过。
        """
        storage, stats, calls = self._run(
            [_row(1, "covers/1.jpg")],
            existing={"covers/1.jpg"},
            adapter_url="https://img.x/new.jpg",
            ok_urls={"https://img.x/new.jpg"},
            force=True,
        )
        self.assertEqual(stats["healed"], 1)
        self.assertEqual(stats["skipped"], 0)
        self.assertEqual(calls, [(1, "https://img.x/new.jpg")])
        self.assertEqual(self.forces, [True])          # force 透传给了落盘原语

    def test_no_force_skips_healthy_cover(self):
        """默认 force=False：文件在 → 健康跳过，不下载（保持旧行为，避免整库重下）。"""
        storage, stats, calls = self._run(
            [_row(1, "covers/1.jpg")],
            existing={"covers/1.jpg"},
            adapter_url="https://img.x/new.jpg",
            ok_urls={"https://img.x/new.jpg"},
        )
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(calls, [])
        self.assertEqual(self.forces, [])

    def test_filter_by_comic_ids(self):
        """comic_ids：只处理命中的 id（走 find_comics，不整表拉取）。"""
        storage, stats, calls = self._run(
            [_row(1, "covers/1.jpg"), _row(2, "covers/2.jpg")],
            existing={"covers/1.jpg", "covers/2.jpg"},
            adapter_url="https://img.x/a.jpg",
            ok_urls={"https://img.x/a.jpg"},
            force=True, comic_ids=[2],
        )
        self.assertEqual(stats["checked"], 1)          # 只有 1 部被处理
        self.assertEqual(calls, [(2, "https://img.x/a.jpg")])
        self.assertEqual(storage.last_find["comic_ids"], [2])

    def test_filter_by_title(self):
        """title_like：按标题子串命中（名称入口）。"""
        storage, stats, calls = self._run(
            [_row(1, "covers/1.jpg"), _row(2, "covers/2.jpg")],
            existing={"covers/1.jpg", "covers/2.jpg"},
            adapter_url="https://img.x/a.jpg",
            ok_urls={"https://img.x/a.jpg"},
            force=True, title_like=["作品2"],
        )
        self.assertEqual(stats["checked"], 1)
        self.assertEqual(calls, [(2, "https://img.x/a.jpg")])

    def test_filter_supports_multiple_works(self):
        """一次多部：comic_ids 与 title_like 混填 → OR 命中（多部一起自愈）。"""
        storage, stats, calls = self._run(
            [_row(1, "covers/1.jpg"), _row(2, "covers/2.jpg"), _row(3, "covers/3.jpg")],
            existing={"covers/1.jpg", "covers/2.jpg", "covers/3.jpg"},
            adapter_url="https://img.x/a.jpg",
            ok_urls={"https://img.x/a.jpg"},
            force=True, comic_ids=[1], title_like=["作品3"],
        )
        self.assertEqual(stats["checked"], 2)          # id=1 与 名称含「作品3」的 id=3
        self.assertEqual({c[0] for c in calls}, {1, 3})

    def test_no_filter_uses_list_comics(self):
        """不给筛选 → 走 list_comics（全库，保持旧行为），不碰 find_comics。"""
        storage, _, _ = self._run([_row(1, "covers/1.jpg")], existing={"covers/1.jpg"})
        self.assertIsNone(storage.last_find)
        self.assertIsNone(storage.last_source)


if __name__ == "__main__":
    unittest.main()
