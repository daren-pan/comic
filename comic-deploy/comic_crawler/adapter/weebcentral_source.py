"""Weeb Central 适配器（学习用途 · 受控样本）。

目标站：https://weebcentral.com
逆向结论（2026-09-09 实测确认）：
- 纯服务端渲染 + htmx 局部刷新，**匿名即可读**，无登录、无签名、无付费门禁；
- 列表 = 首页 `<!-- Latest Updates -->` 区块（「最近更新」，约 32 部，无分页），
  卡片含标题 / 系列链接 / 章节链接 / 精确到秒的 ISO 时间戳 / 封面；
  ⚠️ 受控样本：默认 MAX_ITEMS=60；仅测试时可经 `cli run --source weebcentral --limit 1`
  临时只取首页最新 1 部（勿写死为默认值）；
- 系列详情 = `/series/{ulid}/{slug}`，含作者 / 状态 / 标签 / 简介 / 封面；
- 全章节列表 = `/series/{ulid}/full-chapter-list`（htmx 端点，返回全部章节，
  含 `/chapters/{uuid}` + 章节标题 + 每章时间戳），**纯 GET 即可**（无需 HX-Request 头）；
- 章节图 = `/chapters/{uuid}/images?is_prev=False`（htmx 端点，返回完整 `<img>` 列表），
  图片 URL 明文直出（`https://scans.lastation.us/manga/{title}/{no:04d}-{page:03d}.png`）。
  ⚠️ 章节页首屏 HTML 只含第一张图，其余由 Alpine.js `singlePageNavigation` 组件在
  `init()` 里发这个 htmx 请求懒加载——因此适配器**必须**直接请求 `/images` 端点而非解析首屏；
- 图床 `scans.lastation.us`，URL 永久有效、无 Referer/签名限制，**无需覆写
  fetch_source_page_urls**（base 默认返回 None 即可）。
  ⚠️ 图床 `.png` 扩展名但实际字节是 JPEG（magic `ffd8ffe0`）——项目 `_read_image_file`
  按魔数判类型，不受影响，但适配器不能靠扩展名判格式。

模型映射：
- 1 部漫画 = 站内一部系列（series ULID 为 source_comic_id） -> comic 表
- 章节 = full-chapter-list 里每个 `/chapters/{uuid}` 条目      -> chapter 表
  （chapter_no 从标题 "Chapter N"/"Episode N" 解析；无编号用 10000+ 高位兜底）
- 每张图 = /images 端点里一个 `<img src>`                        -> page 表

时间窗口（增量）说明：
- 列表时间基准 = 卡片 `<time datetime="ISO">`（该部最近一次更新的章节时间，精确到秒）；
- 首页「最近更新」区只显示最新的约 32 部（无分页）——增量窗口覆盖「最近 32 部更新」，
  若窗口内更新量超过该区上限会漏掉更早的更新（学习用途受控样本可接受，见 MAX_ITEMS）；
  测试时可用 `cli run --source weebcentral --limit 1` 临时只抓最近 1 部（受控样本）；
- since 为 naive（本机时间）时经 _utc 归一为 aware UTC 再与卡片 ISO 时间比较。

页面转存约定（懒转存）：
- **页面图一律懒转存**（调度器 `_upsert_detail` 入库只登记 URL，cached_status=未转存，
  图片字节不主动下载），由失效巡检 `lazy_transfer` 或用户阅读访问时按需转存；
- 封面（`cover_url`）入库即落盘（ensure_cover_local -> covers/{id}.jpg），非懒转存；
- Weeb Central 图床 URL 永久有效、无签名 → 懒转存直接按登记 URL 下载，
  `_url_expired` 恒 False，无需覆写 `fetch_source_page_urls`（base 默认返回 None）。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

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

logger = logging.getLogger(__name__)

BASE = "https://weebcentral.com"
HOME_PATH = "/"
# htmx 端点（纯 GET 即可，无需 HX-Request 头）
FULL_CHAPTER_LIST = "/series/{sid}/full-chapter-list"
CHAPTER_IMAGES = "/chapters/{cid}/images?is_prev=False"
# 快速搜索（POST /search/simple?location=main，表单字段 text=<query>）
SEARCH_SIMPLE = "/search/simple"

# 系列 ULID：26 位大写 base32
ULID_RE = re.compile(r"[0-9A-Z]{26}")
# 章节标题编号：Chapter 417 / Episode 99 / Ch 5.5 / S2 - Episode 1
CHAPTER_NO_RE = re.compile(r"(?:chapter|episode|ep|ch)\s*(\d+(?:\.\d+)?)", re.I)
NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")
NO_NUM_BASE = 10000  # 无编号章节高位兜底，仿番外 10000+ 防冲突

# 学习用途受控参数
# MAX_ITEMS 为默认列表收录上限（首页最近更新区约 32 部，留余量）；
# 仅测试时可经 `cli run --source weebcentral --limit 1` 临时只抓最近 1 部（受控样本，勿写死为默认值）。
MAX_ITEMS = 60        # 单次列表最多收录条数（首页最近更新区约 32 部，留余量）
MAX_CHAPTERS = 2000   # 单部最多收录章节数（防极端长连载失控）
STATUS_MAP = {"ongoing": "连载", "completed": "完结", "hiatus": "休载", "cancelled": "已取消"}


def _utc(dt: datetime) -> datetime:
    """naive datetime 按「本机时区」解释后转 UTC；aware 原样归一。

    调度器传的 since 取自 sync_log.finished_at（本机 naive），而 WeebCentral 的
    ISO 时间戳是带时区的 aware——直接比较会 TypeError，这里统一成 UTC aware 再比较。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.astimezone(timezone.utc)


@register("weebcentral")
class WeebCentralAdapter(CrawlerAdapter):
    """Weeb Central（weebcentral.com）适配器（学习用途 · 受控样本）。

    列表语义 = 首页「最近更新」（Latest Updates）区块，返回按更新时间倒序的漫画
    （每张卡片的时间戳即该部最近更新的章节时间，精确到秒）。
    """

    source_name = "weebcentral"
    base_url = BASE
    robots_allowed = True  # 学习用途：受控低频请求

    # ------------------------------------------------------------------
    # 列表页：首页「Latest Updates」区块（约 32 部，无分页）
    # ------------------------------------------------------------------
    def fetch_comic_list(self, page: int = 1, since: "datetime | None" = None) -> ComicListResult:
        if page > 1:
            # 首页「最近更新」区无分页：仅第 1 页有内容
            return ComicListResult(items=[], page=page, has_next=False)

        sel = self._fetch_selector(f"{BASE}{HOME_PATH}")
        section = sel.xpath(
            "//span[normalize-space(text())='Latest Updates']/ancestor::section[1]"
        )
        if not section:
            return ComicListResult(items=[], page=page, has_next=False)

        items: list[ComicBrief] = []
        for card in section.xpath(".//article"):
            if len(items) >= MAX_ITEMS:
                break
            brief = self._card_to_brief(card)
            if brief is not None:
                items.append(brief)

        # 增量窗口：只保留源站更新时间 > since 的漫画（首次 since=None 全收）
        if since is not None:
            cutoff = _utc(since)
            items = [
                it for it in items
                if it.source_updated_at is not None and it.source_updated_at > cutoff
            ]
        return ComicListResult(items=items, page=page, has_next=False)

    def _card_to_brief(self, card: Selector) -> ComicBrief | None:
        """Latest Updates 卡片 -> ComicBrief；字段缺失返回 None。"""
        series_href = card.xpath("./a[contains(@href,'/series/')]/@href").get("") or ""
        chapter_href = card.xpath("./a[contains(@href,'/chapters/')]/@href").get("") or ""
        m = ULID_RE.search(series_href)
        if not m:
            return None
        sid = m.group(0)
        title = (
            card.xpath("./a[contains(@href,'/chapters/')]//div[contains(@class,'font-semibold')]/text()")
            .get("")
            .strip()
            or card.xpath("./@data-tip").get("").strip()
        )
        if not title:
            return None
        cover = (
            card.xpath("./a[contains(@href,'/series/')]//img/@src").get("").strip()
        )
        latest_chapter = (
            "".join(
                card.xpath("./a[contains(@href,'/chapters/')]//span/text()").getall()
            ).strip()
        )
        raw_time = (
            card.xpath("./a[contains(@href,'/chapters/')]//time/@datetime").get("").strip()
        )
        return ComicBrief(
            source=self.source_name,
            source_comic_id=sid,
            title=title,
            cover_url=cover,
            latest_chapter_title=latest_chapter,
            detail_url=series_href if series_href.startswith("http") else f"{BASE}{series_href}",
            source_updated_at=self._parse_dt(raw_time),
        )

    # ------------------------------------------------------------------
    # 详情页：系列元数据 + 全章节列表（新 -> 旧）
    # ------------------------------------------------------------------
    def fetch_comic_detail(self, comic: ComicBrief) -> ComicDetail:
        sel = self._fetch_selector(comic.detail_url)
        title = self._series_title(sel) or comic.title
        author = self._series_authors(sel)
        status = self._series_status(sel) or comic.status
        tags = self._series_tags(sel)
        description = self._series_description(sel) or comic.title

        chapters = self._fetch_chapters(comic.source_comic_id)
        return ComicDetail(
            source=self.source_name,
            source_comic_id=comic.source_comic_id,
            title=title,
            author=author,
            cover_url=self._series_cover(sel) or comic.cover_url,
            status=status,
            category=tags[0] if tags else (comic.category or ""),
            tags=tags,
            description=description,
            latest_chapter_title=comic.latest_chapter_title,
            detail_url=comic.detail_url,
            chapters=chapters,
        )

    def _fetch_chapters(self, series_id: str) -> list[ChapterBrief]:
        """全章节列表（htmx 端点）-> ChapterBrief，保持源站「新 -> 旧」顺序。"""
        url = f"{BASE}{FULL_CHAPTER_LIST.format(sid=series_id)}"
        try:
            sel = self._fetch_selector(url)
        except Exception:
            logger.warning("weebcentral 全章节列表获取失败 sid=%s", series_id)
            return []
        chapters: list[ChapterBrief] = []
        for node in sel.xpath("//a[contains(@href,'/chapters/')]"):
            if len(chapters) >= MAX_CHAPTERS:
                break
            href = node.xpath("./@href").get("") or ""
            cm = re.search(r"/chapters/([0-9A-Z]+)", href)
            if not cm:
                continue
            # 章节标题是 grow 容器内的第一个 <span>（后续 span 是 "Last Read"/新章节指示器）
            title = node.xpath(
                "./span[contains(@class,'grow')]/span[1]/text()"
            ).get("")
            if not title:
                title = node.xpath(
                    "string(./span[contains(@class,'grow')])"
                ).get("")
            title = self._clean_html(title)
            if not title:
                continue
            chapters.append(
                ChapterBrief(
                    source=self.source_name,
                    source_comic_id=series_id,
                    chapter_no=self._chapter_no(title, len(chapters)),
                    title=title,
                    source_chapter_id=cm.group(1),
                    pages_url="",
                )
            )
        return chapters

    # ------------------------------------------------------------------
    # 章节图片：/chapters/{uuid}/images（htmx 端点，返回完整 <img> 列表）
    # ------------------------------------------------------------------
    def fetch_chapter_pages(self, detail: ComicDetail, chapter: ChapterBrief) -> list[PageInfo]:
        url = f"{BASE}{CHAPTER_IMAGES.format(cid=chapter.source_chapter_id)}"
        sel = self._fetch_selector(url)
        pages: list[PageInfo] = []
        # ⚠️ 图床域名不固定（scans.lastation.us / official.lowee.us 等），
        # 且章节页首屏只含第一张图——完整列表由 /images 端点返回，全部为
        # 绝对 http(s) 图片 URL，故匹配所有 http(s) img src 而非固定某域。
        for no, src in enumerate(
            sel.xpath("//img[starts-with(@src,'http')]/@src").getall(),
            start=1,
        ):
            src = src.strip()
            if src:
                pages.append(PageInfo(page_no=no, source_url=src))
        return pages

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _series_title(sel: Selector) -> str:
        """og:title '{title} | Weeb Central' -> '{title}'。"""
        raw = sel.xpath("//meta[@property='og:title']/@content").get("") or ""
        return re.sub(r"\s*\|\s*Weeb Central\s*$", "", raw).strip()

    @staticmethod
    def _series_cover(sel: Selector) -> str:
        return (
            sel.xpath("//meta[@property='og:image']/@content").get("").strip()
        )

    @staticmethod
    def _series_description(sel: Selector) -> str:
        return (
            sel.xpath("//meta[@property='og:description']/@content").get("").strip()
        )

    @staticmethod
    def _series_authors(sel: Selector) -> str:
        """Author(s): <a>Son JeHo</a>,<a>Zhena</a> -> 'Son JeHo, Zhena'。"""
        names: list[str] = []
        for node in sel.xpath(
            "//li[contains(., 'Author(s)')]//a[contains(@href,'/search?author=')]"
        ):
            n = node.xpath("string(.)").get().strip()
            if n and n not in names:
                names.append(n)
        return ", ".join(names)

    @staticmethod
    def _series_status(sel: Selector) -> str:
        """Status: <a>Ongoing</a> -> '连载'（映射 STATUS_MAP）。"""
        raw = (
            sel.xpath("//li[contains(., 'Status:')]//a/text()").get("").strip()
        )
        return STATUS_MAP.get(raw.lower(), "")

    @staticmethod
    def _series_tags(sel: Selector) -> list[str]:
        """Tags(s): <a>Action</a>,<a>Comedy</a> -> ['Action','Comedy']（去重去空）。"""
        tags: list[str] = []
        for node in sel.xpath(
            "//li[contains(., 'Tags(s)')]//a[contains(@href,'/search?included_tag=')]"
        ):
            t = node.xpath("string(.)").get().strip()
            if t and t not in tags:
                tags.append(t)
        return tags

    @staticmethod
    def _chapter_no(title: str, idx: int) -> int:
        """章节序号：'Chapter 417' -> 417；'Episode 99' -> 99；'Ch 5.5' -> 55；
        'S2 - Episode 1' -> 1（取 Episode 后的数）；无编号用 10000+ 高位兜底。"""
        m = CHAPTER_NO_RE.search(title)
        if m:
            return WeebCentralAdapter._to_no(m.group(1))
        nums = NUMBER_RE.findall(title)
        if nums:
            return WeebCentralAdapter._to_no(nums[-1])
        return NO_NUM_BASE + idx

    @staticmethod
    def _to_no(raw: str) -> int:
        """'5' -> 5；'5.5' -> 55（放大 10 倍避免与 '6' 撞号，仿 mangadex）。"""
        if "." in raw:
            return int(round(float(raw) * 10))
        return int(raw)

    @staticmethod
    def _parse_dt(raw: str) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean_html(raw: str) -> str:
        """去空白 + 解码 HTML 实体（&#39; -> '）。"""
        text = re.sub(r"\s+", " ", raw or "").strip()
        if "&#" in text:
            text = re.sub(r"&#(\d+);?", lambda m: chr(int(m.group(1))), text)
        return text.strip()

    def _fetch_selector(self, url: str) -> Selector:
        html = self.http.get(url)
        return Selector(text=html)
