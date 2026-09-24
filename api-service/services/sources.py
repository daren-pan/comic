"""数据源开关状态与元信息。

开关的**生效态**（代码默认值 + 管理台覆盖态）与**持久化**都由采集层负责 ——
`comic_crawler.facade` 的 `load_source_state` / `save_source_state`（状态文件与图库
同在运行时数据目录，见 `crawler-service/src/comic_crawler/sources/state.py`）。

本模块只做两件事：① 进程内缓存一份生效态（读接口高频调用，不值得每次重读文件）；
② 拼装管理台要的元信息（开关态 + 库内作品数 + 上次同步时间）。
"""
from __future__ import annotations

from core import bootstrap  # noqa: F401  —— 先完成 sys.path 引导（使 comic_crawler 可导入）
from core.db import db

#: 进程内缓存的生效态；只在 `toggle()` 里改，并同步落盘。
_state: dict[str, bool] = {}


def _load() -> None:
    from comic_crawler.facade import load_source_state

    global _state
    _state = load_source_state()


_load()


def is_enabled(name: str) -> bool:
    return _state.get(name, True)


def toggle(name: str) -> bool:
    """翻转并持久化；返回翻转后的状态。"""
    from comic_crawler.facade import save_source_state

    _state[name] = not _state.get(name, True)
    save_source_state(_state)
    return _state[name]


def meta() -> list[dict]:
    """给管理台的数据源列表：开关态 + 库内作品数 + 上次同步时间。

    作品数走 `count_comics_by_source()`（存储侧一条 `GROUP BY source`）——
    此前是 `list_comics(page_size=10000)` 拉整批行再在内存计数，代价随作品数线性增长、
    且过万即静默截断（见 AGENTS.md「硬性约定·性能」）。
    """
    from comic_crawler.facade import SOURCES

    count = db.count_comics_by_source()
    return [
        {
            "name": s.name,
            "enabled": _state.get(s.name, s.enabled),
            "priority": s.priority,
            "interval": s.crawl_interval_seconds,
            "comicCount": count.get(s.name, 0),
            "lastSync": db.get_last_sync_time(s.name),
        }
        for s in SOURCES
    ]
