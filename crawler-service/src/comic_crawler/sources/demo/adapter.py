"""示例源站适配器 —— 演示如何接入一个新源站。

本适配器解析 fixtures/ 下的 HTML 文件（模拟源站页面，离线可跑）。
真实接入时只需：
1. 把 base_url 换成目标源站域名；
2. 按目标源站真实 DOM 调整本文件中的 XPath 即可。

演示的 HTML 结构（见 fixtures/*.html）：
- 列表页：div.comic-list > div.comic-item（标题/作者/状态/分类/更新）
- 详情页：h1 标题 + p.desc 简介 + div.chapter-list > a（章节）
- 章节页：div.pages > img（分页图片）
"""

from __future__ import annotations

import re
from pathlib import Path

from parsel import Selector

from ...models import (
    ChapterBrief,
    ComicBrief,
    ComicDetail,
    ComicListResult,
    PageInfo,
)
from ..base import CrawlerAdapter
from ..registry import register

# 样例 HTML 与适配器同目录（fixtures/）——不再依赖仓库根，源包自洽可迁移
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@register("demo_source")
class DemoSourceAdapter(CrawlerAdapter):
    """演示源站：解析本地 fixture HTML，验证全链路（调度→抓取→解析→去重→入库）。

    子类化复用：覆盖 source_name / LIST_FILE / DETAIL_PREFIX 即可
    接入一个结构相同的新源（见 demo_source_b.py）。
    """

    source_name = "demo_source"
    base_url = str(FIXTURES_DIR)
    robots_allowed = True  # 演示源站允许抓取

    LIST_FILE = "demo_list.html"        # 列表页 fixture 文件名
    DETAIL_PREFIX = "demo_detail_"      # 详情页 fixture 文件名前缀

    # ------------------------------------------------------------------
    # 列表页：div.comic-item 内解析
    # ------------------------------------------------------------------
    def fetch_comic_list(self, page: int = 1, since: "datetime | None" = None) -> ComicListResult:  # noqa: ARG001
        if page > 1:
            # 演示源站只有一页数据：第 2 页起返回空，模拟翻页结束
            return ComicListResult(items=[], page=page, has_next=False)

        html = self.http.get(f"{self.base_url}/{self.LIST_FILE}")
        sel = Selector(text=html)

        items: list[ComicBrief] = []
        for node in sel.xpath("//div[contains(@class,'comic-item')]"):
            title_node = node.xpath(".//a[contains(@class,'title')]")
            title = title_node.xpath("./text()").get("").strip()
            href = title_node.xpath("./@href").get("")
            # 从 href 提取源站漫画 ID，如 /comic/1001.html -> 1001
            comic_id = self._extract_id(href) or title
            items.append(
                ComicBrief(
                    source=self.source_name,
                    source_comic_id=comic_id,
                    title=title,
                    author=node.xpath(".//span[contains(@class,'author')]/text()").get("").strip(),
                    status=(
                        "完结"
                        if "完结" in node.xpath(".//span[contains(@class,'status')]/text()").get("")
                        else "连载"
                    ),
                    category=node.xpath(".//span[contains(@class,'category')]/text()").get("").strip(),
                    latest_chapter_title=node.xpath(".//span[contains(@class,'update')]/text()").get("").strip(),
                    detail_url=f"{self.base_url}/{self.DETAIL_PREFIX}{comic_id}.html",
                )
            )

        has_next = bool(sel.xpath("//div[contains(@class,'pagination')]//a[contains(text(),'下一页')]"))
        return ComicListResult(items=items, page=page, has_next=has_next)

    # ------------------------------------------------------------------
    # 详情页：简介 + 章节列表
    # ------------------------------------------------------------------
    def fetch_comic_detail(self, comic: ComicBrief) -> ComicDetail:
        html = self.http.get(comic.detail_url or f"{self.base_url}/{self.DETAIL_PREFIX}{comic.source_comic_id}.html")
        sel = Selector(text=html)

        chapters: list[ChapterBrief] = []
        for node in sel.xpath("//div[contains(@class,'chapter-list')]//a"):
            chapter_title = node.xpath("./text()").get("").strip()
            href = node.xpath("./@href").get("")
            chapter_id = self._extract_id(href) or str(len(chapters) + 1)
            chapters.append(
                ChapterBrief(
                    source=self.source_name,
                    source_comic_id=comic.source_comic_id,
                    chapter_no=int(node.xpath("./@data-no").get() or len(chapters) + 1),
                    title=chapter_title,
                    source_chapter_id=chapter_id,
                    pages_url=f"{self.base_url}/demo_chapter.html",
                )
            )

        return ComicDetail(
            source=self.source_name,
            source_comic_id=comic.source_comic_id,
            title=sel.xpath("//h1/text()").get("").strip() or comic.title,
            author=sel.xpath("//p[contains(@class,'author')]/text()").get("").strip() or comic.author,
            cover_url=sel.xpath("//img[contains(@class,'cover')]/@src").get("") or "",
            category=comic.category,
            status=comic.status,
            description=sel.xpath("//p[contains(@class,'desc')]/text()").get("").strip(),
            latest_chapter_title=comic.latest_chapter_title,
            detail_url=comic.detail_url,
            chapters=chapters,
        )

    # ------------------------------------------------------------------
    # 章节页：分页图片
    # ------------------------------------------------------------------
    def fetch_chapter_pages(self, detail: ComicDetail, chapter: ChapterBrief) -> list[PageInfo]:
        html = self.http.get(chapter.pages_url)
        sel = Selector(text=html)

        pages: list[PageInfo] = []
        for no, node in enumerate(sel.xpath("//div[contains(@class,'pages')]//img"), start=1):
            pages.append(
                PageInfo(
                    page_no=no,
                    source_url=node.xpath("./@src").get("").strip(),
                )
            )
        return pages

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_id(href: str) -> str | None:
        """从 /comic/1001.html 或 /read/1001/1080.html 提取数字 ID。"""
        if not href:
            return None
        matches = re.findall(r"\d+", href)
        return matches[-1] if matches else None
