"""编排层：决定「何时跑」与「怎么跑一次」。

| 文件 | 职责 |
|---|---|
| `sync.py` | 采集主流程：增量轮询 / 全量扫描（`incremental_sync` / `full_sync`） |
| `heal.py` | 失效巡检与封面自愈（`inspect_sync` / `heal_covers`） |
| `scheduler.py` | 本地轮询式定时调度（`SyncScheduler.tick()`） |

本层**单向依赖**下面的通用层、源站层与存储层，不被它们反向引用。
"""
from .heal import heal_covers, inspect_sync
from .scheduler import SyncScheduler
from .sync import FIRST_CHAPTERS, MAX_PAGES_PER_SYNC, SyncSession, full_sync, incremental_sync

__all__ = [
    "incremental_sync",
    "full_sync",
    "SyncSession",
    "SyncScheduler",
    "inspect_sync",
    "heal_covers",
    "MAX_PAGES_PER_SYNC",
    "FIRST_CHAPTERS",
]
