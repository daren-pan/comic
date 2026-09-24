"""数据源开关状态与元信息。

开关的**默认值**来自 `comic_crawler.sources.SOURCES[].enabled`；管理台的覆盖态
持久化到 `config.SOURCE_STATE_FILE`（默认 `crawler-service/data/source_state.json` —— 与图库同一个
运行时数据目录；容器内是 bind 过来的 `/data/source_state.json`），重启不丢。
"""
from __future__ import annotations

import json
import logging

from core import config
from core.db import db

_logger = logging.getLogger("comic.admin")

_state: dict[str, bool] = {}


def _load() -> dict[str, bool]:
    state: dict[str, bool] = {}
    try:
        from comic_crawler.facade import SOURCES

        for s in SOURCES:
            state[s.name] = s.enabled
    except Exception:
        pass
    if config.SOURCE_STATE_FILE.exists():
        try:
            saved = json.loads(config.SOURCE_STATE_FILE.read_text("utf-8"))
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if isinstance(v, bool):
                        state[k] = v
        except Exception:
            _logger.exception("读取 source_state.json 失败")
    return state


def _save() -> None:
    try:
        config.SOURCE_STATE_FILE.write_text(
            json.dumps(_state, ensure_ascii=False, indent=2), "utf-8"
        )
    except Exception:
        _logger.exception("写入 source_state.json 失败")


_state = _load()


def is_enabled(name: str) -> bool:
    return _state.get(name, True)


def toggle(name: str) -> bool:
    """翻转并持久化；返回翻转后的状态。"""
    _state[name] = not _state.get(name, True)
    _save()
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
