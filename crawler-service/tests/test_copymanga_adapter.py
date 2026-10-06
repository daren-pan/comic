"""拷贝漫画适配器解析测试（纯逻辑：mock `_api_get` 返回 fixture，不联网不写库）。

覆盖：
- `_row_to_brief`：列表/搜索行 -> ComicBrief（path_word 作 ID、**封面地址原样保留**、
  作者拼接、日期解析、列表 theme 恒空）；
- `fetch_comic_list`：条数、has_next、page>MAX_PAGE 返回空、**增量按日期比较**；
- `fetch_comic_detail`：标题/作者/状态/标签/分类/简介/封面 + 章节 index+1 连续唯一、
  `groups` 在 results 层级、`is_lock` -> restricted；
- `_pick_group`：优先 default / default 为空时退化为章节最多的组 / 无 groups；
- `_status_of`：已完結 -> 完结，連載中 -> 连载，缺失 -> 空串；
- `fetch_chapter_pages`：contents[].url -> PageInfo（跳空项）；
- `fetch_source_page_urls`：重拉 + 章级缓存（只请求一次）；
- `search_comics` / `_parse_date` / `parse_comic_ref`；
- `images.transfer._host_allowed`：`*.mangafunb.fun` 通配白名单（分片图床）。

运行：PYTHONPATH=src python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.images.transfer import _host_allowed  # noqa: E402
from comic_core.models import ChapterBrief, ComicBrief, ComicDetail  # noqa: E402
from comic_crawler.sources.copymanga.adapter import CopymangaAdapter  # noqa: E402

# ---------------------------------------------------------------------------
# fixture：列表 /api/v3/comics（列表行没有 status；theme 实测恒为空数组）
# ---------------------------------------------------------------------------
LIST_JSON = {
    "total": 55422,
    "limit": 20,
    "offset": 0,
    "list": [
        {
            "name": "電鋸人",
            "path_word": "dianjuren",
            "cover": "https://sd.mangafunb.fun/d/dianjuren/cover/1689304034.jpg.328x422.jpg",
            "author": [{"name": "藤本タツキ", "path_word": "tengbentatsuki"}],
            "author_alias": "藤本タツキ",
            "theme": [],
            "popular": 2541848,
            "datetime_updated": "2026-09-16",
        },
        {
            "name": "海贼王",
            "path_word": "haizeiwang",
            "cover": "https://sx.mangafunb.fun/h/haizeiwang/cover/1.jpg.328x422.jpg",
            "author": [{"name": "尾田荣一郎"}, {"name": "助手"}],
            "theme": [],
            "popular": 100,
            "datetime_updated": "2026-09-01",
        },
        {
            "name": "无日期作品",
            "path_word": "nodate",
            "cover": "",
            "author": [],
            "theme": [],
            "datetime_updated": "",
        },
    ],
}

# ---------------------------------------------------------------------------
# fixture：搜索 /api/v3/search/comic（没有 datetime_updated）
# ---------------------------------------------------------------------------
SEARCH_JSON = {
    "total": 2,
    "limit": 20,
    "offset": 0,
    "list": [
        {
            "name": "電鋸人",
            "alias": "電鋸人,电锯人,链锯人",
            "path_word": "dianjuren",
            "cover": "https://sd.mangafunb.fun/d/dianjuren/cover/1689304034.jpg.328x422.jpg",
            "ban": 0,
            "author": [{"name": "藤本タツキ"}],
            "popular": 458,
        },
        {"name": "無 ID 的行", "path_word": "", "author": []},
    ],
}

# ---------------------------------------------------------------------------
# fixture：详情 /api/v3/comic2/{path_word}（groups 在 results 层级，字段名是 path_word）
# ---------------------------------------------------------------------------
DETAIL_JSON = {
    "is_banned": False,
    "is_lock": False,
    "is_login": False,
    "is_mobile_bind": False,
    "is_vip": False,
    "popular": 2541848,
    "comic": {
        "uuid": "259e688c-f526-11e8-b542-00163e0ca5bd",
        "name": "電鋸人",
        "alias": "電鋸人,电锯人,链锯人",
        "path_word": "dianjuren",
        "free_type": {"display": "免費", "value": 1},
        "restrict": {"value": 0, "display": "一般向(免費)"},
        "region": {"value": 0, "display": "日本"},
        "status": {"value": 1, "display": "已完結"},
        "author": [{"name": "藤本タツキ", "path_word": "tengbentatsuki"}],
        "theme": [{"name": "格鬥", "path_word": "gedou"}, {"name": "奇幻", "path_word": "qihuan"}],
        "brief": "炎拳作者登陸周刊少年JUMP。\r\n被騙得負債累累的少年電次……？！",
        "datetime_updated": "2026-03-26",
        "cover": "https://sd.mangafunb.fun/d/dianjuren/cover/1689304034.jpg.328x422.jpg",
        "last_chapter": {"uuid": "5b5dcf9c", "name": "第03话"},
    },
    "groups": {
        "default": {"path_word": "default", "count": 3, "name": "默認"},
        "tankobon": {"path_word": "tankobon", "count": 9, "name": "单行本"},
        "karapeji": {"path_word": "karapeji", "count": 0, "name": "全彩版"},
    },
}

# ---------------------------------------------------------------------------
# fixture：分组章节 /api/v3/comic/{p}/group/{g}/chapters（index 0 起连续）
# ---------------------------------------------------------------------------
CHAPTERS_JSON = {
    "total": 3,
    "limit": 500,
    "offset": 0,
    "list": [
        {"index": 0, "uuid": "u-1", "name": "第01话", "datetime_created": "2018-12-01"},
        {"index": 1, "uuid": "u-2", "name": "第02话", "datetime_created": "2018-12-10"},
        {"index": 2, "uuid": "u-3", "name": "第03话", "datetime_created": "2018-12-17"},
    ],
}

# ---------------------------------------------------------------------------
# fixture：章节内页 /api/v3/comic/{p}/chapter2/{uuid}（含一个空项，应被跳过）
# ---------------------------------------------------------------------------
CHAPTER_JSON = {
    "is_lock": False,
    "chapter": {
        "uuid": "u-1",
        "name": "第01话",
        "contents": [
            {"url": "https://sd.mangafunb.fun/d/dianjuren/0f432/1.jpg.c1500x.jpg"},
            {"url": ""},
            {"url": "https://sd.mangafunb.fun/d/dianjuren/0f432/2.jpg.c1500x.jpg"},
        ],
    },
}


class _FakeApi:
    """按端点分发的 `_api_get` 替身（记录调用，便于断言请求参数）。"""

    def __init__(self, mapping: dict[str, dict]) -> None:
        self.mapping = mapping
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, params: dict | None = None):
        self.calls.append((path, dict(params or {})))
        if "/group/" in path and path.endswith("/chapters"):
            return self.mapping.get("chapters", {})
        if "/chapter2/" in path:
            return self.mapping.get("chapter", {})
        if path.startswith("/api/v3/comic2/"):
            return self.mapping.get("detail", {})
        if path.startswith("/api/v3/search/"):
            return self.mapping.get("search", {})
        if path.startswith("/api/v3/comics"):
            return self.mapping.get("list", {})
        return {}


class TestCopymangaAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.ad = CopymangaAdapter(http=object())

    # ------------------------------------------------------------------
    def test_row_to_brief(self):
        row = LIST_JSON["list"][0]
        b = self.ad._row_to_brief(row)
        self.assertEqual(b.source, "copymanga")
        self.assertEqual(b.source_comic_id, "dianjuren")  # path_word，不是 uuid
        self.assertEqual(b.title, "電鋸人")
        self.assertEqual(b.author, "藤本タツキ")
        # 封面地址原样保留（**不剥** `.328x422.jpg` 缩略后缀）
        self.assertEqual(
            b.cover_url,
            "https://sd.mangafunb.fun/d/dianjuren/cover/1689304034.jpg.328x422.jpg",
        )
        self.assertEqual(b.detail_url, "https://copy4000.com/comic/dianjuren")
        self.assertEqual(b.status, "连载")  # 列表不给状态，默认连载（详情覆盖）
        self.assertEqual(b.tags, [])        # 列表 theme 实测恒为空
        self.assertEqual(b.source_updated_at, datetime(2026, 9, 16))

    # ------------------------------------------------------------------
    def test_fetch_list_and_request_params(self):
        fake = _FakeApi({"list": LIST_JSON})
        self.ad._api_get = fake
        res = self.ad.fetch_comic_list(page=1, since=None)
        self.assertEqual(len(res.items), 3)
        # 全量模式（since=None）：total 远大于本页条数 → 仍可继续翻页（由 MAX_PAGE 安全阀兜底）
        self.assertTrue(res.has_next)
        # 请求参数走「最近更新」倒序
        path, params = fake.calls[0]
        self.assertEqual(path, "/api/v3/comics")
        self.assertEqual(params["ordering"], "-datetime_updated")
        self.assertEqual(params["limit"], 20)
        self.assertEqual(params["offset"], 0)

    def test_fetch_list_paginate_to_window_edge(self):
        """窗口内更新超一页时应继续翻页；翻到某页全部越过 since 才停（对齐 mangadex）。"""
        def row(name: str, pw: str, day: str) -> dict:
            return {
                "name": name,
                "path_word": pw,
                "cover": "",
                "author": [],
                "datetime_updated": day,
            }

        # 第 1 页（offset=0）：09-16 当天（窗口内）；第 2 页（offset=20）：09-01（窗口外）
        pages = {
            0: {"total": 60, "list": [row("A", "a", "2026-09-16"), row("B", "b", "2026-09-16")]},
            20: {"total": 60, "list": [row("C", "c", "2026-09-01"), row("D", "d", "2026-09-01")]},
        }

        def fake(path, params=None):
            return pages.get((params or {}).get("offset", 0), {"total": 60, "list": []})

        self.ad._api_get = fake
        since = datetime(2026, 9, 10)
        r1 = self.ad.fetch_comic_list(page=1, since=since)
        self.assertEqual([it.title for it in r1.items], ["A", "B"])
        self.assertTrue(r1.has_next)                 # 窗口内可能还有 → 继续翻
        r2 = self.ad.fetch_comic_list(page=2, since=since)
        self.assertEqual(r2.items, [])               # 本页全在窗口外 → 无收集
        self.assertFalse(r2.has_next)                # 已越过 since 边界 → 停，不翻第 3 页

    def test_fetch_list_since_window_by_date(self):
        """源站时间只到「天」，增量按**日期**比较（用 > 会漏掉当天更新）。"""
        self.ad._api_get = _FakeApi({"list": LIST_JSON})
        # since = 当天 23:59（比源站的 00:00 晚）——按日期比较仍应保留当天作品
        res = self.ad.fetch_comic_list(page=1, since=datetime(2026, 9, 16, 23, 59))
        titles = [it.title for it in res.items]
        self.assertIn("電鋸人", titles)          # 09-16 当天，保留
        self.assertNotIn("海贼王", titles)        # 09-01 早于窗口
        self.assertNotIn("无日期作品", titles)     # 无日期 -> 不参与
        # 带时区的 since 也不能炸
        from datetime import timezone

        res2 = self.ad.fetch_comic_list(
            page=1, since=datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
        )
        self.assertEqual([it.title for it in res2.items], ["電鋸人"])

    # ------------------------------------------------------------------
    def test_fetch_detail(self):
        fake = _FakeApi({"detail": DETAIL_JSON, "chapters": CHAPTERS_JSON})
        self.ad._api_get = fake
        d = self.ad.fetch_comic_detail(
            ComicBrief(source="copymanga", source_comic_id="dianjuren", title="電鋸人")
        )
        self.assertEqual(d.title, "電鋸人")
        self.assertEqual(d.author, "藤本タツキ")
        self.assertEqual(d.status, "完结")            # 已完結 -> 完结
        self.assertEqual(d.tags, ["格鬥", "奇幻"])
        self.assertEqual(d.category, "格鬥")
        self.assertFalse(d.restricted)               # is_lock=False
        self.assertEqual(d.latest_chapter_title, "第03话")
        self.assertIn("\n", d.description)           # \r\n 归一为 \n
        self.assertNotIn("\r", d.description)
        self.assertEqual(
            d.cover_url,
            "https://sd.mangafunb.fun/d/dianjuren/cover/1689304034.jpg.328x422.jpg",
        )
        # 章节：index 0 起 -> chapter_no = index + 1，连续且唯一
        self.assertEqual([c.chapter_no for c in d.chapters], [1, 2, 3])
        self.assertEqual([c.title for c in d.chapters], ["第01话", "第02话", "第03话"])
        self.assertEqual(d.chapters[0].source_chapter_id, "u-1")
        # 只走 default 组（tankobon 有 9 章也不收）
        self.assertTrue(any("/group/default/chapters" in p for p, _ in fake.calls))

    def test_fetch_detail_restricted_by_is_lock(self):
        locked = dict(DETAIL_JSON)
        locked["is_lock"] = True
        self.ad._api_get = _FakeApi({"detail": locked, "chapters": CHAPTERS_JSON})
        d = self.ad.fetch_comic_detail(
            ComicBrief(source="copymanga", source_comic_id="x", title="")
        )
        self.assertTrue(d.restricted)

    def test_fetch_detail_falls_back_to_detail_fields(self):
        """按需导入只给 path_word（brief 无 title/author/cover）时用详情补全。"""
        self.ad._api_get = _FakeApi({"detail": DETAIL_JSON, "chapters": {"list": []}})
        d = self.ad.fetch_comic_detail(
            ComicBrief(source="copymanga", source_comic_id="dianjuren", title="")
        )
        self.assertEqual(d.title, "電鋸人")
        self.assertEqual(d.author, "藤本タツキ")
        self.assertTrue(d.cover_url.endswith("1689304034.jpg.328x422.jpg"))
        self.assertEqual(d.chapters, [])

    def test_fetch_chapters_pagination(self):
        """total 大于单页时按 offset 继续拉，直到达到 total。"""
        page1 = {"total": 3, "list": CHAPTERS_JSON["list"][:2]}
        page2 = {"total": 3, "list": CHAPTERS_JSON["list"][2:]}

        class _Paged:
            def __init__(self):
                self.calls = []

            def __call__(self, path, params=None):
                self.calls.append(dict(params or {}))
                if "/chapter2/" in path:
                    return {}
                return page1 if params.get("offset") == 0 else page2

        f = _Paged()
        self.ad._api_get = f
        got = self.ad._fetch_chapters("dianjuren", "default")
        self.assertEqual([c.chapter_no for c in got], [1, 2, 3])
        self.assertEqual([c["offset"] for c in f.calls], [0, 2])  # 第二页从 offset=2 起

    # ------------------------------------------------------------------
    def test_fetch_chapter_pages(self):
        self.ad._api_get = _FakeApi({"chapter": CHAPTER_JSON})
        detail = ComicDetail(source="copymanga", source_comic_id="dianjuren", title="x")
        chapter = ChapterBrief(
            source="copymanga", source_comic_id="dianjuren", chapter_no=1,
            title="第01话", source_chapter_id="u-1",
        )
        pages = self.ad.fetch_chapter_pages(detail, chapter)
        self.assertEqual([p.page_no for p in pages], [1, 2])  # 空 url 项被跳过
        self.assertTrue(pages[0].source_url.endswith(".c1500x.jpg"))  # 正文图不剥后缀
        self.assertEqual(pages[0].cached_status, "未转存")

    def test_fetch_source_page_urls_cached(self):
        fake = _FakeApi({"chapter": CHAPTER_JSON})
        self.ad._api_get = fake
        first = self.ad.fetch_source_page_urls("dianjuren", "u-1")
        self.assertEqual(len(first), 2)
        second = self.ad.fetch_source_page_urls("dianjuren", "u-1")
        self.assertIs(second, first)                    # 命中章级缓存（同对象）
        self.assertEqual(len(fake.calls), 1)            # 只请求源站一次

    # ------------------------------------------------------------------
    def test_pick_group(self):
        self.assertEqual(self.ad._pick_group(DETAIL_JSON["groups"]), "default")
        # default 章节数为 0 -> 退化为章节最多的组
        g = {
            "default": {"path_word": "default", "count": 0},
            "tankobon": {"path_word": "tankobon", "count": 9},
        }
        self.assertEqual(self.ad._pick_group(g), "tankobon")
        self.assertEqual(self.ad._pick_group({}), "")
        self.assertEqual(self.ad._pick_group(None), "")

    def test_status_of(self):
        self.assertEqual(self.ad._status_of({"status": {"display": "已完結"}}), "完结")
        self.assertEqual(self.ad._status_of({"status": {"display": "連載中"}}), "连载")
        self.assertEqual(self.ad._status_of({"status": {"display": "连载"}}), "连载")
        self.assertEqual(self.ad._status_of({}), "")
        self.assertEqual(self.ad._status_of({"status": None}), "")

    def test_parse_date(self):
        self.assertEqual(self.ad._parse_date("2026-09-16"), datetime(2026, 9, 16))
        self.assertIsNone(self.ad._parse_date(""))
        self.assertIsNone(self.ad._parse_date(None))
        self.assertIsNone(self.ad._parse_date("2026-13-45"))  # 非法月日
        self.assertIsNone(self.ad._parse_date("not-a-date"))

    def test_cover_url_kept_as_is(self):
        """封面地址**原样入库**，一个字都不改（2026-09-18 决定，撤销"剥后缀取原图"）。

        原因：那个 `.328x422.jpg` 后缀**不是**可替换的 resize 参数 —— 实测图床上只有
        「基址」与「精确 `.328x422.jpg`」两个真实文件，`.500x643` / `.c1500x` 等一律 404。
        而剥离逻辑一旦取错扩展名就会整张 404（`.jpeg`/`.png` 封面曾被写成 `.jpg`），
        收益不稳、风险实在，故不再改写。
        """
        # 详情路径：brief 无 cover 时用详情字段，且原样保留
        self.ad._api_get = _FakeApi({"detail": DETAIL_JSON, "chapters": {"list": []}})
        d = self.ad.fetch_comic_detail(
            ComicBrief(source="copymanga", source_comic_id="dianjuren", title="")
        )
        self.assertEqual(
            d.cover_url, DETAIL_JSON["comic"]["cover"]
        )  # 与源站字段逐字节相同

        # 列表路径：同样原样保留
        b = self.ad._row_to_brief(LIST_JSON["list"][0])
        self.assertEqual(b.cover_url, LIST_JSON["list"][0]["cover"])

        # 各种扩展名都不受影响（此前 `.jpeg`/`.png` 会被误改）
        for raw in (
            "https://sq.mangafunb.fun/q/qingwanlewo/cover/1788335868.jpeg.328x422.jpg",
            "https://sc.mangafunb.fun/c/cadws/cover/1789615473.png.328x422.jpg",
            "https://sd.mangafunb.fun/d/x/1.webp.328x422.jpg",
            "https://sd.mangafunb.fun/d/x/1.jpg",
            "",
        ):
            row = dict(LIST_JSON["list"][0], cover=raw)
            self.assertEqual(self.ad._row_to_brief(row).cover_url, raw)

        # brief 已带 cover 时优先用 brief 的（导入链路），同样不改写
        given = "https://se.mangafunb.fun/e/x/cover/1788672090.jpeg.328x422.jpg"
        d2 = self.ad.fetch_comic_detail(
            ComicBrief(
                source="copymanga", source_comic_id="x", title="t", cover_url=given
            )
        )
        self.assertEqual(d2.cover_url, given)

    def test_search_comics(self):
        fake = _FakeApi({"search": SEARCH_JSON})
        self.ad._api_get = fake
        items = self.ad.search_comics("电锯人", limit=10)
        self.assertEqual(len(items), 1)                  # 无 path_word 的行被丢掉
        self.assertEqual(items[0].source_comic_id, "dianjuren")
        self.assertEqual(items[0].title, "電鋸人")
        self.assertIsNone(items[0].source_updated_at)    # 搜索行没有更新时间
        path, params = fake.calls[0]
        self.assertEqual(path, "/api/v3/search/comic")
        self.assertEqual(params["q"], "电锯人")
        # 空关键词不请求源站
        fake2 = _FakeApi({"search": SEARCH_JSON})
        self.ad._api_get = fake2
        self.assertEqual(self.ad.search_comics("   "), [])
        self.assertEqual(fake2.calls, [])

    def test_parse_comic_ref(self):
        f = self.ad.parse_comic_ref
        self.assertEqual(f("https://copy4000.com/comic/dianjuren"), "dianjuren")
        self.assertEqual(f("https://copy4000.com/comic/dianjuren?foo=1"), "dianjuren")
        self.assertEqual(f("dianjuren"), "dianjuren")
        self.assertEqual(f("19du"), "19du")
        self.assertEqual(f("HUANGNVZIYIZHANFANGDEKUANGHUA"), "HUANGNVZIYIZHANFANGDEKUANGHUA")
        # 外站链接 / 首页 / 作者页 / 空 / 过短 一律 None
        self.assertIsNone(f("https://mangadex.org/title/abc"))
        self.assertIsNone(f("https://copy4000.com/"))
        self.assertIsNone(f("https://copy4000.com/author/x/comics"))
        self.assertIsNone(f(""))
        self.assertIsNone(f("a"))
        self.assertIsNone(f("有 空格 的字符串"))

    # ------------------------------------------------------------------
    def test_host_allowed_wildcard(self):
        """`*.mangafunb.fun` 通配：放行一级子域，拒绝多级子域与伪装域名。"""
        ad = self.ad
        self.assertTrue(_host_allowed("https://sd.mangafunb.fun/a.jpg", ad))
        self.assertTrue(_host_allowed("https://sa.mangafunb.fun/a.jpg", ad))
        self.assertTrue(_host_allowed("https://s0.mangafunb.fun/a.jpg", ad))
        self.assertFalse(_host_allowed("https://a.b.mangafunb.fun/a.jpg", ad))   # 多一级
        self.assertFalse(_host_allowed("https://mangafunb.fun/a.jpg", ad))       # 无子域
        self.assertFalse(_host_allowed("https://evilmangafunb.fun/a.jpg", ad))   # 无点分隔
        self.assertFalse(_host_allowed("https://example.com/a.jpg", ad))
        self.assertFalse(_host_allowed("http://127.0.0.1/a.jpg", ad))            # 内网
        self.assertFalse(_host_allowed("not-a-url", ad))
        # 未声明 image_hosts 的适配器不校验（沿用既有约定）
        self.assertTrue(_host_allowed("https://example.com/a.jpg", object()))
        # 精确域名仍然工作（zaimanhua 那种写法）
        exact = type("A", (), {"image_hosts": {"images.zaimanhua.com"}})()
        self.assertTrue(_host_allowed("https://images.zaimanhua.com/a.jpg", exact))
        self.assertFalse(_host_allowed("https://x.images.zaimanhua.com/a.jpg", exact))


if __name__ == "__main__":
    unittest.main()
