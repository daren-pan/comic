"""MangaDex 适配器解析测试（纯逻辑，mock _api_get 返回 fixture，不联网不写库）。

覆盖：
- fetch_comic_list：manga 列表解析（title/cover/status/source_updated_at）、
  since 窗口过滤、has_next 边界；
- fetch_comic_detail：详情字段（title/author/tags/category/cover/description）+
  feed 章节反转（新 -> 旧）、chapter_no 卷话映射；
- fetch_chapter_pages：at-home 分发 URL 拼接；
- fetch_source_page_urls：重拉复用 at-home；
- _chapter_key：卷.话 -> 单调整数，无编号高位兜底。

运行：python -m unittest discover -s tests -v（需 PYTHONPATH=src）
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.adapter.mangadex_source import MangaDexAdapter

LIST_RESP = {
    "data": [
        {
            "id": "m1",
            "type": "manga",
            "attributes": {
                "title": {"zh": "测试漫画A"},
                "altTitles": [{"en": "Test Comic A"}, {"zh": "测试漫画A"}],
                "status": "ongoing",
                "latestUploadedChapter": "2026-09-07T12:00:00+00:00",
                "updatedAt": "2026-09-07T10:00:00+00:00",
            },
            "relationships": [
                {"type": "cover_art", "attributes": {"fileName": "m1-cover.jpg"}}
            ],
        },
        {
            "id": "m2",
            "type": "manga",
            "attributes": {
                "title": {"en": "Old Comic B"},
                "altTitles": [],
                "status": "completed",
                "updatedAt": "2026-09-01T10:00:00+00:00",
            },
            "relationships": [],
        },
    ],
    "limit": 25,
    "offset": 0,
    "total": 2,
}

DETAIL_RESP = {
    "data": {
        "id": "m1",
        "attributes": {
            "title": {"zh": "测试漫画A"},
            "description": {"zh": "这是一段测试简介。"},
            "status": "ongoing",
            "tags": [
                {"id": "t1", "type": "tag", "attributes": {"name": {"en": "Action"}}},
                {"id": "t2", "type": "tag", "attributes": {"name": {"en": "Adventure"}}},
            ],
        },
        "relationships": [
            {"type": "cover_art", "attributes": {"fileName": "m1-cover.jpg"}},
            {"type": "author", "attributes": {"name": "作者甲"}},
            {"type": "artist", "attributes": {"name": "画师乙"}},
        ],
    }
}

FEED_RESP = {
    "data": [
        {"id": "c1", "type": "chapter", "attributes": {"volume": "1", "chapter": "1", "title": "第一话"}},
        {"id": "c2", "type": "chapter", "attributes": {"volume": "1", "chapter": "2", "title": "第二话"}},
        {"id": "c3", "type": "chapter", "attributes": {"volume": "2", "chapter": "5", "title": ""}},
        {"id": "c4", "type": "chapter", "attributes": {"volume": None, "chapter": "5.5", "title": "小剧场"}},
    ]
}

AT_HOME_RESP = {
    "result": "ok",
    "baseUrl": "https://uploads.mangadex.org",
    "chapter": {"hash": "abc123", "data": ["p001.jpg", "p002.jpg", "p003.jpg"]},
}

# 每部漫画的最新章 publishAt（/chapter?manga=..&order[publishAt]=desc）
CHAPTER_BY_MANGA = {
    "m1": {"data": [{"id": "ch1", "type": "chapter", "attributes": {"chapter": "22.2", "publishAt": "2026-09-07T12:00:00+00:00"}}]},
    "m2": {"data": [{"id": "ch2", "type": "chapter", "attributes": {"chapter": "5", "publishAt": "2026-09-01T10:00:00+00:00"}}]},
}


class _FakeApi:
    """按 path 分发 fixture 的 _api_get 替身。"""

    def __init__(self, list_resp=None, list_pages=None, detail_resp=None, feed_resp=None,
                 home_resp=None, chapter_by_manga=None) -> None:
        self.list_resp = list_resp
        self.list_pages = list_pages or {}   # {page_no: /manga 响应}，按 offset 推导
        self.detail_resp = detail_resp
        self.feed_resp = feed_resp
        self.home_resp = home_resp
        self.chapter_by_manga = chapter_by_manga or {}
        self.calls: list[tuple[str, dict | None]] = []

    def __call__(self, path: str, params: dict | None = None) -> dict | None:
        self.calls.append((path, params))
        if path == "/manga":
            if self.list_pages:
                limit = int((params or {}).get("limit") or 25)
                pn = ((params or {}).get("offset") or 0) // limit + 1
                return self.list_pages.get(pn) or {"data": []}
            return self.list_resp
        if path == "/chapter":
            return self.chapter_by_manga.get((params or {}).get("manga"))
        if path.startswith("/manga/") and path.endswith("/feed"):
            return self.feed_resp
        if "/at-home/" in path:
            return self.home_resp
        if path.startswith("/manga/"):
            return self.detail_resp
        return None


class TestMangaDexAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.ad = MangaDexAdapter(http=object())

    def test_chapter_key_volume_and_decimal(self):
        self.assertEqual(self.ad._chapter_key("1", "5", 0), 1050)
        self.assertEqual(self.ad._chapter_key("2", "5", 0), 2050)
        self.assertEqual(self.ad._chapter_key("2", "5.5", 0), 2055)
        # 无卷无编号 → 高位兜底
        self.assertEqual(self.ad._chapter_key("", "", 7), 10007)
        self.assertGreater(self.ad._chapter_key("", "", 7), 10000)

    def test_fetch_list_parsing(self):
        self.ad._api_get = _FakeApi(
            list_resp=LIST_RESP, chapter_by_manga=CHAPTER_BY_MANGA
        )
        result = self.ad.fetch_comic_list(page=1)
        self.assertEqual(len(result.items), 2)
        first = result.items[0]
        self.assertEqual(first.source, "mangadex")
        self.assertEqual(first.source_comic_id, "m1")
        self.assertEqual(first.title, "测试漫画A")  # zh 优先
        self.assertEqual(first.status, "连载")
        self.assertEqual(
            first.cover_url,
            "https://uploads.mangadex.org/covers/m1/m1-cover.jpg",
        )
        # 时间窗口基准 = 逐部查最新章 publishAt（非 updatedAt/非 UUID）
        self.assertEqual(
            first.source_updated_at,
            datetime.fromisoformat("2026-09-07T12:00:00+00:00"),
        )
        # 列表请求不携带 contentRating[]（已去掉分级过滤）
        manga_calls = [p for path, p in self.ad._api_get.calls if path == "/manga"]
        self.assertTrue(manga_calls)
        self.assertTrue(all("contentRating[]" not in (p or {}) for p in manga_calls))
        # 超过翻页安全阀返回空（列表不再固定只翻 1 页）
        from comic_crawler.adapter import mangadex_source as md

        self.assertEqual(
            len(self.ad.fetch_comic_list(page=md.MAX_LIST_PAGES + 1).items), 0
        )

    def test_fetch_list_since_filter(self):
        self.ad._api_get = _FakeApi(
            list_resp=LIST_RESP, chapter_by_manga=CHAPTER_BY_MANGA
        )
        since = datetime.fromisoformat("2026-09-05T00:00:00+00:00")
        result = self.ad.fetch_comic_list(page=1, since=since)
        # m1 最新章 publish=09-07 保留；m2 publish=09-01 早于 since 被过滤
        self.assertEqual([it.source_comic_id for it in result.items], ["m1"])

    def test_fetch_list_since_naive_local(self):
        """调度器传的 since 是 naive（本机时间，无时区）——须按本机时区解释后
        与 MD 的 aware(UTC) publishAt 比较，不能直接比较（否则 TypeError）。"""
        self.ad._api_get = _FakeApi(
            list_resp=LIST_RESP, chapter_by_manga=CHAPTER_BY_MANGA
        )
        # 不带时区的 naive since（模拟 sync_log.finished_at）
        since = datetime.fromisoformat("2026-09-05T00:00:00")
        result = self.ad.fetch_comic_list(page=1, since=since)
        self.assertEqual([it.source_comic_id for it in result.items], ["m1"])

    def test_fetch_list_paginate_to_window_edge(self):
        """窗口内更新超一页时应继续翻页；翻到某页全部越过 since 才停。"""
        import comic_crawler.adapter.mangadex_source as md

        def _manga(mid: str) -> dict:
            return {
                "id": mid,
                "type": "manga",
                "attributes": {"title": {"zh": f"漫画{mid}"}, "status": "ongoing"},
                "relationships": [],
            }

        chapter_map = {
            "m1": {"data": [{"id": "c1", "attributes": {"publishAt": "2026-09-07T10:00:00+00:00"}}]},
            "m2": {"data": [{"id": "c2", "attributes": {"publishAt": "2026-09-06T10:00:00+00:00"}}]},
            "m3": {"data": [{"id": "c3", "attributes": {"publishAt": "2026-09-01T10:00:00+00:00"}}]},
        }
        fake = _FakeApi(
            list_pages={
                1: {"data": [_manga("m1"), _manga("m2")]},  # 09-07/09-06：窗口内
                2: {"data": [_manga("m3")]},                 # 09-01：早于 since
            },
            chapter_by_manga=chapter_map,
        )
        self.ad._api_get = fake
        since = datetime.fromisoformat("2026-09-05T00:00:00+00:00")
        with patch.object(md, "LIST_LIMIT", 2):
            r1 = self.ad.fetch_comic_list(page=1, since=since)
            self.assertEqual([it.source_comic_id for it in r1.items], ["m1", "m2"])
            self.assertTrue(r1.has_next)  # 窗口内可能还有 → 继续翻
            r2 = self.ad.fetch_comic_list(page=2, since=since)
            self.assertEqual(r2.items, [])  # 本页全在窗口外 → 无收集
            self.assertFalse(r2.has_next)  # 已越过 since 边界 → 停，不翻第 3 页

    def test_fetch_detail(self):
        fake = _FakeApi(detail_resp=DETAIL_RESP, feed_resp=FEED_RESP)
        self.ad._api_get = fake
        from comic_crawler.models import ComicBrief

        brief = ComicBrief(
            source="mangadex", source_comic_id="m1", title="测试漫画A"
        )
        detail = self.ad.fetch_comic_detail(brief)
        self.assertEqual(detail.title, "测试漫画A")
        self.assertEqual(detail.author, "作者甲, 画师乙")
        self.assertEqual(detail.tags, ["Action", "Adventure"])
        self.assertEqual(detail.category, "Action")
        self.assertEqual(detail.description, "这是一段测试简介。")
        self.assertEqual(
            detail.cover_url,
            "https://uploads.mangadex.org/covers/m1/m1-cover.jpg",
        )
        # feed 升序(1.1/1.2/2.5/5.5) → 反转成 新->旧，第 0 个应为输入最后一条
        self.assertEqual(len(detail.chapters), 4)
        self.assertEqual(detail.chapters[0].source_chapter_id, "c4")
        self.assertEqual(detail.chapters[-1].source_chapter_id, "c1")
        # chapter_no 卷话映射：第2卷 第5话 -> 2050
        c2v5 = next(c for c in detail.chapters if c.source_chapter_id == "c3")
        self.assertEqual(c2v5.chapter_no, 2050)
        # feed 请求 contentRating[] = CONTENT_RATINGS 全部 4 值（返回范围=声明范围）
        from comic_crawler.adapter.mangadex_source import CONTENT_RATINGS

        feed_params = next(p for path, p in fake.calls if path.endswith("/feed"))
        self.assertEqual(
            (feed_params or {}).get("contentRating[]"), list(CONTENT_RATINGS)
        )
        # 标题：无显式标题用 chapter 原始串
        self.assertEqual(detail.chapters[0].title, "小剧场")

    def test_fetch_chapter_pages(self):
        self.ad._api_get = _FakeApi(home_resp=AT_HOME_RESP)
        from comic_crawler.models import ChapterBrief, ComicDetail

        detail = ComicDetail(
            source="mangadex", source_comic_id="m1", title="x", chapters=[]
        )
        chapter = ChapterBrief(
            source="mangadex",
            source_comic_id="m1",
            chapter_no=1050,
            title="第1话",
            source_chapter_id="c1",
        )
        pages = self.ad.fetch_chapter_pages(detail, chapter)
        self.assertEqual(len(pages), 3)
        self.assertEqual(
            pages[0].source_url,
            "https://uploads.mangadex.org/data/abc123/p001.jpg",
        )
        self.assertEqual([p.page_no for p in pages], [1, 2, 3])
        # fetch_source_page_urls 复用 at-home（懒转存重拉）
        fresh = self.ad.fetch_source_page_urls("m1", "c1")
        self.assertEqual(len(fresh), 3)
        self.assertEqual(fresh[2], "https://uploads.mangadex.org/data/abc123/p003.jpg")

    def test_title_language_fallback(self):
        self.assertEqual(MangaDexAdapter._title({"en": "Only EN"}), "Only EN")
        self.assertEqual(MangaDexAdapter._title({"ja": "日本語"}), "日本語")
        self.assertEqual(MangaDexAdapter._title({}), "")
        self.assertEqual(MangaDexAdapter._title(None), "")


if __name__ == "__main__":
    unittest.main()
