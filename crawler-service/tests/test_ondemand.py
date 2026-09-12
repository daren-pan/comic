"""按需导入 / 源站搜索的纯逻辑测试（**不连库、不联网**）。

覆盖三件事：
1. 作品引用解析（作品 ID / 作品链接 / 退化为关键词）；
2. 能力缺失与搜不到的失败语义（UnsupportedCapability / ComicNotFound）；
3. 入库策略 —— **全量补章** + **一页都不登记**（导入只写目录，页清单留到读那话时）。
"""
from __future__ import annotations

import unittest

from comic_crawler.models import ChapterBrief, ComicDetail, PageInfo
from comic_crawler.scheduling.ondemand import (
    ComicNotFound,
    ComicRestricted,
    UnsupportedCapability,
    import_comic,
    resolve_brief,
)
from comic_crawler.sources.base import CrawlerAdapter
from comic_crawler.storage.base import Storage


class FakeStorage(Storage):
    """内存存储：只记录 upsert 足迹，供断言（不连库）。"""

    def __init__(self, *, chapters=None, same_source_id=None, fingerprint_id=None):
        self.chapters = list(chapters or [])       # 库内已有章节
        self.same_source_id = same_source_id       # 同源已收录时的 comic_id
        self.fingerprint_id = fingerprint_id       # 跨源已收录时的 comic_id
        self.upserted_chapters: list = []
        self.page_writes = 0                       # upsert_pages 被调用次数

    # --- 判重 ---
    def get_comic_id_by_source(self, source, source_comic_id):
        return self.same_source_id

    def get_comic_id_by_fingerprint(self, fingerprint):
        return self.fingerprint_id

    # --- 写入 ---
    def upsert_comic(self, detail, fingerprint):
        return 999, self.same_source_id is None and self.fingerprint_id is None

    def upsert_chapter(self, comic_id, chapter):
        self.upserted_chapters.append(chapter)
        return 100 + len(self.upserted_chapters), True

    def upsert_pages(self, chapter_id, pages):
        self.page_writes += 1
        return len(pages)

    def get_chapters(self, comic_id):
        return self.chapters

    def log_sync(self, source, mode, stats):
        pass

    # --- 其余抽象方法（本测试不触达） ---
    def get_last_sync_time(self, source):
        return None

    def stats(self):
        return {}

    def list_uncached_pages(self, limit=None, since=None, until=None, source=None):
        return []

    def mark_page_cached(self, page_id, oss_url):
        pass

    def mark_page_invalid(self, page_id):
        pass

    def list_pages(self, after_id=0, limit=1000, source=None):
        return []

    def count_pages_by_status(self):
        return {}

    def list_comics(self, category=None, keyword=None, sort="updated", page=1, page_size=12):
        return [], 0

    def get_comic(self, comic_id):
        return None

    def get_chapter(self, chapter_id):
        return None

    def get_pages(self, chapter_id):
        return []

    def get_page_context(self, chapter_id, page_no):
        return None

    def get_categories(self):
        return []

    def get_comic_tags(self, comic_id):
        return []

    def get_comic_tags_bulk(self, comic_ids):
        return {}

    def set_comic_cover(self, comic_id, cover_url):
        pass


class FakeAdapter(CrawlerAdapter):
    """假适配器：详情/章节由测试给定，用于断言「有没有真的去抓页清单」。"""

    source_name = "fake"
    base_url = "https://fake.test"
    capabilities = {"search", "ref"}

    def __init__(self, *, detail=None, hits=None, searchable=True, pages=1):
        if not searchable:
            self.capabilities = {"ref"}
        self.detail = detail
        self.hits = hits or []
        self.pages = pages          # 1 = 有页；0 = 空清单（真读不到）；"raise" = 探测抛异常
        self.pages_calls = 0
        self.search_calls: list[str] = []

    def fetch_comic_list(self, page=1, since=None):  # pragma: no cover
        raise AssertionError("按需导入不应走列表接口")

    def fetch_comic_detail(self, comic):
        return self.detail

    def fetch_chapter_pages(self, detail, chapter):
        self.pages_calls += 1
        if self.pages == "raise":
            raise RuntimeError("probe boom")
        if not self.pages:
            return []
        return [PageInfo(page_no=1, source_url="https://fake.test/1.jpg")]

    def search_comics(self, keyword, limit=20):
        self.search_calls.append(keyword)
        return self.hits

    def parse_comic_ref(self, ref):
        return ref.split(":")[1] if ref.startswith("fake:") else None


def _chapters(nos: list[int]) -> list[ChapterBrief]:
    return [
        ChapterBrief(
            source="fake",
            source_comic_id="42",
            chapter_no=n,
            title=f"第{n}话",
            source_chapter_id=str(n),
        )
        for n in nos
    ]


def _detail(nos: list[int], *, title="测试漫画", restricted=False) -> ComicDetail:
    return ComicDetail(
        source="fake",
        source_comic_id="42",
        title=title,
        author="某作者",
        cover_url="",          # 空封面 → 跳过落盘，测试不触网
        chapters=_chapters(nos),
        restricted=restricted,
    )


class TestResolveBrief(unittest.TestCase):
    def test_by_source_comic_id(self):
        brief = resolve_brief(FakeAdapter(), source_comic_id="7")
        self.assertEqual(brief.source_comic_id, "7")
        self.assertEqual(brief.source, "fake")

    def test_by_ref(self):
        brief = resolve_brief(FakeAdapter(), ref="fake:9")
        self.assertEqual(brief.source_comic_id, "9")

    def test_ref_falls_back_to_keyword(self):
        """链接解析不出来时，退化为关键词搜索（而不是直接失败）。"""
        from comic_crawler.models import ComicBrief

        ad = FakeAdapter(hits=[ComicBrief(source="fake", source_comic_id="55", title="搜到的")])
        brief = resolve_brief(ad, ref="随手写的东西")
        self.assertEqual(brief.source_comic_id, "55")
        self.assertEqual(ad.search_calls, ["随手写的东西"])

    def test_keyword_requires_search_capability(self):
        ad = FakeAdapter(searchable=False)
        with self.assertRaises(UnsupportedCapability):
            resolve_brief(ad, keyword="xx")

    def test_keyword_not_found(self):
        with self.assertRaises(ComicNotFound):
            resolve_brief(FakeAdapter(hits=[]), keyword="搜不到")

    def test_blank_input_rejected(self):
        with self.assertRaises(ValueError):
            resolve_brief(FakeAdapter())


class TestImportComic(unittest.TestCase):
    def test_restricted_is_rejected(self):
        """源站不可读（付费/需登录/下架）→ 拒绝导入，且不写任何章节。"""
        db = FakeStorage()
        ad = FakeAdapter(detail=_detail([1, 2, 3], restricted=True))
        with self.assertRaises(ComicRestricted):
            import_comic(ad, db, source_comic_id="42")
        self.assertEqual(db.upserted_chapters, [])
        self.assertEqual(db.page_writes, 0)
        self.assertEqual(ad.pages_calls, 0)   # is_lock 先判，不必再探测

    def test_new_comic_gets_all_chapters_and_no_pages(self):
        """新作品：**章节全量**入库，且**一页都不登记**（导入不碰页清单）。"""
        db = FakeStorage()
        ad = FakeAdapter(detail=_detail([1, 2, 3, 4, 5]))
        result = import_comic(ad, db, source_comic_id="42")

        self.assertEqual([c.chapter_no for c in db.upserted_chapters], [1, 2, 3, 4, 5])
        # 只探测了 1 次（最老一章）—— 若按章节逐章抓页清单，这里会是 5 次
        self.assertEqual(ad.pages_calls, 1)
        self.assertEqual(db.page_writes, 0)      # ← 关键：一页都没登记
        self.assertTrue(result["isNew"])
        self.assertEqual(result["newChapters"], 5)

    def test_existing_comic_fills_missing_chapters(self):
        """库内只有最新 1 话（采集所致）→ 导入应**补齐缺的那几话**，而不是只补更新的。"""
        db = FakeStorage(chapters=[{"chapter_no": 7, "id": 700}])
        ad = FakeAdapter(detail=_detail([7, 6, 5]))   # 源站新 -> 旧
        result = import_comic(ad, db, source_comic_id="42")

        self.assertEqual(sorted(c.chapter_no for c in db.upserted_chapters), [5, 6])
        self.assertEqual(result["newChapters"], 2)
        self.assertEqual(ad.pages_calls, 1)      # 仅探测 1 次

    def test_reimport_is_idempotent(self):
        """重复导入：章节已齐 → 不重复写章节。"""
        db = FakeStorage(chapters=[{"chapter_no": n} for n in (1, 2, 3)])
        ad = FakeAdapter(detail=_detail([1, 2, 3]))
        result = import_comic(ad, db, source_comic_id="42")

        self.assertEqual(db.upserted_chapters, [])
        self.assertEqual(result["newChapters"], 0)

    def test_reports_already_in_library(self):
        """同源已收录时把标记带给调用方（前端据此显示「打开」而不是「导入」）。"""
        db = FakeStorage(same_source_id=123)
        ad = FakeAdapter(detail=_detail([1]))
        result = import_comic(ad, db, source_comic_id="42")

        self.assertTrue(result["alreadySameSource"])
        self.assertEqual(result["comicId"], 123)

    def test_probe_blocks_when_no_pages(self):
        """详情未标受限、但实测一章取不到图 → 仍拒绝（避免收进空壳作品）。"""
        db = FakeStorage()
        ad = FakeAdapter(detail=_detail([1, 2, 3]), pages=0)
        with self.assertRaises(ComicRestricted):
            import_comic(ad, db, source_comic_id="42")
        self.assertEqual(db.upserted_chapters, [])

    def test_probe_failure_lets_it_through(self):
        """探测本身失败（网络异常）→ 放行，交给读时兜底，不因探测不了就误拒。"""
        db = FakeStorage()
        ad = FakeAdapter(detail=_detail([1, 2]), pages="raise")
        result = import_comic(ad, db, source_comic_id="42")
        self.assertEqual(result["newChapters"], 2)
        self.assertEqual(db.page_writes, 0)

    def test_keyword_import_uses_first_hit(self):
        from comic_crawler.models import ComicBrief

        db = FakeStorage()
        ad = FakeAdapter(
            detail=_detail([1]),
            hits=[
                ComicBrief(source="fake", source_comic_id="11", title="第一条"),
                ComicBrief(source="fake", source_comic_id="22", title="第二条"),
            ],
        )
        result = import_comic(ad, db, keyword="测试")
        self.assertEqual(result["sourceComicId"], "11")


if __name__ == "__main__":
    unittest.main()
