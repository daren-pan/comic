"""本地轮询式定时调度：增量高频 / 全量低频 / 失效巡检（架构方案 §2.2、§4.4）。

生产环境由 cron / 分布式调度 + MQ 触发；此处用 `tick()` 轮询实现同等节奏，
单机演示即可跑通。只负责「何时跑」，真正执行在 `sync.py` / `heal.py`。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from ..sources.base import CrawlerAdapter
from ..storage.base import Storage

from .heal import inspect_sync
from .sync import full_sync, incremental_sync

logger = logging.getLogger(__name__)

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
                inspect_sync(
                    self.storage,
                    image_store=self.image_store,
                    adapter_provider=lambda name: self.adapters.get(name),
                )
            except Exception:
                logger.exception("失效巡检失败")
            self._last_inspect = now
            executed.append("inspect")

        return executed
