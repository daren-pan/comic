"""管理台「定时任务」的**接口侧** —— 只管配置与展示，**不跑采集**。

采集由独立进程 **`comic-scheduler`** 负责（2026-10-06 从 api 进程里搬出去，
见 `comic-scheduler/README.md`）。两个进程只通过运行时数据目录里的三个文件交换：

| 文件 | 写者 | 读者 |
|---|---|---|
| `schedule.json` | **本模块**（页面保存） | 执行器 |
| `schedule_state.json` | 执行器 | **本模块**（页面展示） |
| `schedule_run_now.json` | **本模块**（「立即执行一次」按钮） | 执行器（读到即删） |

于是本模块只剩四件事：**读配置 / 存配置（含 cron 语义校验）/ 读运行态并算「下次执行」/ 写触发请求**。

⚠️ 执行器是独立进程，所以"它在不在"本身是个要展示的状态 —— `status()` 里带 `heartbeatAt`
与算好的 `executorAlive`：执行器没起来时页面必须能看出来，否则会以为"配了就该跑"。

⚠️ 依赖面：只允许 `from comic_crawler.facade import ...`（**不得** `from comic_crawler import facade`，
那是穿透子模块）—— 见 `tests/test_crawler_boundary.py`。故这里按需在函数内逐个取名字
（与 `services/ondemand.py`、`services/admin_jobs.py` 同一惯例，导入期也不拉起采集包）。
"""
from __future__ import annotations

import logging
from datetime import datetime

from core import bootstrap  # noqa: F401  —— 先完成 sys.path 引导（使 comic_crawler 可导入）

logger = logging.getLogger("comic.admin.schedule")

#: 心跳超过这个秒数就算执行器不在线（执行器空闲时每 60s 刷一次心跳）
_ALIVE_SECONDS = 150


def status() -> dict:
    """页面要的全部状态：配置 + 运行态（执行器写的）+ 下次执行时刻 + 执行器是否在线。"""
    from comic_crawler.facade import (
        default_sources,
        load_schedule_config,
        load_schedule_state,
        next_run_at,
    )

    now = datetime.now()
    config = load_schedule_config()
    state = load_schedule_state()

    cron_error = None
    next_run = None
    try:
        next_run = next_run_at(config, now)
    except ValueError as exc:
        # 保存路径上已经挡过一道；这里再解析一次是为了"配置文件被手改坏"时页面也能显示原因
        cron_error = str(exc)

    heartbeat = state.get("heartbeatAt")
    alive = False
    if heartbeat:
        try:
            alive = (now - datetime.fromisoformat(heartbeat)).total_seconds() < _ALIVE_SECONDS
        except Exception:
            alive = False

    return {
        "config": config.to_dict(),
        "sources": list(config.sources) or default_sources(),
        "nextRunAt": next_run.isoformat(timespec="seconds") if next_run else None,
        "serverTime": now.isoformat(timespec="seconds"),
        "running": bool(state.get("running")),
        "lastRunAt": state.get("lastRunAt"),
        "lastStatus": state.get("lastStatus"),
        "lastMessage": state.get("lastMessage"),
        "lastTaskId": state.get("lastTaskId"),
        "lastSources": state.get("lastSources") or [],
        # 表达式非法：优先用本进程刚解析出的原因，否则用执行器记的
        "cronError": cron_error or state.get("cronError"),
        "executorAlive": alive,
        "heartbeatAt": heartbeat,
        "executorPid": state.get("pid"),
    }


def update(payload: dict) -> dict:
    """保存配置并返回新状态。

    **cron 的语义校验在这里**（`parse_cron`）：非法就把 `ValueError` 抛给路由层 ——
    由路由转成 400 并带上段名与原因（策略类校验要给中文提示，见 `schemas.py` 的说明）。
    形状（非空/长度）由 `schemas.AdminScheduleBody` 先挡一道。
    """
    from comic_crawler.facade import ScheduleConfig, parse_cron, save_schedule_config

    cron = " ".join(str(payload.get("cron") or "").split())
    parse_cron(cron)   # 非法即抛，交给路由层转 400

    save_schedule_config(
        ScheduleConfig(
            enabled=bool(payload.get("enabled", False)),
            cron=cron,
            action=payload.get("action") or "sync",
            sources=list(payload.get("sources") or []),
            mode=payload.get("mode") or "incremental",
            limit=payload.get("limit"),
            since=payload.get("since"),
        )
    )
    return status()


def run_now(user: dict | None = None) -> dict:
    """写一条「立即执行」请求，返回 `{requested, requestedAt, userId, username}`。

    执行器（独立进程）在下一个 tick（≤5s）内看到就跳一轮；结果体现在 `status()` 的
    `running` / `lastRunAt` / `lastMessage`，同时**记进任务表** `admin_task`
    （`task_type=schedule`）——`user` 会一并写进请求文件，所以这一轮归属于点按钮的人。

    写失败**让它抛**（路由层转 500）：点了按钮却什么都没发生，是最难排查的那类问题。
    """
    from comic_crawler.facade import request_run_now

    payload = request_run_now(user)
    return {"requested": True, **payload}
