"""编排层：决定「何时跑」与「怎么跑一次」。

| 文件 | 职责 |
|---|---|
| `sync.py` | 采集主流程：增量轮询 / 全量扫描（`incremental_sync` / `full_sync`） |
| `ondemand.py` | 按需导入：收录用户指定的单部作品（`import_comic`） |
| `heal.py` | 失效巡检与封面自愈（`inspect_sync` / `heal_covers`） |
| `schedule.py` | 管理台「定时任务」配置读写 + 由它推导的时刻（`is_due` / `next_run_at`） |
| `schedule_state.py` | 定时任务运行态与「立即执行」触发文件（两个进程各写各的） |
| `runner.py` | 「跑一轮」的唯一定义（`sync_source` / `run_round`），执行器与 api 共用 |
| `cron.py` | 5 段 cron 表达式的解析与时刻计算（`parse_cron` / `CronSpec`） |

本层**单向依赖**下面的通用层、源站层与存储层，不被它们反向引用。
"""
from .cron import DEFAULT_CRON, CronSpec, parse_cron
from .heal import heal_covers, inspect_sync
from .ondemand import (
    ComicNotFound,
    ComicRestricted,
    OnDemandError,
    UnsupportedCapability,
    import_comic,
    resolve_brief,
)
from .runner import default_sources, run_round, sync_source
from .schedule import (
    ACTIONS,
    ACTION_INSPECT,
    ACTION_SYNC,
    GRACE_SECONDS,
    MODES,
    ScheduleConfig,
    is_due,
    load_schedule_config,
    next_run_at,
    save_schedule_config,
)
from .schedule_state import (
    consume_run_now,
    load_schedule_state,
    request_run_now,
    save_schedule_state,
)
from .sync import FIRST_CHAPTERS, MAX_PAGES_PER_SYNC, SyncSession, full_sync, incremental_sync

__all__ = [
    "incremental_sync",
    "full_sync",
    "SyncSession",
    "import_comic",
    "resolve_brief",
    "OnDemandError",
    "ComicNotFound",
    "ComicRestricted",
    "UnsupportedCapability",
    "inspect_sync",
    "heal_covers",
    "MAX_PAGES_PER_SYNC",
    "FIRST_CHAPTERS",
    # 定时任务：配置 + 时刻推导 + 运行态/触发 + 一轮执行
    "ScheduleConfig",
    "load_schedule_config",
    "save_schedule_config",
    "MODES",
    "ACTIONS",
    "ACTION_SYNC",
    "ACTION_INSPECT",
    "GRACE_SECONDS",
    "is_due",
    "next_run_at",
    "load_schedule_state",
    "save_schedule_state",
    "request_run_now",
    "consume_run_now",
    "sync_source",
    "run_round",
    "default_sources",
    "DEFAULT_CRON",
    "CronSpec",
    "parse_cron",
]
