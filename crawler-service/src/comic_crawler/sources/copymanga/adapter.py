"""拷貝漫畫（copy4000.com）适配器。

目标站：https://copy4000.com   API：https://api.copy4000.com/api/v3/*
逆向结论（2026-09-16 实测确认）：
- **前后端分离**：网页是 SSR + 内联 JSON，但内容全部来自公开 JSON API，**匿名即可读**，
  无登录、无 Cookie、无签名、无付费门禁（付费作品由 `is_lock` 标出）。
- 接口统一返回 `{"code": 200, "message": "请求成功", "results": {...}}`；
  ⚠️ **成功码是 `code == 200`，但 HTTP 状态码可能是 200 也可能是非标的 210**（参数非法时
  HTTP 210 + `code: 210`）—— 判定一律看 `code`，不要看 HTTP 状态码。
- 必带头：`User-Agent`（桌面 UA）。另有 `version` / `platform` / `region` 三个版本与
  分区头，缺失时实测仍可用，但带上可避免落到旧版响应。
  `Accept-Language: zh-Hans` 只影响界面文案，**作品名仍是源站繁体**（见 README「已知坑」）。
- 关键接口（均 GET）：
    - 列表：  /api/v3/comics?limit=&offset=&ordering=-datetime_updated（ordering 还可取
              `datetime_updated` / `-popular`；`theme=<path_word>` 可只取某题材）
              -> {total, list[], limit, offset}
    - 搜索：  /api/v3/search/comic?q=&limit=&offset=
    - 详情：  /api/v3/comic2/{path_word}?platform=1
              -> {is_banned, is_lock, is_login, is_vip, is_mobile_bind, comic{}, popular, groups{}}
    - 章节：  /api/v3/comic/{path_word}/group/{group_path_word}/chapters?limit=&offset=
    - 内页：  /api/v3/comic/{path_word}/chapter2/{uuid}?platform=1 -> results.chapter.contents[].url
- **作品 ID = `path_word`**（字符串，如 `dianjuren`），不是数字 ID，也不是详情里那个 `uuid`。
- **`groups` 在 `results` 层级**（不在 `comic` 里），是 `{组名: {path_word, count, name}}`：
  常见 `default`（默認/連載）、`tankobon`（单行本）、`karapeji`（全彩版）。
  组内**不含**章节数组，章节要单独请求 group 端点。
- 章节列表实测 `limit` 上限在 500~1000 之间（500 可用、1000 返回空），故按 500 分页累加。
- 图床是**分片域名** `s?.mangafunb.fun`：实测 24 个分片（`sa`…`sz` + `s0`）且**同一部的
  封面与正文图落在同一分片**。分片由作品路径散列得出、集合可能新增，无法穷举 ——
  故 `image_hosts` 用通配 `*.mangafunb.fun`（见 images/transfer._host_allowed）。
- 图片 URL **明文直出、无签名、无 Referer 限制**（实测带/不带 Referer 均 HTTP 200 /
  image/jpeg）；封面 URL 带 `.328x422.jpg` 缩略后缀。
  ⚠️ **地址原样入库，不做任何改写**（2026-09-18 决定，撤销"剥后缀取原图"，详见源 README「图片」段）：
  那个后缀**不是**可替换的 resize 参数（实测只有基址与精确 `.328x422.jpg` 两个真实文件，
  其它规格一律 404）；剥后缀的收益不稳（抽 20 部有 9 部原图反而更小），
  但一旦按段拆错扩展名就整张 404（`.jpeg`/`.png` 曾被写成 `.jpg`）→ 直接用源站给的地址最省事。

模型映射：
- 1 部漫画 = 站内一个 `path_word`                       -> comic 表
- 章节 = 所选 group 下每个 chapter（`index` 0 起连续）   -> chapter 表，chapter_no = index + 1
- 每张正文图 = `contents[].url`                          -> page 表

时间窗口（增量）说明：
- 列表的时间基准 `datetime_updated` **只到「天」**（"2026-09-16"，无时分秒）；
- 因此增量窗口按**日期**比较（`item.date() >= since.date()`）而不是 `>` 绝对值 ——
  日期粒度的源用 `>` 会把当天已更新的作品全部漏掉。

页面转存约定（与其它源一致）：正文图只登记 URL（cached_status=未转存），由懒转存 /
用户阅读时按需落盘；封面入库即落盘（covers/{id}.jpg）。
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

SITE = "https://copy4000.com"
API = "https://api.copy4000.com"
API_LIST = "/api/v3/comics"
API_SEARCH = "/api/v3/search/comic"
API_DETAIL = "/api/v3/comic2/{path_word}"
API_GROUP_CHAPTERS = "/api/v3/comic/{path_word}/group/{group}/chapters"
API_CHAPTER = "/api/v3/comic/{path_word}/chapter2/{uuid}"

# 受控参数：列表翻页安全阀（每页 20 部）。增量模式下实际按时间窗口边界提前停
# （见 fetch_comic_list），只有全量/首采才会翻到这一页数；与 mangadex 同一口径。
MAX_PAGE = 50
PAGE_SIZE = 20

# 章节列表单次拉取上限（实测 500 可用、1000 直接返回空），超出用 offset 翻页累加
CHAPTER_PAGE_SIZE = 500
# 单部作品章节数硬上限：防御异常数据把一次详情抓取拖死（实测最大量级约 300 话）
MAX_CHAPTERS = 3000

# 优先收「连载」组；该组缺失或为空时退化为章节数最多的组（有些作品只有单行本）
PREFERRED_GROUPS = ("default",)

# 作品链接 / 纯 ID 解析：只认本栈域名，避免把别的源站链接误解析成这里
REF_HOSTS = ("copy4000.com", "www.copy4000.com")

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# 源站前端自报的版本串；带上可避免落到旧版响应（与站点 bundle 一致）
API_VERSION = "2024.06.20"


@register("copymanga")
class CopymangaAdapter(CrawlerAdapter):
    """拷贝漫画（copy4000.com）适配器。

    列表语义 = 「最近更新」（`/api/v3/comics?ordering=-datetime_updated`），
    按源站更新时间倒序；增量模式按时间窗口边界翻页（防遗漏批量更新），
    MAX_PAGE 是翻页安全阀（仅全量/首采才会触达）。
    """

    source_name = "copymanga"
    base_url = SITE
    robots_allowed = True  # 学习用途：受控低频请求
    capabilities = {"search", "ref"}  # 支持关键词搜索 + 解析作品链接/ID
    # 图床是分片域名 s?.mangafunb.fun（sa…sz + s0，共 24 个且可能新增），无法穷举，
    # 故用通配白名单：只放行 mangafunb.fun 的**一级子域**（见 images/transfer._host_allowed）。
    image_hosts = {"*.mangafunb.fun"}

    # ------------------------------------------------------------------
    # 列表：最近更新（按源站更新时间倒序）
    # ------------------------------------------------------------------
    def fetch_comic_list(self, page: int = 1, since: "datetime | None" = None) -> ComicListResult:
        if page > MAX_PAGE:
            return ComicListResult(items=[], page=page, has_next=False)

        offset = (page - 1) * PAGE_SIZE
        res = self._api_get(
            API_LIST,
            {"limit": PAGE_SIZE, "offset": offset, "ordering": "-datetime_updated"},
        ) or {}
        rows = [r for r in (res.get("list") or []) if isinstance(r, dict)]
        total = _to_int_safe(res.get("total"))

        items = [self._row_to_brief(r) for r in rows]
        # 增量窗口：源站时间只到「天」，故按**日期**比较（用 > 会把当天更新全漏掉）
        if since is not None:
            day = (since.replace(tzinfo=None) if since.tzinfo else since).date()
            items = [
                it
                for it in items
                if it.source_updated_at is not None and it.source_updated_at.date() >= day
            ]

        # 翻页：列表按源站更新时间倒序——增量模式下当某页没有任何窗口内作品（items 空）
        # 说明已翻过 since 边界，后续页只会更旧，停止翻页，避免固定页数漏掉窗口内的大批量更新；
        # 无 since（全量/首采）则翻到 MAX_PAGE 安全阀为止。
        has_next = (offset + len(rows)) < total and page < MAX_PAGE
        if since is not None and not items:
            has_next = False
        return ComicListResult(items=items, page=page, has_next=has_next)

    # ------------------------------------------------------------------
    # 详情：作品信息 + 连载组章节（新 -> 旧由源站 index 保证升序）
    # ------------------------------------------------------------------
    def fetch_comic_detail(self, comic: ComicBrief) -> ComicDetail:
        res = self._api_get(API_DETAIL.format(path_word=comic.source_comic_id), {"platform": 1}) or {}
        info = res.get("comic") or {}
        groups = res.get("groups") or {}

        group = self._pick_group(groups)
        chapters = self._fetch_chapters(comic.source_comic_id, group) if group else []

        title = (comic.title or "").strip() or str(info.get("name") or "").strip()
        author = (comic.author or "").strip() or self._author_text(info.get("author"))
        # 封面地址**原样入库**（不剥缩略后缀，见模块 docstring）
        cover_url = (comic.cover_url or "").strip() or str(info.get("cover") or "").strip()
        tags = self._tag_list(info.get("theme")) or list(comic.tags)
        last = info.get("last_chapter") or {}

        return ComicDetail(
            source=self.source_name,
            source_comic_id=comic.source_comic_id,
            title=title,
            author=author,
            cover_url=cover_url,
            status=self._status_of(info) or comic.status,
            category=(tags[0] if tags else comic.category),
            tags=tags,
            description=str(info.get("brief") or "").replace("\r\n", "\n").strip() or title,
            latest_chapter_title=str(last.get("name") or "").strip() or comic.latest_chapter_title,
            detail_url=f"{SITE}/comic/{comic.source_comic_id}",
            chapters=chapters,
            # 合规红线：只认平台明确的锁定位 `is_lock`（付费/锁定内容不收录）。
            # ⚠️ 详情里的 `is_login` / `is_vip` / `is_banned` 不是"不可读"的充分条件，
            #    真正读不读得了由 scheduling/ondemand._probe_readable 实测一章决定。
            restricted=bool(res.get("is_lock")),
        )

    # ------------------------------------------------------------------
    # 章节图片：/comic/{path_word}/chapter2/{uuid} -> contents[].url
    # ------------------------------------------------------------------
    def fetch_chapter_pages(self, detail: ComicDetail, chapter: ChapterBrief) -> list[PageInfo]:
        urls = self._chapter_urls(chapter.source_comic_id, chapter.source_chapter_id)
        return [
            PageInfo(page_no=idx, source_url=url)
            for idx, url in enumerate(urls, start=1)
        ]

    def fetch_source_page_urls(
        self, source_comic_id: str, source_chapter_id: str
    ) -> list[str] | None:
        """现场重拉整章图片 URL。

        图床 URL 实测**无签名、直接可下**，正常情况下用不上；覆写它是因为图床是
        **分片域名**（`s?.mangafunb.fun`，同一部的封面与正文图同分片）—— 分片一旦迁移，
        库里登记的旧域名会 404，此时按源站 id 重拉即可拿到新域名。
        带实例级缓存：同一章的多页在同一批转存中只请求一次源站。
        """
        key = (str(source_comic_id), str(source_chapter_id))
        cache = getattr(self, "_url_cache", None)
        if cache is None:
            cache = self._url_cache = {}
        if key in cache:
            return cache[key]
        urls = self._chapter_urls(key[0], key[1])
        if len(cache) > 256:  # 缓存保护：超限清空，避免无限增长
            cache.clear()
        cache[key] = urls
        return urls or None

    def chapter_api_path(self, comic_id: str, chapter_id: str) -> str:
        """重拉页地址时实际调用的源站接口（**仅供日志「接口」列**）。"""
        return f"{API}{API_CHAPTER.format(path_word=comic_id, uuid=chapter_id)}"

    # ------------------------------------------------------------------
    # 按需导入：关键词搜索 + 作品引用解析（只读，均不写库）
    # ------------------------------------------------------------------
    def search_comics(self, keyword: str, limit: int = 20) -> list[ComicBrief]:
        kw = (keyword or "").strip()
        if not kw:
            return []
        res = self._api_get(API_SEARCH, {"q": kw, "limit": max(1, limit), "offset": 0}) or {}
        rows = [r for r in (res.get("list") or []) if isinstance(r, dict)]
        return [self._row_to_brief(r) for r in rows[: max(1, limit)] if r.get("path_word")]

    def parse_comic_ref(self, ref: str) -> str | None:
        """从作品页链接或作品 path_word 里取出 source_comic_id。

        接受：``https://copy4000.com/comic/{path_word}``、纯 path_word（如 ``dianjuren``）。
        **带域名但不是本站的链接直接拒绝**（避免把别的源站链接误解析成本站作品）。
        """
        s = (ref or "").strip()
        if not s:
            return None
        if "://" in s:
            if not any(h in s for h in REF_HOSTS):
                return None
            m = re.search(r"/comic/([A-Za-z0-9_-]+)", s)
            return m.group(1) if m else None
        # 裸标识：path_word 只由字母/数字/下划线/连字符组成
        return s if re.fullmatch(r"[A-Za-z0-9_-]{2,64}", s) else None

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _row_to_brief(self, row: dict[str, Any]) -> ComicBrief:
        """列表/搜索行 -> ComicBrief（两种响应的作品 ID 都是 `path_word`）。

        ⚠️ 列表与搜索的字段差异：搜索行**没有** `datetime_updated`；
        并且实测**列表行的 `theme` 恒为空数组**（详情才有题材）—— 所以标签/分类
        只能靠详情接口补，这里传空不传错。按需导入会立刻拉详情，采集路径由
        `_upsert_detail` 用详情覆盖，两处都会补上。
        """
        path_word = str(row.get("path_word") or "").strip()
        tags = self._tag_list(row.get("theme"))
        return ComicBrief(
            source=self.source_name,
            source_comic_id=path_word,
            title=str(row.get("name") or "").strip(),
            author=self._author_text(row.get("author")),
            # 封面地址原样入库（与详情路径一致，不剥缩略后缀）
            cover_url=str(row.get("cover") or "").strip(),
            # 列表不给连载状态，先按默认「连载」；详情接口会覆盖成真实状态
            status="连载",
            category=tags[0] if tags else "",
            tags=tags,
            latest_chapter_title="",
            detail_url=f"{SITE}/comic/{path_word}" if path_word else "",
            source_updated_at=self._parse_date(row.get("datetime_updated")),
        )

    def _fetch_chapters(self, path_word: str, group: str) -> list[ChapterBrief]:
        """拉某分组下的全部章节（按 500 一页累加，直到达到 total 或硬上限）。

        顺序即源站 `index` 升序（0 起连续），chapter_no 直接取 index + 1 ——
        比正则解析「第01话」可靠（站点同时存在「第1卷」这类卷标题的组）。
        """
        out: list[ChapterBrief] = []
        offset = 0
        while True:
            res = self._api_get(
                API_GROUP_CHAPTERS.format(path_word=path_word, group=group),
                {"limit": CHAPTER_PAGE_SIZE, "offset": offset},
            ) or {}
            rows = [r for r in (res.get("list") or []) if isinstance(r, dict)]
            if not rows:
                break
            for r in rows:
                uuid = str(r.get("uuid") or "").strip()
                if not uuid:
                    continue
                out.append(
                    ChapterBrief(
                        source=self.source_name,
                        source_comic_id=path_word,
                        chapter_no=_to_int_safe(r.get("index")) + 1,
                        title=str(r.get("name") or "").strip(),
                        source_chapter_id=uuid,
                        pages_url="",
                    )
                )
            offset += len(rows)
            total = _to_int_safe(res.get("total"))
            if offset >= total or len(out) >= MAX_CHAPTERS:
                break
        return out[:MAX_CHAPTERS]

    def _chapter_urls(self, path_word: str, uuid: str) -> list[str]:
        """章节内页 URL 列表（源站原图，未做转存）。"""
        res = self._api_get(
            API_CHAPTER.format(path_word=path_word, uuid=uuid), {"platform": 1}
        ) or {}
        contents = ((res.get("chapter") or {}).get("contents")) or []
        return [
            str(c.get("url")).strip()
            for c in contents
            if isinstance(c, dict) and str(c.get("url") or "").strip()
        ]

    @staticmethod
    def _pick_group(groups: dict) -> str:
        """选要收的分组 path_word：优先「连载」组，否则退化为章节数最多的组。

        站点把同一部作品按来源拆成多个组（`default` 默認/連載、`tankobon` 单行本、
        `karapeji` 全彩版）。**只收一个组**：组间章节编号语义不同，混在一起会让
        chapter_no 冲突（同一章在两个组里各有一份）。少数作品没有 `default`
        （只有单行本），此时取章节最多的那个组，避免整部收不到章节。
        """
        if not isinstance(groups, dict) or not groups:
            return ""
        for name in PREFERRED_GROUPS:
            g = groups.get(name)
            if isinstance(g, dict) and g.get("path_word") and _to_int_safe(g.get("count")) > 0:
                return str(g["path_word"])
        best, best_n = "", 0
        for g in groups.values():
            if isinstance(g, dict) and g.get("path_word"):
                n = _to_int_safe(g.get("count"))
                if n > best_n:
                    best, best_n = str(g["path_word"]), n
        return best

    @staticmethod
    def _status_of(info: dict) -> str:
        """源站连载状态 -> 项目口径（连载 / 完结）。

        按 `status.display` 文本判定（实测取值 `連載中` / `已完結`）而不是 `value` 码 ——
        文本稳、码值含义不明（站点未公开映射表）。
        """
        disp = str((info.get("status") or {}).get("display") or "")
        if not disp:
            return ""
        return "完结" if ("完" in disp or "結" in disp or "结" in disp) else "连载"

    @staticmethod
    def _author_text(authors: Any) -> str:
        """[{'name': '藤本タツキ', ...}] -> 'A, B'。"""
        if isinstance(authors, str):
            return authors.strip()
        if isinstance(authors, list):
            names = [str(a.get("name") or "").strip() for a in authors if isinstance(a, dict)]
            return ", ".join(n for n in names if n)
        return ""

    @staticmethod
    def _tag_list(themes: Any) -> list[str]:
        """[{'name': '格鬥', ...}] -> ['格鬥', ...]（去重去空，保序）。"""
        if not isinstance(themes, list):
            return []
        out: list[str] = []
        for t in themes:
            name = str((t or {}).get("name") or "").strip() if isinstance(t, dict) else ""
            if name and name not in out:
                out.append(name)
        return out

    @staticmethod
    def _parse_date(text: Any) -> datetime | None:
        """源站 `datetime_updated` 只到「天」（"2026-09-16"）-> naive datetime。"""
        m = _DATE_RE.search(str(text or ""))
        if not m:
            return None
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # 请求层：统一 JSON 接口，成功判定看 body 里的 code（不是 HTTP 状态码）
    # ------------------------------------------------------------------
    def _api_get(self, path: str, params: dict | None = None) -> dict[str, Any] | None:
        url = f"{API}{path}"
        headers = {
            "User-Agent": UA_DESKTOP,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-Hans",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "version": API_VERSION,
            "platform": "1",
            "region": "1",
        }
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
                    resp = client.get(url, params=dict(params or {}))
                    data = resp.json()
                # ⚠️ 源站成功码是 body 里的 code == 200；HTTP 状态码可能是非标的 210，
                #    所以这里不看 resp.status_code（它会把"参数非法"也当成 200 级成功）。
                code = data.get("code")
                if code != 200:
                    raise RuntimeError(
                        f"copymanga API {path} code={code}: {data.get('message')}"
                    )
                return data.get("results") or {}
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(0.8 * (attempt + 1))
        if last_err is not None:
            raise last_err
        return None


def _to_int_safe(value: Any) -> int:
    """宽松转 int（源站大量数字字段是字符串；缺省/非法一律当 0）。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
