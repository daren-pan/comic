"""在漫画 / 再漫画 H5 适配器（学习用途 · 受控样本）。

目标站：https://zaimanhua.com / https://m.zaimanhua.com
逆向结论（2026-09-02 实测确认）：
- PC 网页（www/manhua 域）的 detail API 对《午夜心旋律》(id=71419)
  一律返回空章节（canRead=False / chapterList=[]）—— 与是否登录无关；
- 手机端 H5（m.zaimanhua.com，品牌"再漫画"）与 PC 共用同一内容库，
  其 App 专用 JSON API **匿名即可读**，且服务端按请求头 `Platform` 判定
  下发内容：缺省/`pc` 时章节图片接口返回空页，`h5` 时正常下发；
- 关键 API（均为 GET，需带 `_v=15` 版本参数 + `Platform: h5` 头）：
    - 搜索:  /api/app/v1/search/index?keyword=..&source=0
    - 详情:  /api/app/v1/comic/detail/{id}
    - 章节图: /api/app/v1/comic/chapter/{comic_id}/{chapter_id}
- 图片域 images.zaimanhua.com/w/...，URL 自带 sign/t 防盗链签名，直接可下载。

模型映射：
- 1 部漫画 = 站内一部作品              -> comic 表
- 连载卷中的每个 chapter 入口 = 1 章节  -> chapter 表（只收"连载"卷最新 N 话）
- 每张正文图 = 一页                    -> page 表（source_url 指向签名 CDN 原图）
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

from ..models import (
    ChapterBrief,
    ComicBrief,
    ComicDetail,
    ComicListResult,
    PageInfo,
)
from .base import CrawlerAdapter
from .registry import register

BASE = "https://m.zaimanhua.com"
API_SEARCH = "/api/app/v1/search/index"
API_DETAIL = "/api/app/v1/comic/detail/{cid}"
API_CHAPTER = "/api/app/v1/comic/chapter/{cid}/{chid}"

# 学习用途受控参数
MAX_COMICS = 4          # 搜索/列表最多收录 N 部
MAX_CHAPTERS = 2        # 每部仅收"连载"卷最新 N 话
VOL_TITLE = "连载"      # 只收连载卷，跳过单行本卷（避免章节编号语义混杂）

CN_CHAPTER_RE = re.compile(r"第\s*(\d+)\s*(话|回|章)")
CN_VOL_RE = re.compile(r"第\s*(\d+)\s*卷")

UA_H5 = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)


@register("zaimanhua")
class ZaimanhuaAdapter(CrawlerAdapter):
    """在漫画 / 再漫画 H5（m.zaimanhua.com）适配器（学习用途 · 受控样本）。

    列表语义 = 关键词搜索（source=0 全站搜索）。默认关键词在源码顶部
    SEARCH_KEYWORDS 配置；受控参数确保单次收录量小。
    """

    source_name = "zaimanhua"
    base_url = BASE
    robots_allowed = True  # 学习用途：受控低频请求

    SEARCH_KEYWORDS: tuple[str, ...] = ("午夜心旋律",)  # 受控：仅收录指定作品

    # ------------------------------------------------------------------
    # 列表页：关键词搜索（source=0）-> 前 MAX_COMICS 部
    # ------------------------------------------------------------------
    def fetch_comic_list(self, page: int = 1) -> ComicListResult:
        if page > 1:
            return ComicListResult(items=[], page=page, has_next=False)

        items: list[ComicBrief] = []
        for kw in self.SEARCH_KEYWORDS:
            raw = self._api_get(
                API_SEARCH,
                params={"keyword": kw, "source": 0, "page": 1, "size": 20},
            ) or {}
            for row in (((raw.get("data") or {}).get("list")) or [])[:MAX_COMICS]:
                items.append(self._row_to_brief(row))
        return ComicListResult(items=items, page=page, has_next=False)

    # ------------------------------------------------------------------
    # 详情页：漫画信息 + 连载卷章节（新 -> 旧，取前 MAX_CHAPTERS 话）
    # ------------------------------------------------------------------
    def fetch_comic_detail(self, comic: ComicBrief) -> ComicDetail:
        raw = self._api_get(API_DETAIL.format(cid=comic.source_comic_id)) or {}
        data = raw.get("data") or {}
        info = data.get("data") or {}  # {id,title,chapters:[...]}

        chapters: list[ChapterBrief] = []
        vol = self._pick_serial_vol(info.get("chapters") or [])
        if vol is not None:
            for item in vol["data"][:MAX_CHAPTERS]:
                no = self._chapter_no(item.get("chapter_name") or "")
                if no is None:
                    continue
                chapters.append(
                    ChapterBrief(
                        source=self.source_name,
                        source_comic_id=comic.source_comic_id,
                        chapter_no=no,
                        title=item.get("chapter_name") or item.get("chapter_title") or "",
                        source_chapter_id=str(item.get("chapter_id") or ""),
                        pages_url="",
                    )
                )

        return ComicDetail(
            source=self.source_name,
            source_comic_id=comic.source_comic_id,
            title=comic.title,
            author=comic.author,
            cover_url=comic.cover_url,
            status=self._tag_text(info.get("status")) or comic.status,
            category=self._tag_text(info.get("types")) or comic.category,
            description=info.get("description") or comic.title,
            latest_chapter_title=comic.latest_chapter_title,
            detail_url=f"{BASE}{API_DETAIL.format(cid=comic.source_comic_id)}",
            chapters=chapters,
        )

    # ------------------------------------------------------------------
    # 章节图片：/app/v1/comic/chapter/{cid}/{chid} -> page_url 数组
    # ------------------------------------------------------------------
    def fetch_chapter_pages(self, detail: ComicDetail, chapter: ChapterBrief) -> list[PageInfo]:
        raw = self._api_get(
            API_CHAPTER.format(cid=chapter.source_comic_id, chid=chapter.source_chapter_id)
        ) or {}
        info = ((raw.get("data") or {}).get("data") or {})
        page_urls = info.get("page_url") or []
        return [
            PageInfo(page_no=idx, source_url=url.strip())
            for idx, url in enumerate(page_urls, start=1)
            if url and url.strip()
        ]

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _row_to_brief(self, row: dict[str, Any]) -> ComicBrief:
        """搜索行 -> ComicBrief。字段见 /app/v1/search/index 响应。"""
        cid = str(row.get("id") or row.get("comic_id") or "").strip()
        title = (row.get("title") or "").strip()
        return ComicBrief(
            source=self.source_name,
            source_comic_id=cid,
            title=title,
            author=", ".join(
                [a.strip() for a in str(row.get("authors") or "").split(",") if a.strip()]
            ),
            cover_url=(row.get("cover") or "").strip(),
            status=(row.get("status") or "连载").strip(),
            category=(row.get("types") or "").strip(),
            latest_chapter_title=(
                row.get("last_update_chapter_name")
                or row.get("last_name")
                or ""
            ).strip(),
            detail_url="",
        )

    @staticmethod
    def _pick_serial_vol(chapters: list[dict]) -> dict | None:
        """从 chapters 卷组中选"连载"卷（新章节所在卷）。

        响应结构: [{title:'连载', data:[{chapter_id,chapter_name,...}]},
                   {title:'单行本', data:[...]}]
        """
        for vol in chapters:
            if (vol.get("title") or "") == VOL_TITLE:
                return vol
        # 兜底：取第一个含 data 的卷
        for vol in chapters:
            if vol.get("data"):
                return vol
        return None

    @staticmethod
    def _chapter_no(name: str) -> int | None:
        """'第128话' -> 128；'第09卷'/'其他' 一律跳过（只收主线连载话数）。"""
        m = CN_CHAPTER_RE.search(name or "")
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _tag_text(tags: Any) -> str:
        """[{'tag_name':'爱情'},...] -> '爱情,校园'。"""
        if isinstance(tags, str):
            return tags
        if isinstance(tags, list):
            names = [t.get("tag_name") for t in tags if isinstance(t, dict)]
            return ", ".join(n for n in names if n)
        return ""

    # ------------------------------------------------------------------
    # 请求层：H5 API 需 Platform: h5 头 + _v 版本参数
    # ------------------------------------------------------------------
    def _api_get(self, path: str, params: dict | None = None) -> dict[str, Any] | None:
        url = f"{self.base_url}{path}"
        query = dict(params or {})
        query.setdefault("_v", 15)
        headers = {
            "User-Agent": UA_H5,
            "Platform": "h5",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/pages/comic/page",
            "content-type": "application/json",
        }
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=12.0, follow_redirects=True, headers=headers) as client:
                    resp = client.get(url, params=query)
                    resp.raise_for_status()
                    return resp.json()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(0.8 * (attempt + 1))
        if last_err is not None:
            raise last_err
        return None
