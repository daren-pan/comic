"""采集调度器：全量扫描 / 增量轮询。

对应架构方案 §2.2 抓取频率与 §4.4 任务调度：
- 增量轮询：抓"最近更新"列表 → 指纹去重 → 新作品抓详情入库，旧作品仅更新；
- 全量扫描：逐页翻完整个源站，兜底校正遗漏与失效。

调度触发（cron / 分布式锁）由部署层负责，本模块是同步的执行逻辑。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from .adapter.base import CrawlerAdapter
from .fingerprint import build_fingerprint
from .models import ComicListResult, SyncStats
from .storage import Storage

logger = logging.getLogger(__name__)

MAX_PAGES_PER_SYNC = 50  # 单轮同步最多翻页数，防止失控


@dataclass(slots=True)
class SyncSession:
    """一次同步会话的上下文（记录开始时间，供 sync_log 使用）。"""

    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def incremental_sync(adapter: CrawlerAdapter, storage: Storage, mode: str = "incremental") -> SyncStats:
    """增量同步：列表 → 指纹去重 → 新作品抓详情+章节入库。"""
    session = SyncSession()
    stats = SyncStats(source=adapter.source_name, mode=mode, started_at=session.started_at)
    logger.info("开始 %s 同步: %s", mode, adapter)

    adapter.pre_fetch()
    try:
        page = 1
        while True:
            result = adapter.fetch_comic_list(page=page)
            _process_batch(adapter, storage, result, stats)
            if not result.has_next:
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


def _process_batch(adapter: CrawlerAdapter, storage: Storage, result: ComicListResult, stats: SyncStats) -> None:
    for brief in result.items:
        stats.total_seen += 1
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


def _upsert_detail(
    adapter: CrawlerAdapter, storage: Storage, detail: "ComicDetail", fp: str, stats: SyncStats
) -> None:
    """详情 + 章节 + 页面入库（新漫画收录与已收录补章共用）。"""
    comic_id, is_new = storage.upsert_comic(detail, fp)
    if is_new:
        stats.new_comics += 1

    # 外链封面落盘为图库内相对 key（入库即落盘；失败仅告警，下次同步自愈）
    try:
        from .image_service import ensure_cover_local
        from .image_store import LocalImageStore

        ensure_cover_local(storage, LocalImageStore(), comic_id, detail.cover_url)
    except Exception:
        logger.exception("封面落盘流程异常 comic_id=%s", comic_id)

    for idx, chapter in enumerate(detail.chapters):
        chapter_id, chapter_new = storage.upsert_chapter(comic_id, chapter)
        if chapter_new:
            stats.new_chapters += 1
        try:
            pages = adapter.fetch_chapter_pages(detail, chapter)
            if pages:
                storage.upsert_pages(chapter_id, pages)
                # 采集入库后自动转存「最新一话的第 1 页」（detail.chapters 首个为最新话）
                # 用于通量验证：只下载最新章第1页，其余页保持未转存（占位）。
                if idx == 0:
                    try:
                        from .image_service import transfer_latest_first_page
                        from .image_store import LocalImageStore

                        transfer_latest_first_page(
                            storage, LocalImageStore(), comic_id, chapter_id
                        )
                    except Exception:
                        logger.exception(
                            "自动转存最新章第1页异常 comic_id=%s chapter_id=%s",
                            comic_id, chapter_id,
                        )
        except Exception:
            # 章节图片失败不阻塞整部漫画入库，仅记录并继续
            stats.failed += 1
            logger.warning("章节 %s(%s) 图片抓取失败", chapter.title, chapter.source_chapter_id)


def full_sync(adapter: CrawlerAdapter, storage: Storage) -> SyncStats:
    """全量扫描：语义与增量一致（同为列表+详情补全），生产环境可在此
    追加"失效校验"（重抓已标记失效的章节、比对 content_hash 变更）。"""
    return incremental_sync(adapter, storage, mode="full")


def inspect_sync(storage: Storage, image_store=None) -> dict[str, int]:
    """失效巡检（架构方案 §2.2 第三类任务，每小时）：

    1. 未转存页 → 触发懒转存；
    2. 已转存页 → 校验 OSS 对象是否存在，缺失则标记失效并尝试恢复；
    3. 恢复失败的失效页保持 '失效'，由下次巡检或人工处理。

    返回统计：{checked, transferred, verified, recovered, invalid}
    """
    if image_store is None:
        from .image_store import LocalImageStore

        image_store = LocalImageStore()

    from .image_service import lazy_transfer

    stats = {"checked": 0, "transferred": 0, "verified": 0, "recovered": 0, "invalid": 0}

    # 1) 未转存 → 转存
    transfer_stats = lazy_transfer(storage, image_store)
    stats["transferred"] = transfer_stats["transferred"]

    # 2) 已转存 → 校验对象是否存在
    for row in storage.list_pages():
        stats["checked"] += 1
        oss_url = row["oss_url"]
        if not oss_url or row["cached_status"] != "已转存":
            continue
        key = oss_url  # file:// 或 http(s) URL；本地模拟直接比对路径
        if image_store.exists(key):
            stats["verified"] += 1
            continue
        # 对象丢失：先标记失效，再尝试用源 URL 恢复（演示中重转即恢复）
        storage.mark_page_invalid(row["page_id"])
        stats["invalid"] += 1
        from .image_service import build_image_key

        key = build_image_key(row["comic_id"], row["chapter_id"], row["page_no"])
        try:
            data = image_store.get(key)
        except Exception:
            data = None
        if data is None:
            from .image_service import default_downloader

            data = default_downloader(row["source_url"], key)
        image_store.put(key, data)
        # 回填图库内相对 key（与 lazy_transfer 一致），保持 oss_url 全库统一形态
        storage.mark_page_cached(row["page_id"], key)
        stats["recovered"] += 1

    logger.info("失效巡检完成: %s", stats)
    return stats


class SyncScheduler:
    """本地轮询式定时调度（架构方案 §2.2 / §4.4 的轻量落地）。

    生产环境由 cron / 分布式调度 + MQ 触发；此处用轮询 tick() 实现同等的
    「增量高频 / 全量低频 / 失效巡检」节奏，单机演示即可跑通：
    - 增量：每源按 SourceConfig.crawl_interval_seconds 轮询（源站一更新，本站几分钟内可见）；
    - 全量：每日 FULL_SYNC_HOUR 点后每源跑一次（当日不重复）；
    - 巡检：按固定间隔扫描图片存储（转存/校验/恢复）。

    tick(now) 可注入时间，便于单元测试推进时钟。
    """

    FULL_SYNC_HOUR = 3  # 每日全量扫描时间点（与 SourceConfig.full_sync_cron 对齐）

    def __init__(
        self,
        adapters: dict[str, CrawlerAdapter],
        storage: Storage,
        sources,
        inspect_interval_seconds: int = 3600,
        image_store=None,
    ) -> None:
        self.adapters = adapters
        self.storage = storage
        self.sources = {s.name: s for s in sources}
        self.inspect_interval = inspect_interval_seconds
        self.image_store = image_store  # 巡检用图片存储；None 时用默认本地实现
        self._last_incremental: dict[str, float] = {}
        self._last_full_date: dict[str, str] = {}  # 每源每日全量只跑一次
        self._last_inspect: float | None = None

    def tick(self, now: float | None = None) -> list[str]:
        """推进一次调度检查，返回本次实际执行的任务名列表。"""
        now = time.time() if now is None else now
        executed: list[str] = []

        for name, source in self.sources.items():
            if not source.enabled:
                continue
            adapter = self.adapters.get(name)
            if adapter is None:
                continue

            # 1) 增量轮询：距上次执行 >= crawl_interval_seconds
            last_inc = self._last_incremental.get(name)
            if last_inc is None or now - last_inc >= source.crawl_interval_seconds:
                try:
                    incremental_sync(adapter, self.storage)
                except Exception:
                    logger.exception("[%s] 增量同步失败", name)
                self._last_incremental[name] = now
                executed.append(f"{name}::incremental")

            # 2) 每日全量：跨过 FULL_SYNC_HOUR 后当日仅执行一次
            today = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
            if (
                self._last_full_date.get(name) != today
                and datetime.fromtimestamp(now).hour >= self.FULL_SYNC_HOUR
            ):
                try:
                    full_sync(adapter, self.storage)
                except Exception:
                    logger.exception("[%s] 全量同步失败", name)
                self._last_full_date[name] = today
                executed.append(f"{name}::full")

        # 3) 失效巡检：独立于源站，固定间隔
        if self._last_inspect is None or now - self._last_inspect >= self.inspect_interval:
            try:
                inspect_sync(self.storage, image_store=self.image_store)
            except Exception:
                logger.exception("失效巡检失败")
            self._last_inspect = now
            executed.append("inspect")

        return executed
