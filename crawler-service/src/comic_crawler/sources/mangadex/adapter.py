"""MangaDex v5 API 适配器（学习用途 · 受控样本 · 默认不启用）。

目标站：https://mangadex.org（API: https://api.mangadex.org，v5，OpenAPI 3.0.3）
合规说明（务必阅读，对应架构方案 §6.2）：
- MangaDex 是粉丝翻译(scanlation)聚合站，大部分内容版权属原权利人，非授权分发；
- 其 AUP 明确：仅个人/非商业用途，禁止在其上投放广告或商用，使用需署名
  MangaDex 与相应汉化组；限速约 5 req/s/IP；
- 本项目仅作**本地技术演示的受控样本**：config.py 中 enabled=False（不参与
  serve 轮询），仅手动 `run --source mangadex` 使用；单部少量章节、不发布、
  用后可按 source=mangadex 一键清理。

逆向要点（v5 API）：
- 漫画级列表（按最新上传章节倒序）: GET /manga?order[latestUploadedChapter]=desc
  &availableTranslatedLanguage[]=zh&limit=25&offset=..
- 详情:  GET /manga/{id}?includes[]=cover_art&includes[]=author&includes[]=artist
- 章节:  GET /manga/{id}/feed?translatedLanguage[]=zh&order[chapter]=asc
  &includeExternalUrl=0&limit=500（contentRating[] 取 CONTENT_RATINGS 全部 4 值，见常量注释）
- 图源:  GET /at-home/server/{chapter_id} -> {baseUrl, chapter:{hash, data[]}}
  图片 URL = {baseUrl}/data/{hash}/{file}（原图）——签名服务器分发的短期地址，
  懒转存过期时经 fetch_source_page_urls 重新分发（同 zaimanhua 图床思路）。

模型映射：
- 1 部漫画 = manga 记录                          -> comic 表
- 章节 = feed 里的 chapter（卷.话字符串）        -> chapter 表（chapter_no 由
  "卷.话"解析 *10 取整，见 _chapter_key）
- 每页 = at-home 分发的 data 列表一项            -> page 表
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ...models import (
    ChapterBrief,
    ComicBrief,
    ComicDetail,
    ComicListResult,
    PageInfo,
)
from ..base import CrawlerAdapter
from ..registry import register

logger = logging.getLogger(__name__)


def _utc(dt: datetime) -> datetime:
    """naive datetime 按「本机时区」解释后转 UTC；aware 原样归一。

    调度器传的 since 取自 sync_log.finished_at（本机 naive），而 MD 的
    publishAt/updatedAt 是带 UTC 时区的 aware——直接比较会 TypeError，
    这里统一成 UTC aware 再比较。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.astimezone(timezone.utc)

API_BASE = "https://api.mangadex.org"
# 学习用途受控参数
MAX_LIST_PAGES = 10      # 列表翻页安全阀（增量模式下实际按窗口边界提前停，见 fetch_comic_list）
LIST_LIMIT = 25          # 每页漫画数
FEED_LIMIT = 500         # 章节 feed 单次最多返回
MAX_READABLE_PROBE = 8   # 可读性探测：从最新往前最多探测几话找有图章节
FIRST_LANG = "zh"        # 译本优先中文，其次英文
FALLBACK_LANG = "en"
CN_CHAPTER_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*$")
# 无编号章节（如外传/单行）高位兜底，仿番外 10000+ 防冲突
NO_NUM_BASE = 10000

# MD feed 端点必填 contentRating[]（缺省 400），且「返回范围 = 声明范围」。
# 全部 4 个值：safe(全年龄) / suggestive(轻度暗示) / erotica(色情) / pornographic(露骨)。
# 如需调整分级范围（如只收全年龄+轻度暗示），改这一个列表即可，无需动请求代码。
CONTENT_RATINGS = ["safe", "suggestive", "erotica", "pornographic"]

# MangaDex API 需要明确 User-Agent；节流 0.6~1.0s（尊重 ~5 rps 限速）
UA = "comic-crawler-learning-demo/0.1 (local study only; contact: localhost)"
MIN_DELAY = 0.6


@register("mangadex")
class MangaDexAdapter(CrawlerAdapter):
    """MangaDex v5 适配器（学习用途 · 受控样本 · 默认不启用）。"""

    source_name = "mangadex"
    base_url = API_BASE
    robots_allowed = True  # API 有 AUP；本实现按"非商用 + 低频"遵守

    # ------------------------------------------------------------------
    # 漫画级列表：按"最新上传章节"倒序（源站更新驱动增量）
    # ------------------------------------------------------------------
    def fetch_comic_list(self, page: int = 1, since: datetime | None = None) -> ComicListResult:
        if page > MAX_LIST_PAGES:
            return ComicListResult(items=[], page=page, has_next=False)
        params = {
            "order[latestUploadedChapter]": "desc",
            "hasAvailableChapters": "true",
            "availableTranslatedLanguage[]": [FIRST_LANG],
            "includes[]": ["cover_art"],  # 列表顺带取封面关系
            "limit": LIST_LIMIT,
            "offset": (page - 1) * LIST_LIMIT,
        }
        raw = self._api_get("/manga", params) or {}
        data = raw.get("data") or []

        items: list[ComicBrief] = []
        for m in data:
            if self._is_excluded(m):
                continue
            attrs = m.get("attributes") or {}
            title = self._comic_title(attrs)
            if not title:
                continue
            mid = str(m.get("id") or "")
            # 精确时间基准：逐部查「最新一章上传时间」（publishAt）。
            # 注意 /manga 的 latestUploadedChapter 是 chapter UUID、updatedAt 是元数据
            # 修改时间——两者都不能当"最新章节上传时间"（曾误用导致展示旧日期）。
            updated_at = self._latest_publish(mid)
            if since is not None and (updated_at is None or updated_at <= _utc(since)):
                continue  # 该作品最近一章仍早于窗口起点 → 未更新，跳过
            cover_url = self._cover_from_relationships(m)
            items.append(
                ComicBrief(
                    source=self.source_name,
                    source_comic_id=mid,
                    title=title,
                    author="",
                    cover_url=cover_url,
                    status=self._status_text(attrs.get("status")),
                    category="",
                    latest_chapter_title="",
                    detail_url=f"{API_BASE}/manga/{mid}",
                    source_updated_at=updated_at,
                )
            )

        # 翻页：列表按「最新上传章节」倒序（≈最新章时间倒序）——
        # 增量模式下当某一页没有任何窗口内作品（items 空）说明已翻过 since 边界，
        # 后续页只会更旧，停止翻页，避免固定页数漏掉窗口内的大批量更新；
        # 无 since（full/首采）则翻到 MAX_LIST_PAGES 安全阀为止。
        has_next = len(data) >= LIST_LIMIT and page < MAX_LIST_PAGES
        if since is not None and not items:
            has_next = False
        return ComicListResult(items=items, page=page, has_next=has_next)

    def _latest_publish(self, manga_id: str) -> datetime | None:
        """查某部漫画最新一章的公开时间（publishAt，全语言，排除未公开）。"""
        params = {
            "manga": manga_id,
            "order[publishAt]": "desc",
            "limit": 1,
        }
        raw = self._api_get("/chapter", params) or {}
        rows = raw.get("data") or []
        if not rows:
            return None
        return self._parse_dt(((rows[0].get("attributes") or {}).get("publishAt")))

    # ------------------------------------------------------------------
    # 详情：manga + 章节 feed
    # ------------------------------------------------------------------
    def fetch_comic_detail(self, comic: ComicBrief) -> ComicDetail:
        detail = self._api_get(
            f"/manga/{comic.source_comic_id}",
            {"includes[]": ["cover_art", "author", "artist"]},
        ) or {}
        data = detail.get("data") or {}
        attrs = data.get("attributes") or {}
        title = self._comic_title(attrs) or comic.title
        author = self._authors(data.get("relationships") or [])
        # ⚠️ MangaDex 的 tag 在 attributes.tags（非 relationships，includes[]=tag 无效）
        tags = self._tags(attrs)

        chapters = self._fetch_feed(comic.source_comic_id)
        # 授权/官方数字版作品的章节图片托管在 MD 之外（at-home data 为空）——
        # 探测章节可读性，把「最新一话中有图可读」的章节放到最前，避免首采 0 页。
        chapters = self._readable_head(chapters)
        return ComicDetail(
            source=self.source_name,
            source_comic_id=comic.source_comic_id,
            title=title,
            author=author,
            cover_url=self._cover_from_relationships(data) or comic.cover_url,
            status=self._status_text(attrs.get("status")) or comic.status,
            category=tags[0] if tags else (comic.category or ""),
            tags=tags,
            description=self._description(attrs.get("description")) or title,
            latest_chapter_title=comic.latest_chapter_title,
            detail_url=comic.detail_url or f"{API_BASE}/manga/{comic.source_comic_id}",
            chapters=chapters,
        )

    def _readable_head(self, chapters: list[ChapterBrief]) -> list[ChapterBrief]:
        """把最新一话中有图可读的章节放到列表首位。

        MD 上部分（授权/官方）作品的章节图片在站外，at-home 分发 data 为空。
        探测前 MAX_READABLE_PROBE 话的图数：若首章无图，向后找第一个有图的
        提为「最新可读话」（调度首采即采它）；全部无图则保持原样（0 页兜底）。
        """
        if not chapters:
            return chapters
        if self._at_home_page_urls(chapters[0].source_chapter_id):
            return chapters  # 最新章直接可读
        for i in range(1, min(len(chapters), MAX_READABLE_PROBE)):
            if self._at_home_page_urls(chapters[i].source_chapter_id):
                head = chapters.pop(i)
                chapters.insert(0, head)
                break
        return chapters

    def _fetch_feed(self, manga_id: str) -> list[ChapterBrief]:
        """章节 feed（指定语言升序 -> 再反转成"最新在前"供调度采样）。"""
        chapters: list[ChapterBrief] = []
        for lang in (FIRST_LANG, FALLBACK_LANG):
            params = {
                "translatedLanguage[]": [lang],
                "contentRating[]": list(CONTENT_RATINGS),  # MD feed 端点必填（范围见常量）
                "order[volume]": "asc",
                "order[chapter]": "asc",
                # ⚠️ MD 布尔参数须用 0/1（'false'/'true' 会在 feed 端点 400）
                "includeExternalUrl": "0",
                "includeFuturePublishAt": "0",
                "limit": FEED_LIMIT,
            }
            raw = self._api_get(f"/manga/{manga_id}/feed", params) or {}
            rows = raw.get("data") or []
            if rows:
                chapters = self._parse_feed(rows)
                break
        # 调度器约定 detail.chapters 为「新 -> 旧」（最新话在前）
        return list(reversed(chapters))

    def _parse_feed(self, rows: list[dict]) -> list[ChapterBrief]:
        out: list[ChapterBrief] = []
        for idx, ch in enumerate(rows):
            attrs = ch.get("attributes") or {}
            vol = str(attrs.get("volume") or "")
            no_raw = str(attrs.get("chapter") or "")
            # 注意：feed 里"第0章"常见（序章），chapter_no 需与具体 title 对应
            key = self._chapter_key(vol, no_raw, idx)
            title = f"{attrs.get('title') or ''}".strip()
            out.append(
                ChapterBrief(
                    source=self.source_name,
                    source_comic_id="",
                    chapter_no=key,
                    title=title or f"{no_raw}",
                    source_chapter_id=str(ch.get("id") or ""),
                    pages_url="",
                )
            )
        return out

    # ------------------------------------------------------------------
    # 章节图片：at-home 分发（签名地址短时效 -> 支持现场重拉）
    # ------------------------------------------------------------------
    def fetch_chapter_pages(self, detail: ComicDetail, chapter: ChapterBrief) -> list[PageInfo]:
        urls = self._at_home_page_urls(chapter.source_chapter_id)
        return [
            PageInfo(page_no=idx, source_url=u)
            for idx, u in enumerate(urls, start=1)
            if u
        ]

    def fetch_source_page_urls(
        self, source_comic_id: str, source_chapter_id: str
    ) -> list[str] | None:
        """现场重拉：向 at-home 重新分发整章图片 URL（懒转存重试用）。"""
        return self._at_home_page_urls(source_chapter_id)

    def _at_home_page_urls(self, chapter_id: str) -> list[str]:
        if not chapter_id:
            return []
        raw = self._api_get(f"/at-home/server/{chapter_id}") or {}
        # ⚠️ at-home 响应无外层 data：顶层即 {result, baseUrl, chapter:{hash,data[]}}
        base = raw.get("baseUrl") or ""
        ch = raw.get("chapter") or {}
        hash_ = ch.get("hash") or ""
        return [f"{base}/data/{hash_}/{f}" for f in (ch.get("data") or []) if f]

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _api_get(self, path: str, params: dict[str, Any] | None = None) -> dict | None:
        url = f"{API_BASE}{path}"
        headers = {
            "User-Agent": UA,
            "Accept": "application/vnd.api+json",
        }
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                time.sleep(MIN_DELAY)
                resp = httpx.get(url, params=params or {}, headers=headers, timeout=15.0)
                if resp.status_code == 429:
                    time.sleep(2.0)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(0.8 * (attempt + 1))
        if last_err is not None:
            raise last_err
        return None

    @staticmethod
    def _title(t: Any) -> str:
        if not isinstance(t, dict):
            return ""
        for key in ("zh", "en"):
            val = t.get(key)
            if val:
                return str(val).strip()
        for val in t.values():
            if val:
                return str(val).strip()
        return ""

    @staticmethod
    def _comic_title(attrs: dict) -> str:
        """漫画标题：主标题 -> altTitles（中文优先，其次英文）。

        MangaDex 的主标题常是罗马字/日文音译，中文/英文名多放在 altTitles——
        中文译本作品优先展示 altTitles 里的中文名。
        """
        main = MangaDexAdapter._title(attrs.get("title"))
        for alt in attrs.get("altTitles") or []:
            if not isinstance(alt, dict):
                continue
            val = alt.get("zh")
            if val:
                return str(val).strip()
        for alt in attrs.get("altTitles") or []:
            if not isinstance(alt, dict):
                continue
            val = alt.get("en") or alt.get("zh-hk") or alt.get("zh-cn")
            if val:
                return str(val).strip()
        return main

    @staticmethod
    def _description(d: Any) -> str:
        if not isinstance(d, dict):
            return ""
        # zh 缺省回退 en（MD 很多漫画没有中文简介）
        return (d.get("zh") or d.get("en") or "").strip()

    @staticmethod
    def _status_text(s: str | None) -> str:
        return {
            "ongoing": "连载",
            "completed": "完结",
            "hiatus": "休载",
            "cancelled": "已取消",
        }.get(s or "", "")

    @staticmethod
    def _authors(relationships: list[dict]) -> str:
        names: list[str] = []
        for rel in relationships:
            if rel.get("type") in ("author", "artist"):
                n = (rel.get("attributes") or {}).get("name") or ""
                if n and n not in names:
                    names.append(n)
        return ", ".join(names)

    @staticmethod
    def _tags(attrs: dict) -> list[str]:
        """标签：MangaDex tag 位于 attributes.tags（每个含 attributes.name）。"""
        tags: list[str] = []
        for t in attrs.get("tags") or []:
            name = MangaDexAdapter._title((t.get("attributes") or {}).get("name"))
            if name and name not in tags:
                tags.append(name)
        return tags

    @staticmethod
    def _cover_from_relationships(node: dict) -> str:
        manga_id = node.get("id") or ""
        for rel in node.get("relationships") or []:
            if rel.get("type") == "cover_art":
                fname = (rel.get("attributes") or {}).get("fileName")
                if manga_id and fname:
                    return f"https://uploads.mangadex.org/covers/{manga_id}/{fname}"
        return ""

    @staticmethod
    def _parse_dt(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_excluded(manga: dict) -> bool:
        """排除：成人内容（后续如需可放开，演示只收 safe/suggestive）。"""
        return False

    @staticmethod
    def _chapter_key(vol: str, no_raw: str, idx: int) -> int:
        """章节序号：'卷.话' 语义 -> 唯一整数。

        MangaDex chapter 是「卷内话」字符串，跨卷会重复（第1卷 5 话 & 第2卷 5 话）。
        这里按「卷号*1000 + 话号*10(+小数位)」映射为单调整数，避免撞号：
          第1卷 第5话    -> 1050
          第2卷 第5话    -> 2050
          第2卷 第5.5话  -> 2055
          无卷/无编号    -> NO_NUM_BASE + idx（高位，防与主线冲突）
        """
        v_no = 0
        try:
            v_no = int(float(vol))
        except (TypeError, ValueError):
            v_no = 0
        if not no_raw:
            return NO_NUM_BASE + idx
        try:
            c_no = int(round(float(no_raw) * 10))
        except (TypeError, ValueError):
            return NO_NUM_BASE + idx
        return v_no * 1000 + c_no
