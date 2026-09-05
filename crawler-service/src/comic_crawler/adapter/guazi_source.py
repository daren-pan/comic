"""瓜子漫画适配器（学习用途 · 受控样本）。

目标站：https://www.guazimanhua.com/
- 典型中文漫画站：服务端渲染（PHP）、多部漫画按"最近更新"排序 —— 正是
  本项目 demo 源模拟的真实场景，用于验证"典型中文站接入"的适配器写法；
- robots.txt 仅屏蔽 AI 爬虫（GPTBot/ClaudeBot 等），普通 UA 抓取不受限；
- 学习用途边界（架构文档 §6.2）：本地技术演示、不公开发布。受控参数：
  MAX_PAGES（"今天更新"列表最多扫描页数，每页 30 部）+ MAX_CHAPTERS（每部仅收最新 N 话），
  样本量小、可一键按 source='guazi' 清理。列表入口为 update.php?date={档位}，
  抓取增量时间窗口内更新的全部漫画（翻页补齐，避免只取首页固定 N 部遗漏）。

时间窗口（增量）实现（方案A · 按天）：
- 瓜子列表卡片（article.mobile-update-card）不暴露时间戳，只有详情页
  <p class="desc"> 里的「更新时间：YYYY-MM-DD」（精确到日）。
- 站点 date 参数仅提供固定档位 today/yesterday/week/month/all，无自定义区间。
- 因此增量窗口粒度只能是「日」：
  1) 首次（since=None）：date=today 全量抓当天更新的所有漫画；
  2) 之后增量（since 非空）：按 since 与今天的天数差选 date 档位（撑大窗口保证不漏），
     再对每部进详情页解析「更新时间」，仅保留 updated_date >= since_day 的（窗口精确到日）。
- 只在 since 非空时才进详情页拿时间做过滤（首次不额外请求，省流量）。

模型映射：
- 1 部漫画 = 站内一部作品           -> comic 表
- 每个章节入口 = 一个章节            -> chapter 表
- 每张正文图 = 一页                  -> page 表（source_url 指向 CDN 原图）
"""

from __future__ import annotations

import re
from datetime import date, datetime

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
# "最近更新"列表页：按时间范围展示全站更新，每页 30 部，可翻页
# date 参数为站点固定档位：all / today / yesterday / week / month
UPDATE_PATH = "/update.php"
UPDATE_DATE_ALL = "all"
UPDATE_DATE_DAY = "today"
UPDATE_DATE_WEEK = "week"
UPDATE_DATE_MONTH = "month"
COMIC_ID_RE = re.compile(r"comic\.php\?id=(\d+)")
CHAPTER_ID_RE = re.compile(r"chapter\.php\?id=(\d+)")
# 第48话 / 第 48 话
CN_NUM_RE = re.compile(r"第\s*(\d+)\s*话")
PLAIN_NUM_RE = re.compile(r"(\d+)")
STATUS_RE = re.compile(r"状态为(连载|完结)")

# ---- 学习用途受控参数（改大即扩大收录，务必确认仍属受限样本） ----
MAX_PAGES = 5         # "今天更新"最多扫描页数（每页 30 部，防失控；当日更新超出则截断）
MAX_CHAPTERS = 3      # 每部仅收录最新 N 话
BANNED_TEXTS = ("开始阅读", "去阅读", "最新更新")  # 章节列表里的功能链接


@register("guazi")
class GuaziAdapter(CrawlerAdapter):
    """真实中文源站：瓜子漫画（学习用途 · 受控样本）。"""

    source_name = "guazi"
    base_url = BASE
    robots_allowed = True  # robots.txt 仅屏蔽 AI 爬虫，普通 UA 不受限

    # ------------------------------------------------------------------
    # 列表页：抓增量时间窗口内的全部漫画（update.php?date={档位}，每页 30 部，翻页补齐）
    # ------------------------------------------------------------------
    def fetch_comic_list(self, page: int = 1, since: "datetime | None" = None) -> ComicListResult:
        if page > MAX_PAGES:
            return ComicListResult(items=[], page=page, has_next=False)

        since_day = self._since_day(since)  # 增量窗口起点（仅按天），None=首次/全量
        # date 档位：首次用 today；之后按 since 与今天的天数差撑大窗口（today/week/month/all）
        date_param = self._date_param(since_day)

        # update.php 的更新卡片：article.mobile-update-card
        # （与首页 section.latest-section > article.update-card 结构不同）
        sel = self._fetch_selector(f"{UPDATE_PATH}?date={date_param}&page={page}")
        items: list[ComicBrief] = []
        for card in sel.xpath("//article[contains(@class,'mobile-update-card')]"):
            href = card.xpath("./h2/a/@href").get("") or ""
            m = COMIC_ID_RE.search(href)
            if not m:
                continue
            p = card.xpath(".//p/a")
            chapter_href = p.xpath("./@href").get("") or ""
            items.append(
                ComicBrief(
                    source=self.source_name,
                    source_comic_id=m.group(1),
                    title=self._clean_title(card.xpath("./h2/a/text()").get("")),
                    cover_url=(
                        card.xpath("./a[contains(@class,'mobile-update-cover')]/img/@src")
                        .get("")
                        .strip()
                    ),
                    category=(
                        card.xpath("string(./small)").get("").strip()
                    ),
                    latest_chapter_title=(
                        self._clean_title(p.xpath("./text()").get(""))
                    ),
                    detail_url=f"{BASE}/comic.php?id={m.group(1)}",
                )
            )
        # 去重（同一部可能因多次更新出现在列表）
        seen: set[str] = set()
        uniq: list[ComicBrief] = []
        for it in items:
            if it.source_comic_id in seen:
                continue
            seen.add(it.source_comic_id)
            uniq.append(it)
        # 增量窗口（按天）：仅保留"源站更新时间 >= since_day"的漫画。
        # 只在 since 非空时进详情页解析「更新时间」，首次不额外请求（省流量）。
        if since_day is not None:
            uniq = [it for it in uniq if self._passes_window(it, since_day)]
        # has_next：下一页是否仍有更新卡片（当天更新可能多页，须翻到底保证完整）
        has_next = self._next_page_has_items(page + 1, date_param) if uniq else False
        return ComicListResult(items=uniq, page=page, has_next=has_next)

    @staticmethod
    def _since_day(since: "datetime | None") -> "date | None":
        """增量窗口起点对齐到日（日期部分）；None=首次/全量，不按天过滤。"""
        if since is None:
            return None
        return since.date()

    @staticmethod
    def _date_param(since_day: "date | None") -> str:
        """按 since 与今天的天数差选站点 date 档位（撑大窗口避免漏抓，再用日级过滤砍回）。"""
        if since_day is None:
            return UPDATE_DATE_DAY  # 首次
        diff = (date.today() - since_day).days
        if diff <= 1:
            return UPDATE_DATE_DAY
        if diff <= 6:
            return UPDATE_DATE_WEEK
        if diff <= 31:
            return UPDATE_DATE_MONTH
        return UPDATE_DATE_ALL

    def _passes_window(self, brief: ComicBrief, since_day: "date") -> bool:
        """进详情页解析「更新时间：YYYY-MM-DD」，仅保留 >= since_day 的漫画。

        解析失败（页面无该字段）时放行，避免误漏；具体日期用于窗口精确到日。
        """
        try:
            sel = self._fetch_selector(brief.detail_url)
        except Exception:
            return True  # 详情页异常不阻断窗口（后续 upsert 幂等兜底）
        updated = self._extract_update_date(sel)
        if updated is None:
            return True  # 拿不到时间自然无法过滤 → 放行（幂等消化冗余）
        return updated >= since_day

    @staticmethod
    def _extract_update_date(sel: Selector) -> "date | None":
        """解析详情页「更新时间：YYYY-MM-DD」（元信息 <p class='desc'>）。

        注意：详情页可能有多个 <p class='desc'>（首个是简介，其余是更新时间/
        最新章节/状态等元信息），须遍历全部节点拼接后再匹配，否则只取到简介。
        """
        nodes = sel.xpath("//p[contains(@class,'desc')]")
        joined = "\n".join(n.xpath("string(.)").get() or "" for n in nodes)
        m = re.search(r"更新时间[：:]\s*(\d{4}-\d{2}-\d{2})", joined)
        if not m:
            return None
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            return None

    def _next_page_has_items(self, page: int, date_param: str) -> bool:
        """探测下一页是否还有内容，避免依赖'下一页链接'（今天只有 19 部时链接仍存在但第 2 页为空）。"""
        if page > MAX_PAGES:
            return False
        sel = self._fetch_selector(f"{UPDATE_PATH}?date={date_param}&page={page}")
        return bool(sel.xpath("//article[contains(@class,'mobile-update-card')]"))

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
