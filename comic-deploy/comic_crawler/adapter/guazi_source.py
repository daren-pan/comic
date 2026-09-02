"""瓜子漫画适配器（学习用途 · 受控样本）。

目标站：https://www.guazimanhua.com/
- 典型中文漫画站：服务端渲染（PHP）、多部漫画按"最近更新"排序 —— 正是
  本项目 demo 源模拟的真实场景，用于验证"典型中文站接入"的适配器写法；
- robots.txt 仅屏蔽 AI 爬虫（GPTBot/ClaudeBot 等），普通 UA 抓取不受限；
- 学习用途边界（架构文档 §6.2）：本地技术演示、不公开发布。受控参数：
  MAX_COMICS（首页最近更新取前 N 部）+ MAX_CHAPTERS（每部仅收最新 N 话），
  样本量小、可一键按 source='guazi' 清理。

模型映射：
- 1 部漫画 = 站内一部作品           -> comic 表
- 每个章节入口 = 一个章节            -> chapter 表
- 每张正文图 = 一页                  -> page 表（source_url 指向 CDN 原图）
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

BASE = "https://www.guazimanhua.com"
HOME_PATH = "/"
COMIC_ID_RE = re.compile(r"comic\.php\?id=(\d+)")
CHAPTER_ID_RE = re.compile(r"chapter\.php\?id=(\d+)")
# 第48话 / 第 48 话
CN_NUM_RE = re.compile(r"第\s*(\d+)\s*话")
PLAIN_NUM_RE = re.compile(r"(\d+)")
STATUS_RE = re.compile(r"状态为(连载|完结)")

# ---- 学习用途受控参数（改大即扩大收录，务必确认仍属受限样本） ----
MAX_COMICS = 4        # 首页"最近更新"取前 N 部
MAX_CHAPTERS = 3      # 每部仅收录最新 N 话
BANNED_TEXTS = ("开始阅读", "去阅读", "最新更新")  # 章节列表里的功能链接


@register("guazi")
class GuaziAdapter(CrawlerAdapter):
    """真实中文源站：瓜子漫画（学习用途 · 受控样本）。"""

    source_name = "guazi"
    base_url = BASE
    robots_allowed = True  # robots.txt 仅屏蔽 AI 爬虫，普通 UA 不受限

    # ------------------------------------------------------------------
    # 列表页：首页"最近更新"区块 -> 前 MAX_COMICS 部
    # ------------------------------------------------------------------
    def fetch_comic_list(self, page: int = 1) -> ComicListResult:
        if page > 1:
            return ComicListResult(items=[], page=page, has_next=False)

        sel = self._fetch_selector(HOME_PATH)
        items: list[ComicBrief] = []
        for card in sel.xpath(
            "//section[contains(@class,'latest-section')]"
            "//article[contains(@class,'update-card')]"
        )[:MAX_COMICS]:
            a = card.xpath(".//h3/a")
            href = a.xpath("./@href").get("") or ""
            m = COMIC_ID_RE.search(href)
            if not m:
                continue
            img = card.xpath(".//img[contains(@class,'cover')]")
            title = self._clean_title(a.xpath("./text()").get(""))
            if not title:
                continue
            items.append(
                ComicBrief(
                    source=self.source_name,
                    source_comic_id=m.group(1),
                    title=title,
                    cover_url=img.xpath("./@src").get("").strip(),
                    category=(
                        card.xpath(
                            "string(.//*[contains(@class,'update-tags')])"
                        ).get("").strip()
                    ),
                    latest_chapter_title=(
                        card.xpath(
                            "string(.//*[contains(@class,'update-chapter')])"
                        ).get("").strip()
                    ),
                    detail_url=href if href.startswith("http") else f"{BASE}{href}",
                )
            )
        return ComicListResult(items=items, page=page, has_next=False)

    # ------------------------------------------------------------------
    # 详情页：简介 + 章节列表（新 -> 旧，取前 MAX_CHAPTERS 话）
    # ------------------------------------------------------------------
    def fetch_comic_detail(self, comic: ComicBrief) -> ComicDetail:
        sel = self._fetch_selector(comic.detail_url)

        # 简介 / 分类 / 状态
        desc = sel.xpath("string(//*[contains(@class,'mobile-comic-desc')])").get(
            ""
        ).strip()
        category = (
            sel.xpath("string(//*[contains(@class,'mobile-comic-tags')])").get("").strip()
            or comic.category
        )
        status = "连载"
        st = STATUS_RE.search("".join(sel.xpath("//text()").getall()))
        if st:
            status = st.group(1)

        # 章节：优先取 [data-chapter-list]（全部章节，新->旧）
        nodes = sel.xpath(
            "//*[@data-chapter-list]/a[contains(@href,'chapter.php?id=')]"
        )
        if not nodes:
            nodes = sel.xpath(
                "//a[contains(@href,'chapter.php?id=')]"
                "[normalize-space(text())][not(contains(.,'开始阅读'))]"
            )

        # 主线章节优先（标题非 [番外] 开头），番外仅作补充，避免最新更新
        # 恰为番外时整部收录的都是花絮
        main_nodes, extra_nodes = [], []
        for node in nodes:
            title = self._clean_title(node.xpath("string(./text())").get(""))
            if not title or any(b in title for b in BANNED_TEXTS):
                continue
            (extra_nodes if title.startswith("[番外]") else main_nodes).append(
                (node, title)
            )
        picked = (main_nodes[:MAX_CHAPTERS] + extra_nodes)[:MAX_CHAPTERS]

        chapters: list[ChapterBrief] = []
        for idx, (node, title) in enumerate(picked):
            href = node.xpath("./@href").get("") or ""
            cm = CHAPTER_ID_RE.search(href)
            if not cm:
                continue
            chapters.append(
                ChapterBrief(
                    source=self.source_name,
                    source_comic_id=comic.source_comic_id,
                    chapter_no=self._chapter_no(title, idx),
                    title=title,
                    source_chapter_id=cm.group(1),
                    pages_url=href if href.startswith("http") else f"{BASE}{href}",
                )
            )

        return ComicDetail(
            source=self.source_name,
            source_comic_id=comic.source_comic_id,
            title=comic.title,
            author=comic.author,
            cover_url=comic.cover_url,
            status=status,
            category=category,
            description=desc or comic.title,
            latest_chapter_title=comic.latest_chapter_title,
            detail_url=comic.detail_url,
            chapters=chapters,
        )

    # ------------------------------------------------------------------
    # 章节页：CDN 正文图（img.guazicdn.com/.../chapters/...）
    # ------------------------------------------------------------------
    def fetch_chapter_pages(self, detail: ComicDetail, chapter: ChapterBrief) -> list[PageInfo]:
        sel = self._fetch_selector(chapter.pages_url)

        pages: list[PageInfo] = []
        for no, src in enumerate(
            sel.xpath(
                "//img[contains(@src,'guazicdn.com')][contains(@src,'/chapters/')]/@src"
            ).getall(),
            start=1,
        ):
            src = src.strip()
            if src:
                pages.append(PageInfo(page_no=no, source_url=src))
        return pages

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _chapter_no(self, title: str, idx: int) -> int:
        """章节序号：'第48话' -> 48；[番外]/无数字章节用 10000+ 高位防冲突。

        番外不参与主线编号（不与 '第N话' 撞号），且排在大号区最前。
        """
        if title.startswith("[番外]"):
            return 10000 + idx
        m = CN_NUM_RE.search(title)
        if m:
            return int(m.group(1))
        m = PLAIN_NUM_RE.search(title)
        if m:
            return int(m.group(1))
        return 10000 + idx

    @staticmethod
    def _clean_title(raw: str) -> str:
        """清洗标题：去空白 + 解码 HTML 实体（&#40; -> (）。"""
        title = (raw or "").strip()
        if "&#" in title:
            title = re.sub(
                r"&#(\d+);?", lambda m: chr(int(m.group(1))), title
            )
        return title.strip()

    def _fetch_selector(self, path: str) -> Selector:
        url = path if path.startswith("http") else f"{BASE}{path}"
        html = self.http.get(url)
        return Selector(text=html)
