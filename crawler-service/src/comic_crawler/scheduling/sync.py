"""采集主流程：增量轮询 / 全量扫描（架构方案 §2.2、§4.4）。

- 增量轮询：抓「最近更新」列表 → 指纹去重 → 新作品抓详情入库，旧作品仅更新；
- 全量扫描：逐页翻完整个源站，兜底校正遗漏与失效（与增量同代码路径，差别只在时间水位）。

调度**触发**（cron / 轮询 / 分布式锁）不在这里，见 `scheduler.py` 与部署层；
本模块是「一次同步」的执行逻辑。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from ..fingerprint import build_fingerprint
from ..models import ComicListResult, SyncStats
from ..sources.base import CrawlerAdapter
from ..storage.base import Storage

logger = logging.getLogger(__name__)

MAX_PAGES_PER_SYNC = 50  # 单轮同步最多翻页数，防止失控
FIRST_CHAPTERS = 1       # 新漫画首采：只入库连载卷最新 1 话（页面全部懒下载）；后续增量只补新章节


@dataclass(slots=True)
class SyncSession:
    """一次同步会话的上下文（记录开始时间，供 sync_log 使用）。"""

    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def incremental_sync(
    adapter: CrawlerAdapter,
    storage: Storage,
    mode: str = "incremental",
    limit: int | None = None,
    since=None,
) -> SyncStats:
    """增量同步：列表 → 时间窗口过滤 → 新作品抓详情+章节入库。

    时间窗口：首次（无历史完成时间）采集"今天更新"全部；
    之后采集 [上次同步完成时间, now] 窗口内更新的漫画（由适配器按源站
    时间字段/date 参数过滤，见 CrawlerAdapter.fetch_comic_list 的 since）。

    limit：本次同步最多收录的漫画数（受控样本，如 --limit 1 只抓最近 1 部）；
    None 表示不限制（用适配器 MAX_ITEMS 默认值）。

    since：手动指定的增量起始时间（ISO 字符串或 datetime），优先于上次同步水位；
    None 表示按水位自动推断。用于管理页「按日期控制采集范围」。
    """
    session = SyncSession()
    stats = SyncStats(source=adapter.source_name, mode=mode, started_at=session.started_at)
    # 增量水位：该源上次同步完成时间（None=首次/无记录）
    last_sync_raw = storage.get_last_sync_time(adapter.source_name)
    watermark = None
    if last_sync_raw and mode != "full":
        # 存储层返回 naive datetime（DATETIME 列）；兼容可能返回 ISO 字符串的实现
        if isinstance(last_sync_raw, datetime):
            watermark = last_sync_raw
        else:
            try:
                watermark = datetime.fromisoformat(last_sync_raw)
            except ValueError:
                watermark = None
    # 用户手动指定 since 日期优先于水位
    if since:
        since = datetime.fromisoformat(since) if isinstance(since, str) else since
    else:
        since = watermark
    logger.info("开始 %s 同步: %s（since=%s limit=%s）", mode, adapter, since, limit)

    adapter.pre_fetch()
    try:
        page = 1
        processed = 0
        while True:
            result = adapter.fetch_comic_list(page=page, since=since)
            processed = _process_batch(adapter, storage, result, stats, limit, processed)
            if not result.has_next:
                break
            if limit is not None and processed >= limit:
                logger.info("已达受控 limit=%d，提前终止列表翻页", limit)
                break
            page += 1
            if page > MAX_PAGES_PER_SYNC:
                logger.warning("已达最大翻页数 %d，提前终止", MAX_PAGES_PER_SYNC)
                break
    finally:
        adapter.post_fetch()

    storage.log_sync(adapter.source_name, mode, stats)
    logger.info(stats.summary())
    return stats


def _process_batch(
    adapter: CrawlerAdapter,
    storage: Storage,
    result: ComicListResult,
    stats: SyncStats,
    limit: int | None = None,
    processed: int = 0,
) -> int:
    for brief in result.items:
        if limit is not None and processed >= limit:
            break
        stats.total_seen += 1
        processed += 1
        try:
            fp = build_fingerprint(brief.title, brief.author)
            existing_id = storage.get_comic_id_by_fingerprint(fp)
            if existing_id is not None:
                stats.updated_comics += 1
                # 已收录：仍抓一次详情做幂等补录（upsert 按指纹/章节号跳过已存在项，
                # 源站发布新章节时由此自动补入）。生产环境可用 latest_chapter_title
                # 快筛减少请求，演示以正确性优先。
                detail = adapter.fetch_comic_detail(brief)
                _upsert_detail(adapter, storage, detail, fp, stats)
                continue

            detail = adapter.fetch_comic_detail(brief)
            _upsert_detail(adapter, storage, detail, fp, stats)
        except Exception:
            stats.failed += 1
            logger.exception("处理漫画 %s 失败", brief.title)
    return processed


def _upsert_detail(
    adapter: CrawlerAdapter,
    storage: Storage,
    detail: "ComicDetail",
    fp: str,
    stats: SyncStats,
    first_chapters: int | None = FIRST_CHAPTERS,
    register_pages: bool = True,
) -> None:
    """详情 + 章节 + 页面入库（采集收录、采集补章、按需导入共用）。

    章节采样策略（避免每轮对全卷逐章请求，解决"太慢"）：
    - **按需导入**（`first_chapters=None`）：补齐库内**缺失的所有章节**（不只是比库内最大值
      更新的那些）—— 库里可能只有采集时收的最新 1 话，而用户要的是完整目录；
    - 新漫画（库内尚无该作品章节）：只入库连载卷最新 `first_chapters` 话（采集默认 1 话）；
    - 已收录漫画（库内已有章节）：只入库 chapter_no 大于库内最大值的新章节，
      其余已同步章节仅更新元数据、不重复抓分页。

    页面一律「懒下载」：入库只登记源站 URL（cached_status=未转存），图片字节不主动下载，
    由失效巡检 lazy_transfer / 读某话时的穿透兜底按需转存（见 images/transfer.py）。

    register_pages：是否登记各章节的页清单（默认 True = 采集用）。**按需导入传 False**
    —— 连页清单都不登记，导入 100 话只需 1 次请求（而不是 100 次章节请求），
    页清单等用户真正打开那一话时再生登记。
    """
    comic_id, is_new = storage.upsert_comic(detail, fp)
    if is_new:
        stats.new_comics += 1

    # 外链封面落盘为图库内相对 key（入库即落盘；失败仅告警，下次同步自愈）
    try:
        from ..images.transfer import ensure_cover_local
        from ..images.store import LocalImageStore

        ensure_cover_local(storage, LocalImageStore(), comic_id, detail.cover_url)
    except Exception:
        logger.exception("封面落盘流程异常 comic_id=%s", comic_id)

    # 库内已有章节的 chapter_no 集合（用于增量判断哪些是新章节）
    existing_nos = {int(ch["chapter_no"]) for ch in storage.get_chapters(comic_id)}
    existing_max_no = max(existing_nos) if existing_nos else 0
    # detail.chapters 按源站返回（新 -> 旧）：
    # - 按需导入（first_chapters=None）：**补齐库内缺的所有章节**——不只是比库内最大的
    #   更新的那些。库里可能只有采集时收的最新 1 话，用户要的是完整目录；
    # - 新漫画（库内无章节）：只取最新 first_chapters 话（采集默认 1 话）；
    # - 老漫画（库内已有章节）：取所有 chapter_no 大于库内最大 chapter_no 的新章节（增量）。
    if first_chapters is None:
        sampled = [c for c in detail.chapters if c.chapter_no not in existing_nos]
    elif existing_nos:
        sampled = [c for c in detail.chapters if c.chapter_no > existing_max_no]
    else:
        sampled = detail.chapters[:first_chapters]

    for chapter in sampled:
        chapter_id, chapter_new = storage.upsert_chapter(comic_id, chapter)
        if chapter_new:
            stats.new_chapters += 1
        if not register_pages:
            # 按需导入：只入目录，**页清单留到用户真正打开这一话时再登记**
            # （见 api-service/services/ondemand.ensure_chapter_pages）。
            # 这样导入 100 话只需要 1 次请求，而不是 100 次。
            continue
        try:
            pages = adapter.fetch_chapter_pages(detail, chapter)
            if pages:
                # 懒下载：只登记页面源站 URL（cached_status=未转存），图片字节不主动下载，
                # 由失效巡检 lazy_transfer / 读图时的穿透兜底按需转存
                # （见 images/transfer.fetch_page_bytes）。
                storage.upsert_pages(chapter_id, pages)
        except Exception:
            # 页面登记失败不阻塞整部漫画入库，仅记录并继续
            stats.failed += 1
            logger.warning("章节 %s(%s) 页面登记失败", chapter.title, chapter.source_chapter_id)


def full_sync(adapter: CrawlerAdapter, storage: Storage, limit: int | None = None, since=None) -> SyncStats:
    """全量扫描：语义与增量一致（同为列表+详情补全），生产环境可在此
    追加"失效校验"（重抓已标记失效的章节、比对 content_hash 变更）。"""
    return incremental_sync(adapter, storage, mode="full", limit=limit, since=since)

