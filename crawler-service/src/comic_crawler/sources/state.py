"""管理台「数据源开关」状态的持久化 —— **读写都归采集层**。

状态文件存的是各源 `enabled` 的**管理台覆盖态**（默认值来自 `SOURCES[].enabled`），
落盘位置见 `paths.SOURCE_STATE_FILE`（`<data>/source_state.json`，与图库同一个运行时
数据目录），env `COMIC_STATE_FILE` 可覆盖。

⚠️ **为什么读写在这里、而不是 api-service**（2026-09-24 调整）：这个文件描述的是
**采集源的启停** —— 属于采集域的运行时状态，api 只是它的编辑器。此前路径由采集层
给出、读写却全在 api 侧，等于「谁拥有这个文件」在代码里没有边界；收进来之后 api
不再需要知道它的路径与格式（只调 `load_source_state` / `save_source_state`）。

⚠️ env 覆盖**只接受绝对路径**（相对路径忽略并回落默认）：容器里 wheel 装进
site-packages 后，`paths` 推出来的默认位置落在镜像内部，必须由 env 指到 bind 的 `/data`。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from comic_core.paths import SOURCE_STATE_FILE
from . import SOURCES

logger = logging.getLogger(__name__)


def source_state_path() -> Path:
    """状态文件的实际位置：env `COMIC_STATE_FILE`（绝对路径）优先，否则用默认值。"""
    env = os.environ.get("COMIC_STATE_FILE", "").strip()
    if env and os.path.isabs(env):
        return Path(env)
    return SOURCE_STATE_FILE


def load_source_state() -> dict[str, bool]:
    """源开关的**生效态**：以 `SOURCES[].enabled` 为默认，叠加已保存的覆盖态。

    读不到 / 解析失败一律**回落默认态**（记日志、不抛）：开关文件损坏不该让服务起不来。
    """
    state: dict[str, bool] = {s.name: s.enabled for s in SOURCES}
    path = source_state_path()
    if not path.exists():
        return state
    try:
        saved = json.loads(path.read_text("utf-8"))
    except Exception:
        logger.exception("读取源开关状态失败，回落代码默认值：%s", path)
        return state
    if isinstance(saved, dict):
        for key, value in saved.items():
            if isinstance(value, bool):
                state[key] = value
    return state


def save_source_state(state: dict[str, bool]) -> None:
    """把覆盖态落盘（重启不丢）。写失败只记日志、不抛 —— 开关是尽力而为的操作。"""
    path = source_state_path()
    try:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        logger.exception("写入源开关状态失败：%s", path)
