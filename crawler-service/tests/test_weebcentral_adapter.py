"""Weeb Central 适配器解析测试（纯逻辑，mock _fetch_selector 返回 fixture，不联网不写库）。

覆盖：
- _card_to_brief：Latest Updates 卡片 -> ComicBrief（title/source_comic_id/cover/
  latest_chapter_title/source_updated_at）；
- fetch_comic_list：卡片解析、since 时间窗口过滤、page>1 返回空；
- fetch_comic_detail：系列元数据（title/author/status/tags/description/cover）+ 全章节
  列表解析（标题清洗去 " Last Read"、新 -> 旧顺序）；
- _chapter_no：Chapter/Episode/Season-Episode/Volume/小数/无编号 边界；
- fetch_chapter_pages：/images 端点返回的完整 <img> 列表（含非 lastation.us 的图床）；
- search_comics / _search_card_to_brief：/search/data 结果卡片解析（标题/作者/状态/标签/封面）；
- parse_comic_ref：作品链接 / 纯 ULID / 小写 ULID / 外站链接拒绝。

运行：python -m unittest discover -s tests -v（需 PYTHONPATH=src）
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.sources.weebcentral.adapter import WeebCentralAdapter
from parsel import Selector

# ---------------------------------------------------------------------------
# Fixture：Latest Updates 区块（含 3 张卡片：不同章节标签 + 1 张早于窗口的）
# ---------------------------------------------------------------------------
CARD_A = """<article class="bg-base-100 hover:bg-base-300 flex items-center gap-4 tooltip tooltip-bottom" data-tip="Who's That Long-Haired Senior?">
    <a class="aspect-square overflow-hidden" href="/series/01JQBT895JGB6HPH5AA1G719DX/whos-that-longhaired-senior-" preload>
        <picture>
            <source srcset="https://temp.compsci88.com/cover/small/01JQBT895JGB6HPH5AA1G719DX.webp" type="image/webp" />
            <img src="https://temp.compsci88.com/cover/fallback/01JQBT895JGB6HPH5AA1G719DX.jpg" alt="cover" />
        </picture>
    </a>
    <a class="min-w-0 flex flex-col justify-center pe-4" href="/chapters/01M21XXEZK6N769Z1CDRJVWNSW" preload>
        <div class="flex items-center gap-2">
            <div class="flex-1 truncate font-semibold text-lg">Who&#39;s That Long-Haired Senior?</div>
        </div>
        <div class="flex items-center gap-2 opacity-70">
            <img src="/static/images/icon-completed.svg" alt="" />
            <span>Episode 99</span>
        </div>
        <div class="flex items-center gap-2 opacity-70">
            <img src="/static/images/icon-clock.svg" alt="" />
            <time class="text-datetime" datetime="2026-09-09T01:53:27.539Z">2026-09-09T01:53:27.539506Z</time>
        </div>
    </a>
</article>"""

CARD_B = """<article class="bg-base-100 hover:bg-base-300 flex items-center gap-4 tooltip tooltip-bottom" data-tip="Kaze Hikaru">
    <a class="aspect-square overflow-hidden" href="/series/01J76XYCV2MWFSXRV2HN9EJS7P/Kaze-Hikaru" preload>
        <picture><img src="https://temp.compsci88.com/cover/fallback/01J76XYCV2MWFSXRV2HN9EJS7P.jpg" /></picture>
    </a>
    <a class="min-w-0 flex flex-col justify-center pe-4" href="/chapters/01M21XK40MRB7N38TAMZHNFHE1" preload>
        <div class="flex items-center gap-2">
            <div class="flex-1 truncate font-semibold text-lg">Kaze Hikaru</div>
        </div>
        <div class="flex items-center gap-2 opacity-70">
            <span>Volume 34</span>
        </div>
        <div class="flex items-center gap-2 opacity-70">
            <time class="text-datetime" datetime="2026-09-09T01:47:48.628Z">2026-09-09T01:47:48.628Z</time>
        </div>
    </a>
</article>"""

CARD_OLD = """<article class="bg-base-100 hover:bg-base-300 flex items-center gap-4 tooltip tooltip-bottom" data-tip="Old Series">
    <a class="aspect-square overflow-hidden" href="/series/01J76XYD3Q2Q7HYYMB3FSDPSKC/old-series" preload>
        <picture><img src="https://temp.compsci88.com/cover/fallback/01J76XYD3Q2Q7HYYMB3FSDPSKC.jpg" /></picture>
    </a>
    <a class="min-w-0 flex flex-col justify-center pe-4" href="/chapters/01M21S2GA5VM22HSCBM7ZP0RR5" preload>
        <div class="flex items-center gap-2">
            <div class="flex-1 truncate font-semibold text-lg">Old Series</div>
        </div>
        <div class="flex items-center gap-2 opacity-70">
            <span>Chapter 417</span>
        </div>
        <div class="flex items-center gap-2 opacity-70">
            <time class="text-datetime" datetime="2026-09-01T00:00:00.000Z">2026-09-01T00:00:00.000Z</time>
        </div>
    </a>
</article>"""

HOME_HTML = (
    '<div><!-- Latest Updates -->'
    '<section class="bg-base-200 cols-span-1 md:col-span-2">'
    '<span>Latest Updates</span>'
    + CARD_A + CARD_B + CARD_OLD +
    '</section><!-- History --></div>'
)

# ---------------------------------------------------------------------------
# Fixture：系列详情页元数据
# ---------------------------------------------------------------------------
SERIES_HTML = """<html><head>
<title>Who's That Long-Haired Senior? | Weeb Central</title>
<meta property="og:title" content="Who's That Long-Haired Senior? | Weeb Central" />
<meta property="og:image" content="https://temp.compsci88.com/cover/fallback/01JQBT895JGB6HPH5AA1G719DX.jpg" />
<meta property="og:description" content="Read Who's That Long-Haired Senior? Manhwa online for free at Weeb Central" />
</head><body>
<ul>
<li><strong>Author(s): </strong><span><a href="https://weebcentral.com/search?author=Bulgwanhu">Bulgwanhu</a>,</span><span><a href="https://weebcentral.com/search?author=Zhena">Zhena</a>,</span></li>
<li><strong>Status: </strong><a href="https://weebcentral.com/search?included_status=Ongoing">Ongoing</a></li>
<li><strong>Released: </strong><span>2018</span></li>
<li><strong>Tags(s): </strong><span><a href="https://weebcentral.com/search?included_tag=Romance">Romance</a>,</span><span><a href="https://weebcentral.com/search?included_tag=Shoujo">Shoujo</a>,</span></li>
</ul>
</body></html>"""

# ---------------------------------------------------------------------------
# Fixture：全章节列表（2 条，含 Last Read 指示器，验证标题清洗与顺序）
# ---------------------------------------------------------------------------
CHAPTER_ROW = """<div class="flex items-center" x-data="{ new_chapter: checkNewChapter('2026-09-09T01:53:40.306Z') }">
<a href="/chapters/{cid}" class="hover:bg-base-300 flex-1 flex items-center p-2">
<span class="me-2"><img src="/static/images/chapter-badge-official.svg" /></span>
<span class="grow flex items-center gap-2">
<span class="">{title}</span>
<span class="flex gap-1 items-center link-info" x-show="last_read_chapter === '{cid}'">
<svg class="w-4 h-4" aria-hidden="true"></svg><span class="hidden md:inline">Last Read</span>
</span>
</span>
<time class="text-datetime opacity-50" datetime="2026-09-09T01:53:40.306Z">{title}</time>
</a>
</div>"""

FULL_CHAPTER_HTML = (
    CHAPTER_ROW.replace("{cid}", "01M21XXVEJA3FZY6CKHRB3A7HP").replace("{title}", "Episode 100")
    + CHAPTER_ROW.replace("{cid}", "01M21XXEZK6N769Z1CDRJVWNSW").replace("{title}", "Episode 99")
)

# ---------------------------------------------------------------------------
# Fixture：/images 端点片段（含非 lastation.us 图床 + 相对图标不应被计入）
# ---------------------------------------------------------------------------
IMAGES_HTML = """<section id="chapter-images" class="w-full flex-1 flex flex-col pb-4 cursor-pointer">
<img src="https://official.lowee.us/manga/whos-that-longhaired-senior-/0100-001.png" class="max-w-full h-auto mx-auto" alt="Page 1" />
<img src="https://official.lowee.us/manga/whos-that-longhaired-senior-/0100-002.png" class="max-w-full h-auto mx-auto" alt="Page 2" />
<img src="https://official.lowee.us/manga/whos-that-longhaired-senior-/0100-003.png" class="max-w-full h-auto mx-auto" alt="Page 3" />
<img src="/static/images/icon-clock.svg" alt="" />
</section>"""


# ---------------------------------------------------------------------------
# Fixture：/search/data 高级搜索结果（2 条；第 2 条状态为 Complete 覆盖映射兜底）
# ---------------------------------------------------------------------------
SEARCH_HTML = """
<div id="search-results">
  <article class="bg-base-300 flex gap-4 p-4">
    <section class="w-full lg:w-[25%] xl:w-[20%]">
      <a href="https://weebcentral.com/series/01J76XYD3Q2Q7HYYMB3FSDPSKC/Eleceed">
        <article class="hidden lg:block w-full aspect-4/6 overflow-hidden">
          <picture>
            <source srcset="https://temp.compsci88.com/cover/normal/01J76XYD3Q2Q7HYYMB3FSDPSKC.webp" type="image/webp" />
            <img src="https://temp.compsci88.com/cover/fallback/01J76XYD3Q2Q7HYYMB3FSDPSKC.jpg" alt="Eleceed cover" />
          </picture>
        </article>
      </a>
    </section>
    <section class="hidden lg:block lg:w-[75%] xl:w-[80%]">
      <div class="text-lg font-semibold flex items-center gap-1">
        <div class="flex-1 overflow-hidden text-ellipsis leading-normal line-clamp-2">Eleceed</div>
      </div>
      <div class="flex flex-wrap gap-2">
        <div><strong class="opacity-70">Status: </strong><span>Ongoing</span></div>
        <div><strong class="opacity-70">Author(s): </strong><span><a href="/search?author=Son+JeHo" class="link">Son JeHo</a>, <a href="/search?author=Zhena" class="link">Zhena</a></span></div>
        <div class="opacity-70"><strong>Tag(s): </strong><span>Action,</span> <span>Comedy,</span> <span>Shounen</span></div>
      </div>
    </section>
  </article>
  <article class="bg-base-300 flex gap-4 p-4">
    <section class="w-full lg:w-[25%] xl:w-[20%]">
      <a href="https://weebcentral.com/series/01J76XYH1QAAAAAAAAAAAAAAAA/One-Piece---Shokugeki-no-Sanji">
        <article class="hidden lg:block w-full aspect-4/6 overflow-hidden">
          <picture>
            <img src="https://temp.compsci88.com/cover/fallback/01J76XYH1QAAAAAAAAAAAAAAAA.jpg" alt="One Piece cover" />
          </picture>
        </article>
      </a>
    </section>
    <section class="hidden lg:block lg:w-[75%] xl:w-[80%]">
      <div class="text-lg font-semibold flex items-center gap-1">
        <div class="flex-1 overflow-hidden text-ellipsis leading-normal line-clamp-2">One Piece - Shokugeki no Sanji</div>
      </div>
      <div class="flex flex-wrap gap-2">
        <div><strong class="opacity-70">Status: </strong><span>Complete</span></div>
        <div><strong class="opacity-70">Author(s): </strong><span><a href="/search?author=ODA+Eiichiro">ODA Eiichiro</a></span></div>
        <div class="opacity-70"><strong>Tag(s): </strong><span>Adventure,</span> <span>Comedy</span></div>
      </div>
    </section>
  </article>
</div>
"""

class _FakeSelector:
    """按 URL 路径分发 fixture 的 _fetch_selector 替身。"""

    def __init__(self, mapping: dict[str, str]) -> None:
        # mapping 键：home / series / full-chapter-list / images
        self.mapping = mapping
        self.calls: list[str] = []

    def __call__(self, url: str) -> Selector:
        self.calls.append(url)
        if "/search/data" in url:
            html = self.mapping.get("search", "")
        elif "/full-chapter-list" in url:
            html = self.mapping.get("full-chapter-list", "")
        elif "/images" in url:
            html = self.mapping.get("images", "")
        elif "/series/" in url:
            html = self.mapping.get("series", "")
        elif "weebcentral.com" in url:  # 首页 / 列表
            html = self.mapping.get("home", "")
        else:
            html = ""
        return Selector(text=html)


class TestWeebCentralAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.ad = WeebCentralAdapter(http=object())

    # ------------------------------------------------------------------
    def test_card_to_brief(self):
        sel = Selector(text=CARD_A)
        card = sel.xpath("//article")[0]
        brief = self.ad._card_to_brief(card)
        self.assertEqual(brief.source, "weebcentral")
        self.assertEqual(brief.source_comic_id, "01JQBT895JGB6HPH5AA1G719DX")
        self.assertEqual(brief.title, "Who's That Long-Haired Senior?")  # 实体解码
        self.assertEqual(brief.latest_chapter_title, "Episode 99")
        self.assertEqual(
            brief.source_updated_at,
            datetime.fromisoformat("2026-09-09T01:53:27.539+00:00"),
        )
        self.assertTrue(brief.cover_url.startswith("https://temp.compsci88.com/cover/"))
        self.assertEqual(brief.detail_url, "https://weebcentral.com/series/01JQBT895JGB6HPH5AA1G719DX/whos-that-longhaired-senior-")

    # ------------------------------------------------------------------
    def test_search_comics(self):
        """搜索结果卡片 -> ComicBrief：标题/作者/状态/标签/封面/链接；请求参数正确。"""
        fake = _FakeSelector({"search": SEARCH_HTML})
        self.ad._fetch_selector = fake
        items = self.ad.search_comics("eleceed", limit=10)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source, "weebcentral")
        self.assertEqual(first.source_comic_id, "01J76XYD3Q2Q7HYYMB3FSDPSKC")
        self.assertEqual(first.title, "Eleceed")
        self.assertEqual(first.author, "Son JeHo, Zhena")
        self.assertEqual(first.status, "连载")
        self.assertEqual(first.tags, ["Action", "Comedy", "Shounen"])
        self.assertTrue(first.cover_url.endswith("01J76XYD3Q2Q7HYYMB3FSDPSKC.jpg"))
        self.assertEqual(
            first.detail_url,
            "https://weebcentral.com/series/01J76XYD3Q2Q7HYYMB3FSDPSKC/Eleceed",
        )
        # 搜索结果没有「最新章节 / 更新时间」（由详情接口补齐）
        self.assertEqual(first.latest_chapter_title, "")
        self.assertIsNone(first.source_updated_at)
        # 第二条：Status=Complete 也映射为「完结」
        self.assertEqual(items[1].status, "完结")
        self.assertEqual(items[1].tags, ["Adventure", "Comedy"])
        # 端点与参数：走 /search/data（不是 /search/simple），关键词经 urlencode
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("/search/data?", fake.calls[0])
        self.assertIn("text=eleceed", fake.calls[0])
        self.assertIn("display_mode=Full+Display", fake.calls[0])

    def test_search_comics_limit_and_empty_keyword(self):
        self.ad._fetch_selector = _FakeSelector({"search": SEARCH_HTML})
        self.assertEqual(len(self.ad.search_comics("eleceed", limit=1)), 1)
        # 空关键词不请求源站
        fake = _FakeSelector({"search": SEARCH_HTML})
        self.ad._fetch_selector = fake
        self.assertEqual(self.ad.search_comics("   "), [])
        self.assertEqual(fake.calls, [])

    def test_parse_comic_ref(self):
        self.assertEqual(
            self.ad.parse_comic_ref("https://weebcentral.com/series/01J76XYD3Q2Q7HYYMB3FSDPSKC/Eleceed"),
            "01J76XYD3Q2Q7HYYMB3FSDPSKC",
        )
        self.assertEqual(self.ad.parse_comic_ref("01J76XYD3Q2Q7HYYMB3FSDPSKC"), "01J76XYD3Q2Q7HYYMB3FSDPSKC")
        self.assertEqual(self.ad.parse_comic_ref("01j76xyd3q2q7hyymb3fsdpskc"), "01J76XYD3Q2Q7HYYMB3FSDPSKC")
        # 外站链接 / 空 / 不含 ULID 的文本一律拒绝或返回 None
        self.assertIsNone(self.ad.parse_comic_ref("https://mangadex.org/title/abc-def"))
        self.assertIsNone(self.ad.parse_comic_ref(""))
        self.assertIsNone(self.ad.parse_comic_ref("eleceed"))

    def test_fetch_detail_without_detail_url(self):
        """按需导入只给 source_comic_id（无 detail_url）时，自行拼 /series/{ulid}。"""
        fake = _FakeSelector({"series": SERIES_HTML, "full-chapter-list": FULL_CHAPTER_HTML})
        self.ad._fetch_selector = fake
        from comic_crawler.models import ComicBrief

        detail = self.ad.fetch_comic_detail(
            ComicBrief(source="weebcentral", source_comic_id="01J76XYD3Q2Q7HYYMB3FSDPSKC", title="")
        )
        # 未传 detail_url 也能解析到详情（标题来自 SERIES_HTML 的 og:title）
        self.assertEqual(detail.title, "Who's That Long-Haired Senior?")
        self.assertTrue(detail.chapters)
        self.assertTrue(fake.calls)
        self.assertIn("/series/01J76XYD3Q2Q7HYYMB3FSDPSKC", fake.calls[0])

    def test_fetch_list_no_since(self):
        self.ad._fetch_selector = _FakeSelector({"home": HOME_HTML})
        res = self.ad.fetch_comic_list(page=1, since=None)
        self.assertEqual(len(res.items), 3)
        self.assertFalse(res.has_next)
        # page>1 无分页
        self.assertEqual(len(self.ad.fetch_comic_list(page=2, since=None).items), 0)

    def test_fetch_list_since_filter(self):
        self.ad._fetch_selector = _FakeSelector({"home": HOME_HTML})
        # 窗口 = 09-09 00:00Z：CARD_A/B 时间 09-09 保留；CARD_OLD 09-01 被过滤
        since = datetime.fromisoformat("2026-09-09T00:00:00+00:00")
        res = self.ad.fetch_comic_list(page=1, since=since)
        titles = [it.title for it in res.items]
        self.assertIn("Who's That Long-Haired Senior?", titles)
        self.assertIn("Kaze Hikaru", titles)
        self.assertNotIn("Old Series", titles)

    def test_fetch_list_since_naive_local(self):
        """调度器传的 since 是 naive（本机时间）——须经 _utc 归一为 aware UTC 比较。"""
        self.ad._fetch_selector = _FakeSelector({"home": HOME_HTML})
        since = datetime.fromisoformat("2026-09-09T00:00:00")  # naive
        res = self.ad.fetch_comic_list(page=1, since=since)
        self.assertEqual(len(res.items), 2)  # CARD_OLD(09-01) 仍被过滤

    def test_fetch_detail(self):
        fake = _FakeSelector({
            "full-chapter-list": FULL_CHAPTER_HTML,
            "series": SERIES_HTML,
        })
        self.ad._fetch_selector = fake
        from comic_crawler.models import ComicBrief

        brief = ComicBrief(
            source="weebcentral",
            source_comic_id="01JQBT895JGB6HPH5AA1G719DX",
            title="x",
            detail_url="https://weebcentral.com/series/01JQBT895JGB6HPH5AA1G719DX/whos-that-longhaired-senior-",
        )
        detail = self.ad.fetch_comic_detail(brief)
        self.assertEqual(detail.title, "Who's That Long-Haired Senior?")
        self.assertEqual(detail.author, "Bulgwanhu, Zhena")
        self.assertEqual(detail.status, "连载")
        self.assertEqual(detail.tags, ["Romance", "Shoujo"])
        self.assertEqual(detail.category, "Romance")
        self.assertTrue(detail.description.startswith("Read Who's That Long-Haired Senior?"))
        # 全章节列表：标题清洗去 " Last Read"，保持 新->旧
        self.assertEqual(len(detail.chapters), 2)
        self.assertEqual(detail.chapters[0].title, "Episode 100")
        self.assertEqual(detail.chapters[0].source_chapter_id, "01M21XXVEJA3FZY6CKHRB3A7HP")
        self.assertEqual(detail.chapters[1].title, "Episode 99")
        # chapter_no：Episode 100 -> 100；Episode 99 -> 99（新->旧倒序）
        self.assertEqual(detail.chapters[0].chapter_no, 100)
        self.assertEqual(detail.chapters[1].chapter_no, 99)
        # 请求了 full-chapter-list 端点
        self.assertTrue(any("full-chapter-list" in c for c in fake.calls))

    def test_fetch_chapter_pages(self):
        self.ad._fetch_selector = _FakeSelector({"images": IMAGES_HTML})
        from comic_crawler.models import ChapterBrief, ComicDetail

        detail = ComicDetail(source="weebcentral", source_comic_id="s1", title="x", chapters=[])
        chapter = ChapterBrief(
            source="weebcentral", source_comic_id="s1", chapter_no=100,
            title="Episode 100", source_chapter_id="01M21XXVEJA3FZY6CKHRB3A7HP",
        )
        pages = self.ad.fetch_chapter_pages(detail, chapter)
        self.assertEqual(len(pages), 3)  # 相对 /static/ 图标不被计入
        self.assertEqual([p.page_no for p in pages], [1, 2, 3])
        self.assertEqual(
            pages[0].source_url,
            "https://official.lowee.us/manga/whos-that-longhaired-senior-/0100-001.png",
        )

    # ------------------------------------------------------------------
    def test_chapter_no(self):
        self.assertEqual(self.ad._chapter_no("Chapter 417", 0), 417)
        self.assertEqual(self.ad._chapter_no("Episode 99", 0), 99)
        self.assertEqual(self.ad._chapter_no("S2 - Episode 1", 0), 1)
        self.assertEqual(self.ad._chapter_no("Volume 34", 0), 34)
        self.assertEqual(self.ad._chapter_no("Ch 5.5", 0), 55)  # 小数放大 10 倍
        self.assertEqual(self.ad._chapter_no("番外", 7), 10007)  # 无编号高位兜底
        self.assertGreater(self.ad._chapter_no("番外", 7), 10000)

    def test_parse_dt(self):
        self.assertEqual(
            self.ad._parse_dt("2026-09-09T01:53:27.539Z"),
            datetime.fromisoformat("2026-09-09T01:53:27.539+00:00"),
        )
        self.assertIsNone(self.ad._parse_dt(""))
        self.assertIsNone(self.ad._parse_dt("not-a-date"))

    def test_clean_html(self):
        self.assertEqual(self.ad._clean_html("  Who&#39;s  X  "), "Who's X")
        self.assertEqual(self.ad._clean_html(""), "")

    def test_to_no(self):
        self.assertEqual(self.ad._to_no("5"), 5)
        self.assertEqual(self.ad._to_no("5.5"), 55)


if __name__ == "__main__":
    unittest.main()
