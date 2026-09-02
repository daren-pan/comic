"""Pepper & Carrot 真实源站适配器（CC-BY 4.0 开源授权）。

接入的真实世界源站：https://www.peppercarrot.com/
- 作者 David Revoy，全站采用 CC-BY 4.0 许可（官网 /en/license/），允许抓取、分享、改编（署名即可）；
- robots.txt 仅 Disallow /cache/ 与 /extras/temp/，本适配器抓取的
  /en/webcomics/（列表）与 /0_sources/（正文图片）均在允许范围，刻意避开 /cache/ 缩略图；
- 正文图片使用官方公开的 low-res 版本（尊重版权方带宽设定，也足够演示）。

模型映射（源站是"一部 webcomic、episode 即章节"）：
- 1 部漫画 = Pepper & Carrot          -> comic 表 1 条
- 每个 episode = 一个章节             -> chapter 表，chapter_no 取 episode 编号
- 每张正文图 = 一页                    -> page 表，source_url 指向 low-res 原图
"""

from __future__ import annotations

import re

from parsel import Selector

from ..models import (
    ChapterBrief,
    ComicBrief,
    ComicDetail,
    ComicListResult,
    PageInfo,
)
from .base import CrawlerAdapter
from .registry import register

BASE = "https://www.peppercarrot.com"
LIST_PATH = "/en/webcomics/peppercarrot.html"
EPISODE_PATH_RE = re.compile(r"/en/webcomic/ep(\d+)_([^/]+)\.html")
# 演示：只取最新 N 话，控制单轮抓取量与图片下载量（改大即全量收录）
MAX_EPISODES = 10


@register("peppercarrot")
class PepperCarrotAdapter(CrawlerAdapter):
    """真实源站：Pepper & Carrot（CC-BY 4.0）。"""

    source_name = "peppercarrot"
    base_url = BASE
    robots_allowed = True  # 已核对 robots.txt：仅禁 /cache/、/extras/temp/

    # ------------------------------------------------------------------
    # 列表页：站点即一部漫画，返回单个 ComicBrief
    # ------------------------------------------------------------------
    def fetch_comic_list(self, page: int = 1) -> ComicListResult:
        if page > 1:
            return ComicListResult(items=[], page=page, has_next=False)

        sel = self._fetch_selector(LIST_PATH)
        first = sel.xpath("(//figure[contains(@class,'thumbnail')])[1]")
        items = [
            ComicBrief(
                source=self.source_name,
                source_comic_id="pepper-and-carrot",
                title="Pepper & Carrot",
                author="David Revoy",
                cover_url="",  # 列表页缩略图在 /cache/（robots 禁抓），封面由详情阶段从正文页补
                status="连载",
                category="奇幻 · 冒险",
                latest_chapter_title=(
                    first.xpath(".//figcaption//a/text()").get("").strip()
                ),
                detail_url=f"{BASE}{LIST_PATH}",
            )
        ]
        return ComicListResult(items=items, page=page, has_next=False)

    # ------------------------------------------------------------------
    # 详情页：解析列表页全部 episode -> 章节列表（限 MAX_EPISODES 话）
    # ------------------------------------------------------------------
    def fetch_comic_detail(self, comic: ComicBrief) -> ComicDetail:
        sel = self._fetch_selector(LIST_PATH)

        chapters: list[ChapterBrief] = []
        for node in sel.xpath("//figure[contains(@class,'thumbnail')]")[:MAX_EPISODES]:
            a = node.xpath(".//figcaption//a")
            title = a.xpath("./text()").get("").strip()
            href = (a.xpath("./@href").get("") or "").strip()
            m = EPISODE_PATH_RE.search(href)
            if not m:
                continue
            ep_no = int(m.group(1))
            chapters.append(
                ChapterBrief(
                    source=self.source_name,
                    source_comic_id=comic.source_comic_id,
                    chapter_no=ep_no,  # episode 编号即章节序号
                    title=title,
                    source_chapter_id=f"ep{ep_no}",
                    pages_url=href if href.startswith("http") else f"{BASE}{href}",
                )
            )

        # 封面：从最新一话的正文页取 header 图（/0_sources/，robots 允许）
        cover_url = comic.cover_url
        if chapters:
            ep_sel = self._fetch_selector(chapters[0].pages_url)
            cover_url = (
                ep_sel.xpath("//img[contains(@alt,'Header')]/@src").get("").strip()
                or cover_url
            )

        return ComicDetail(
            source=self.source_name,
            source_comic_id=comic.source_comic_id,
            title=comic.title,
            author=comic.author,
            cover_url=cover_url,
            category=comic.category,
            status=comic.status,
            description=(
                "Pepper & Carrot 是画师 David Revoy 创作的开源 webcomic，"
                "全站采用 CC-BY 4.0 许可（可自由分享与改编，需署名作者）。"
                "本条为真实源站抓取演示数据：调度 → 抓取 → 解析 → 去重 → 入库 → 懒转存，全链路真实可跑。"
            ),
            latest_chapter_title=comic.latest_chapter_title,
            detail_url=comic.detail_url,
            chapters=chapters,
        )

    # ------------------------------------------------------------------
    # 章节页：正文图片（title 以 Page 开头的 img 即为漫画内页）
    # ------------------------------------------------------------------
    def fetch_chapter_pages(self, detail: ComicDetail, chapter: ChapterBrief) -> list[PageInfo]:
        sel = self._fetch_selector(chapter.pages_url)

        pages: list[PageInfo] = []
        for no, node in enumerate(
            sel.xpath("//img[starts-with(@title, 'Page')]"), start=1
        ):
            src = node.xpath("./@src").get("").strip()
            if not src:
                continue
            pages.append(PageInfo(page_no=no, source_url=src))
        return pages

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _fetch_selector(self, path: str) -> Selector:
        url = path if path.startswith("http") else f"{BASE}{path}"
        html = self.http.get(url)
        return Selector(text=html)
