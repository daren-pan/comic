"""在漫画 / 再漫画 H5 适配器（学习用途 · 受控样本）。

目标站：https://zaimanhua.com / https://m.zaimanhua.com
逆向结论（2026-09-02 实测确认）：
- PC 网页（www/manhua 域）的 detail API 对《午夜心旋律》(id=71419)
  一律返回空章节（canRead=False / chapterList=[]）—— 与是否登录无关；
- 手机端 H5（m.zaimanhua.com，品牌"再漫画"）与 PC 共用同一内容库，
  其 App 专用 JSON API **匿名即可读**，且服务端按请求头 `Platform` 判定
  下发内容：缺省/`pc` 时章节图片接口返回空页，`h5` 时正常下发；
- 关键 API（均为 GET，需带 `_v=15` 版本参数 + `Platform: h5` 头）：
    - 最近更新列表: /api/app/v1/comic/update/list/0/{page}   # 首页"最近更新"标签
    - 详情:        /api/app/v1/comic/detail/{id}
    - 章节图:      /api/app/v1/comic/chapter/{comic_id}/{chapter_id}
    - （备用）搜索: /api/app/v1/search/index?keyword=..&source=0
- 图片域 images.zaimanhua.com/w/...，URL 自带 sign/t 防盗链签名，直接可下载。

模型映射：
- 1 部漫画 = 站内一部作品              -> comic 表
- 连载卷中的每个 chapter 入口 = 1 章节  -> chapter 表（只收"连载"卷全部话，跳过单行本卷）
- 每张正文图 = 一页                    -> page 表（source_url 指向签名 CDN 原图）
"""

from __future__ import annotations

import re
import time
from datetime import datetime
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

BASE = "https://m.zaimanhua.com"
API_UPDATE_LIST = "/api/app/v1/comic/update/list/0/{page}"  # 首页"最近更新"标签
API_DETAIL = "/api/app/v1/comic/detail/{cid}"
API_CHAPTER = "/api/app/v1/comic/chapter/{cid}/{chid}"
API_SEARCH = "/api/app/v1/search/index"  # 备用：关键词搜索（未用于默认列表）

# 学习用途受控参数
MAX_PAGE = 1            # "最近更新"最多扫描页数（每页 20 部）
VOL_TITLE = "连载"      # 只收连载卷，跳过单行本卷（避免章节编号语义混杂）

# 标准话数（整话），如 第128话 / 09章；浮点小节（第153.5话）由 chapter_order 兜底，
# 不再试图用正则解析（否则 第153.5话 会被误读成 "5话" -> 5）。
CN_CHAPTER_RE = re.compile(r"第?\s*(\d+)\s*(话|回|章|序)")
CN_VOL_RE = re.compile(r"第\s*(\d+)\s*卷")

UA_H5 = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)


@register("zaimanhua")
class ZaimanhuaAdapter(CrawlerAdapter):
    """在漫画 / 再漫画 H5（m.zaimanhua.com）适配器（学习用途 · 受控样本）。

    列表语义 = 首页「最近更新」标签（/app/v1/comic/update/list/0/{page}）。
    返回按更新时间倒序的漫画列表，每页 20 部；受控参数 MAX_PAGE 限制单次
    扫描页数，避免一次收录过多。
    """

    source_name = "zaimanhua"
    base_url = BASE
    robots_allowed = True  # 学习用途：受控低频请求
    capabilities = {"search", "ref"}  # 支持关键词搜索源站 + 解析作品链接/ID
    # 正文图与封面都在独立图床域（sign+t 短时效签名），限定白名单防 SSRF
    image_hosts = {"images.zaimanhua.com"}

    # ------------------------------------------------------------------
    # 列表页：首页「最近更新」标签 -> 前 MAX_PAGE 页
    # ------------------------------------------------------------------
    def fetch_comic_list(self, page: int = 1, since: "datetime | None" = None) -> ComicListResult:
        if page > MAX_PAGE:
            return ComicListResult(items=[], page=page, has_next=False)

        raw = self._api_get(API_UPDATE_LIST.format(page=page)) or {}
        list_data = raw.get("data") or []
        if isinstance(list_data, dict):  # 兜底：个别接口 data 为对象包裹
            list_data = list_data.get("list") or []
        items = [
            self._row_to_brief(row)
            for row in list_data[:20]
            if isinstance(row, dict)
        ]
        # 增量窗口：只保留源站更新时间 > since 的漫画（首次 since=None 全收）
        if since is not None:
            items = [it for it in items if it.source_updated_at is not None and it.source_updated_at > since]
        # 最近更新接口无明确 has_next 标志；以本页是否已满 20 部（原始数据）判断是否还有下一页
        has_next = len(list_data) >= 20 and page < MAX_PAGE
        return ComicListResult(items=items, page=page, has_next=has_next)

    # ------------------------------------------------------------------
    # 详情页：漫画信息 + 连载卷章节（新 -> 旧，取连载卷全部话）
    # ------------------------------------------------------------------
    def fetch_comic_detail(self, comic: ComicBrief) -> ComicDetail:
        raw = self._api_get(API_DETAIL.format(cid=comic.source_comic_id)) or {}
        data = raw.get("data") or {}
        info = data.get("data") or {}  # {id,title,chapters:[...]}

        chapters: list[ChapterBrief] = []
        vol = self._pick_serial_vol(info.get("chapters") or [])
        if vol is not None:
            for item in vol["data"]:
                # 章节唯一键取源站 chapter_order（全局有序整数，精确区分分卷小话，
                # 如 153.5话=1680 / 153话=1670 / 151.5话=1650），避免用正则解析 "第153.5话"
                # 误得 "5话"->5 导致排序错乱。仅当 chapter_order 缺失/非法时才回退正则解析，
                # 且此时只用作一个可排序的整数（对含小数的标题取整部数，见 _chapter_no）。
                no = item.get("chapter_order")
                if not isinstance(no, int):
                    no = self._chapter_no(
                        item.get("chapter_title") or item.get("chapter_name") or ""
                    )
                    if no is None:
                        no = self._chapter_no(item.get("chapter_title") or "")
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

        tags = self._tag_list(info.get("types")) or comic.tags
        # 详情接口本身就带 title / cover / authors：当 brief 里缺失时（「按需导入」只给了
        # 作品链接或 ID，没有列表页摘要）用详情字段补全 —— 有值仍以 brief 优先，
        # 保证既有采集路径行为不变。
        title = (comic.title or "").strip() or str(info.get("title") or "").strip()
        author = (comic.author or "").strip() or self._tag_text(info.get("authors"))
        cover_url = (comic.cover_url or "").strip() or str(info.get("cover") or "").strip()
        latest = (comic.latest_chapter_title or "").strip() or str(
            info.get("last_update_chapter_name") or ""
        ).strip()
        try:
            restricted = int(info.get("is_lock") or 0) == 1
        except (TypeError, ValueError):
            restricted = False
        # ⚠️ 详情接口的逐章 `canRead` **不可靠**：实测「午夜心旋律」(71419) 详情里
        # 131 章 canRead 全为 false，而章节接口返回 canRead=true / page_url 21 条 ——
        # 该字段是未计算的默认值，拿它判「不可读」会把正常作品误杀。
        # 所以这里只认明确的 `is_lock`；「究竟读不读得了」交给 scheduling/ondemand
        # 实测探测一章（`_probe_readable`）。

        return ComicDetail(
            source=self.source_name,
            source_comic_id=comic.source_comic_id,
            title=title,
            author=author,
            cover_url=cover_url,
            status=self._tag_text(info.get("status")) or comic.status,
            category=self._tag_text(info.get("types")) or comic.category,
            tags=tags,
            description=info.get("description") or title,
            latest_chapter_title=latest,
            detail_url=f"{BASE}{API_DETAIL.format(cid=comic.source_comic_id)}",
            chapters=chapters,
            restricted=restricted,
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

    def fetch_source_page_urls(
        self, source_comic_id: str, source_chapter_id: str
    ) -> list[str] | None:
        """现场重拉整章 page_url（让源站重新签发新鲜 sign，规避旧 URL 过期 403）。

        图床 images.zaimanhua.com 的 URL 带短时效签名（sign+t），采集入库的
        source_url 数日即过期——懒转存遇过期/403 时经此重新请求章节接口。
        带实例级缓存：同一章节的多页在同一批转存中只请求一次源站。
        """
        key = (str(source_comic_id), str(source_chapter_id))
        cache = getattr(self, "_url_cache", None)
        if cache is None:
            cache = self._url_cache = {}
        if key in cache:
            return cache[key]
        raw = self._api_get(API_CHAPTER.format(cid=key[0], chid=key[1])) or {}
        info = ((raw.get("data") or {}).get("data") or {})
        urls = [u.strip() for u in (info.get("page_url") or []) if u and u.strip()]
        if len(cache) > 256:  # 缓存保护：超限清空，避免无限增长
            cache.clear()
        cache[key] = urls
        return urls or None

    # ------------------------------------------------------------------
    # 按需导入：关键词搜索 + 作品引用解析（只读，均不写库）
    # ------------------------------------------------------------------
    def search_comics(self, keyword: str, limit: int = 20) -> list[ComicBrief]:
        """用源站搜索接口按书名/作者找作品（`/api/app/v1/search/index`）。

        ⚠️ 与「最近更新」列表的差异：搜索响应里**作品 ID 在 `id` 字段**，
        而 update/list 里作品 ID 在 `comic_id`（其 `id` 恒为 0）——故显式
        指定 `id_field="id"`，避免取到 0。
        """
        kw = (keyword or "").strip()
        if not kw:
            return []
        raw = self._api_get(API_SEARCH, {"keyword": kw, "source": 0, "page": 1, "size": limit}) or {}
        data = raw.get("data") or {}
        rows = data.get("list") if isinstance(data, dict) else data
        if isinstance(rows, dict):  # 兜底：个别返回再包一层 list
            rows = rows.get("list") or []
        items: list[ComicBrief] = []
        for row in (rows or [])[: max(1, limit)]:
            if not isinstance(row, dict):
                continue
            brief = self._row_to_brief(row, id_field="id")
            if brief.source_comic_id and brief.source_comic_id != "0":
                items.append(brief)
        return items

    def parse_comic_ref(self, ref: str) -> str | None:
        """从作品页链接或作品 ID 里取出 source_comic_id。

        接受：纯数字 ID（如 ``18421``）、含 ``id=`` 的作品页链接、
        路径末尾的长数字。**带域名但不是本站的链接直接拒绝**，避免把别的
        源站链接误解析成本站作品。
        """
        s = (ref or "").strip()
        if not s:
            return None
        if s.isdigit():
            return s
        if "://" in s and "zaimanhua" not in s:
            return None
        m = re.search(r"[?&]id=(\d+)", s)
        if m:
            return m.group(1)
        m = re.search(r"/(\d{4,})(?:[/?#]|$)", s)
        if m:
            return m.group(1)
        return None

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _row_to_brief(self, row: dict[str, Any], id_field: str = "comic_id") -> ComicBrief:
        """列表行 -> ComicBrief（字段见 /app/v1/comic/update/list/0/{page} 响应）。

        id_field：作品 ID 所在字段名。列表接口用 `comic_id`（其 `id` 恒为 0），
        搜索接口用 `id`（无 `comic_id`）——语义相反，故显式指定并互为兜底。
        """
        raw_id = row.get(id_field)
        if raw_id in (None, "", 0, "0"):
            raw_id = row.get("id" if id_field != "id" else "comic_id")
        cid = str(raw_id or "").strip()
        title = (row.get("title") or "").strip()
        tags = self._tag_list(row.get("types"))
        # 源站最近更新时间（last_updatetime，Unix 秒级时间戳），用于增量窗口过滤
        updated_at = None
        ts = row.get("last_updatetime")
        if ts:
            try:
                updated_at = datetime.fromtimestamp(int(ts))
            except (TypeError, ValueError, OSError):
                updated_at = None
        return ComicBrief(
            source=self.source_name,
            source_comic_id=cid,
            title=title,
            author=", ".join(
                [a.strip() for a in str(row.get("authors") or "").split(",") if a.strip()]
            ),
            cover_url=(row.get("cover") or "").strip(),
            status=(row.get("status") or "连载").strip(),
            category=self._tag_text(row.get("types")) or "",
            tags=tags,
            latest_chapter_title=(
                row.get("last_update_chapter_name")
                or row.get("last_name")
                or ""
            ).strip(),
            detail_url="",
            source_updated_at=updated_at,
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
        """仅识别「整话」序号（第128话 -> 128；7话 -> 7）。

        含小数的分卷小话（第153.5话 / 151.5话）与卷/其他（第13卷 / 番外篇）
        一律返回 None —— 这类条目由源站 chapter_order 兜底；若 chapter_order 也缺失，
        宁可漏收也不误存成 "5话"->5 这类错误序号。
        """
        text = name or ""
        # 含小数点的标题（分卷小话）拒绝解析，避免 第153.5话 被截成 5
        if "." in text or "．" in text:
            return None
        m = CN_CHAPTER_RE.search(text)
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

    @staticmethod
    def _tag_list(tags: Any) -> list[str]:
        """[{'tag_name':'爱情'},...] -> ['爱情','校园']（去重去空）。"""
        if isinstance(tags, str):
            return [s.strip() for s in tags.split(",") if s.strip()]
        if isinstance(tags, list):
            names = [t.get("tag_name") for t in tags if isinstance(t, dict)]
            seen: list[str] = []
            for n in names:
                n = (n or "").strip()
                if n and n not in seen:
                    seen.append(n)
            return seen
        return []

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
