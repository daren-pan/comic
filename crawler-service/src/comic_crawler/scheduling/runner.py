"""定时任务「跑一轮」的**唯一实现** —— 执行器与 api 共用同一个函数。

为什么单独成文件：管理台「触发采集」（手动、单源）与定时执行器（cron、按配置多源）
必须用**同一套**采集语义 —— 存储句柄、`mode`/`limit`/`since`、统计口径。收在这里之后：

| 调用方 | 入口 |
|---|---|
| 定时执行器（`comic-scheduler` 进程） | `run_round(config, trigger)` |
| api 的手动触发（`admin_jobs.sync_job`） | `sync_source(source, mode, limit, since)`（薄包装） |

于是"除触发方式外其他都一致"是**构造上成立**的，不靠人工对齐两套逻辑。
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from comic_core import logctx
from comic_core.images.store import LocalImageStore
from comic_core.storage.mysql import MySQLStorage

from ..sources import SOURCES, create_adapter
from .heal import inspect_sync
from .schedule import ACTION_INSPECT, ACTION_SYNC
from .sync import full_sync, incremental_sync

logger = logging.getLogger(__name__)


def sync_source(source: str, mode: str = "incremental", limit: int | None = None,
                since=None) -> dict:
    """采集**一个源**一次，返回 `{stats, summary, db}`。

    这是「执行一次采集」的唯一定义：管理台手动触发与定时执行器都走它。
    """
    storage = MySQLStorage()
    adapter = create_adapter(source)
    if mode == "full":
        stats = full_sync(adapter, storage, limit=limit, since=since)
    else:
        stats = incremental_sync(adapter, storage, limit=limit, since=since)
    return {"stats": asdict(stats), "summary": stats.summary(), "db": storage.stats()}


def default_sources() -> list[str]:
    """配置没点名源时用哪些 —— 全部「**代码里默认启用**」的源。

    ⚠️ 这**不是**管理台那张开关（`source_state.json`）：定时任务按"参数即准入"运行，
    页面留空就取这里。`mangadex` 因 AUP 非商用被代码默认关闭，故不在其中；
    要采它必须在页面上显式点名。
    """
    return [s.name for s in SOURCES if s.enabled]


def run_round(config, trigger: str, task_id: str | None = None) -> dict:
    """按配置跑一轮 —— 干什么由 `config.action` 决定（`sync` 逐源采集 / `inspect` 失效巡检）。

    返回统一形状（采集与巡检都一样，方便执行器与任务表直接消费）：

    ```python
    {"trigger": "定时", "action": "sync", "sources": [...],
     "results": {...}, "ok": 2, "failed": [...], "summary": "定时：成功 2/2 个源"}
    ```

    `summary` 是一行人话，给管理台任务列表 / 运行态直接用 —— 调用方不必再关心动作差异。
    传 `task_id` 时把它绑到日志上下文 —— 这一轮的日志都能按任务号在管理台日志页筛出来。
    """
    if task_id:
        logctx.bind_task(task_id, "schedule")
    action = getattr(config, "action", ACTION_SYNC)
    if action == ACTION_INSPECT:
        return _inspect_round(config, trigger)
    return _sync_round(config, trigger)


def _sync_round(config, trigger: str) -> dict:
    """逐源采集一轮（默认动作）。单源失败**不拖累**其他源：继续跑完并把原因收进结果。"""
    names = list(config.sources) or default_sources()
    results: dict[str, dict] = {}
    ok = 0
    for name in names:
        try:
            out = sync_source(name, config.mode, config.limit, config.since)
            # 带上 stats（含 `updated` 更新明细）：执行器收尾后据此**通知收藏者**
            # （见 daemon._notify_fans）；明细随 result 落任务表 JSON 列，管理台可查。
            results[name] = {"ok": True, "summary": out["summary"], "stats": out.get("stats") or {}}
            ok += 1
        except Exception as exc:
            logger.exception("定时任务：源 %s 采集失败", name)
            results[name] = {"ok": False, "error": str(exc)}
    failed = [n for n, r in results.items() if not r["ok"]]
    summary = f"{trigger}：成功 {ok}/{len(names)} 个源" + (f"，失败 {'、'.join(failed)}" if failed else "")
    return {
        "trigger": trigger,
        "action": ACTION_SYNC,
        "sources": names,
        "mode": config.mode,
        "results": results,
        "ok": ok,
        "failed": failed,
        "summary": summary,
    }


def _inspect_round(config, trigger: str) -> dict:
    """失效巡检一轮：转存未转存页 + **全表**校验已转存对象 + 恢复丢失。

    ⚠️ 与管理台手动「失效巡检」的差别：**不含**第 3 步「全库封面自愈」（那一步偏重，
    留给手动按钮；巡检频率高，不该每次都多打源站请求 —— 见 `schedule.py` 的说明）。
    `mode`/`limit` 对巡检无意义；`since` 作为**转存**窗口下界（校验始终全表）。
    """
    storage = MySQLStorage()
    store = LocalImageStore()
    source = config.sources[0] if len(config.sources) == 1 else None
    stats = inspect_sync(
        storage,
        image_store=store,
        source=source,
        since=config.since,
        until=None,
        adapter_provider=create_adapter,
    ) or {}
    summary = (
        f"{trigger}：巡检 校验 {stats.get('checked', 0)}"
        f" | 转存 {stats.get('transferred', 0)}"
        f" | 恢复 {stats.get('recovered', 0)}"
        f" | 失效 {stats.get('invalid', 0)}"
    )
    return {
        "trigger": trigger,
        "action": ACTION_INSPECT,
        "sources": [source] if source else [],
        "results": {"inspect": stats},
        "ok": 1,
        "failed": [],
        "summary": summary,
        "stats": stats,
    }
