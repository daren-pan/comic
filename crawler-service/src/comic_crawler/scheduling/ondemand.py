"""按需导入：把用户**指定的一部作品**收录进库（搜索命中 / 粘贴作品链接 / 作品 ID）。

与「采集」（`sync.py`）是两种驱动方式，但**共用同一套入库逻辑**（`_upsert_detail`）：

|            | 采集 sync                        | 按需导入 ondemand            |
|------------|----------------------------------|------------------------------|
| 驱动       | 源站「最近更新」列表翻页          | 用户指定的作品                |
| 覆盖范围   | 只能碰到榜单上的作品              | 榜单之外的老作品也能收        |
| 章节       | 新作品只收最新 1 话               | **全量收目录**（目录很便宜）   |
| 页清单     | 登记最新 1 话的页                 | **一页都不登记**              |
| 正文图     | 不下载                            | **不下载**                    |

导入只做三件事：写 `comic` 1 行、写 `chapter` 全量、把封面落盘 1 张
（见 `images/transfer.ensure_cover_local`）。正文图既不登记也不下载 —— 用户
真读某一话时才由 `images/transfer.fetch_page_bytes` 现场取回并顺手落盘
（「边看边转」，用户不用等整话下载完）。

源站请求共 **2 次**：① 详情（书目 + 全部章节）；② 探测一章确认**真的读得了**
（详情接口的 `canRead` 不可靠，见 `_probe_readable`）。
"""
from __future__ import annotations

import logging
from datetime import datetime

from ..fingerprint import build_fingerprint
from ..models import ComicBrief, ComicDetail, SyncStats
from ..sources.base import CrawlerAdapter
from ..storage.base import Storage
from .sync import _upsert_detail

logger = logging.getLogger(__name__)

IMPORT_MODE = "ondemand"  # 写进 sync_log.mode：区分「用户按需导入」与常规采集
SEARCH_LIMIT = 5          # 关键词导入时只看前几条候选（取第一条作为目标）


class OnDemandError(Exception):
    """按需导入的**预期内**失败（与意外异常区分，API 层据此返回 4xx 而非 500）。"""


class ComicNotFound(OnDemandError):
    """源站没有这部作品（搜不到 / 链接解析不到）。"""


class ComicRestricted(OnDemandError):
    """源站标记为付费/锁定内容 —— 按合规红线不收录。"""


class UnsupportedCapability(OnDemandError):
    """该源不支持所需能力（如未实现关键词搜索）。"""


def _find_by_keyword(adapter: CrawlerAdapter, keyword: str) -> ComicBrief:
    """用源站搜索找作品，取最靠前的一条作为导入目标。"""
    if "search" not in adapter.capabilities:
        raise UnsupportedCapability(
            f"源站 {adapter.source_name} 不支持关键词搜索，请改用作品链接或作品 ID"
        )
    hits = adapter.search_comics(keyword, limit=SEARCH_LIMIT)
    if not hits:
        raise ComicNotFound(f"源站 {adapter.source_name} 未搜到「{keyword}」")
    logger.info("按需导入：关键词「%s」命中 %d 条，取「%s」", keyword, len(hits), hits[0].title)
    return hits[0]


def _probe_readable(adapter: CrawlerAdapter, detail: "ComicDetail") -> bool:
    """**实测**这部作品能不能读到图：探一章调章节接口，页清单非空即可读。

    为什么要实测、为什么不看详情接口的逐章 `canRead`：那个字段是**未计算的默认值**
    —— 实测「午夜心旋律」(71419) 详情里 131 章 canRead 全 false，而章节接口对
    **最新的 130 话**返回 `canRead=true / page_url 21 条`（完全可读）。

    探测顺序（最多 2 次请求）：**先最新一章，再退最老一章** —— 实测「午夜心旋律」只有
    最新的 130 话有图，1、2 话源站**本身没有数据**，两端都要试才不至于误判。
    任一章能取到图就放行：**源站部分章节没有数据**是常见情况（原因可能是数据缺失，
    也可能是需登录/付费，**接口层面无法区分，故不做归因**），只按"能否取到图"判断。

    探测本身异常（网络故障、适配器不支持）时**放行**：不因探测不了就拒绝，
    图片真读不到会自然回落到占位图（见 api-service 读图三级兜底）。
    """
    if not detail.chapters:
        return False
    ordered = sorted(detail.chapters, key=lambda c: c.chapter_no)
    candidates = [ordered[-1]] + ([ordered[0]] if len(ordered) > 1 else [])
    for chapter in candidates:
        try:
            if adapter.fetch_chapter_pages(detail, chapter):
                return True
        except Exception as exc:
            logger.warning("可读性探测异常（放行，交给读时兜底）：%s", exc)
            return True
    return False


def resolve_brief(
    adapter: CrawlerAdapter,
    *,
    keyword: str | None = None,
    ref: str | None = None,
    source_comic_id: str | None = None,
) -> ComicBrief:
    """把「作品 ID / 作品链接 / 关键词」统一解析为一个只带 id 的 `ComicBrief`。

    作品 ID 最直接；链接由适配器 `parse_comic_ref` 解析（解析不出来就退回当关键词）；
    关键词走源站搜索。注意 `fetch_comic_detail` 只要求 `source_comic_id`，
    标题/作者/封面由详情接口自身补全（见各源适配器）。
    """
    if source_comic_id:
        return ComicBrief(source=adapter.source_name, source_comic_id=str(source_comic_id), title="")
    if ref:
        sid = adapter.parse_comic_ref(ref) if "ref" in adapter.capabilities else None
        if sid:
            return ComicBrief(source=adapter.source_name, source_comic_id=str(sid), title="")
        keyword = keyword or ref  # 链接解析不出来 → 当作关键词再试一次
    kw = (keyword or "").strip()
    if not kw:
        raise ValueError("必须提供 keyword / ref / source_comic_id 之一")
    return _find_by_keyword(adapter, kw)


def import_comic(
    adapter: CrawlerAdapter,
    storage: Storage,
    *,
    keyword: str | None = None,
    ref: str | None = None,
    source_comic_id: str | None = None,
    first_chapters: int | None = None,
) -> dict:
    """按需导入一部作品，返回结果摘要（**不下载任何正文图**）。

    first_chapters：新作品入库的章节数；默认 None = **全量收目录**。
    重复导入是幂等的：`upsert_comic` 先按跨源指纹、再按 (源, 源作品 ID) 判重，
    命中则更新元数据、不新增行，章节也只补 chapter_no 更大的新章。
    """
    brief = resolve_brief(
        adapter, keyword=keyword, ref=ref, source_comic_id=source_comic_id
    )
    # 同源是否已收录（导入前查询，用于把「新导入」与「已在本源」区分开告诉用户）
    existing_same = storage.get_comic_id_by_source(adapter.source_name, brief.source_comic_id)

    adapter.pre_fetch()
    try:
        detail = adapter.fetch_comic_detail(brief)
        if detail.restricted:
            raise ComicRestricted(
                "该作品在源站被标记为锁定内容（is_lock），按合规约定不收录："
                f"{detail.title or brief.title}"
            )
        if not detail.title:
            raise ComicNotFound(f"{adapter.source_name} 详情为空：{brief.source_comic_id}")
        # 详情接口的 canRead 不可靠，真判断「读不读得了」只能实测一章（多 1 次请求）
        if not _probe_readable(adapter, detail):
            raise ComicRestricted(
                "该作品在源站取不到任何章节图片（源站没有数据，或需登录 / 付费），"
                f"按合规约定不收录：{detail.title}"
            )

        fp = build_fingerprint(detail.title, detail.author)
        # 跨源是否已收录：指纹唯一键决定了「同一部作品全库只有一行」，
        # 命中说明已有别的源收过它，本次导入只会更新那一行（不会新增）。
        existing_cross = storage.get_comic_id_by_fingerprint(fp)

        stats = SyncStats(
            source=adapter.source_name,
            mode=IMPORT_MODE,
            started_at=datetime.now().isoformat(timespec="seconds"),
            total_seen=1,
        )
        _upsert_detail(
            adapter,
            storage,
            detail,
            fp,
            stats,
            first_chapters=first_chapters,
            register_pages=False,  # 只入目录；页清单等用户打开那一话时再生登记
        )
    finally:
        adapter.post_fetch()

    storage.log_sync(adapter.source_name, IMPORT_MODE, stats)
    comic_id = existing_same or existing_cross or storage.get_comic_id_by_source(
        adapter.source_name, brief.source_comic_id
    )
    chapters = len(storage.get_chapters(comic_id)) if comic_id else 0
    logger.info("按需导入完成 comic_id=%s「%s」章节 %d", comic_id, detail.title, chapters)

    return {
        "comicId": comic_id,
        "title": detail.title,
        "author": detail.author,
        "source": adapter.source_name,
        "sourceComicId": brief.source_comic_id,
        "isNew": bool(stats.new_comics),
        "chapters": chapters,          # 库内现有章节总数
        "newChapters": stats.new_chapters,
        "failed": stats.failed,
        # 已在本源收录过（重复导入）；已有别的源收录（会被跨源合并到同一行）
        "alreadySameSource": existing_same is not None,
        "crossSourceComicId": (
            existing_cross if existing_cross and existing_cross != comic_id else None
        ),
        "summary": stats.summary(),
    }

