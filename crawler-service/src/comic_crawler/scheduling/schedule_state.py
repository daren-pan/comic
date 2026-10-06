"""定时任务的**运行态**与「立即执行」触发文件 —— 读写都归采集层。

## 三个文件，各只有一个写者

执行器（`comic-scheduler` 进程）与 api 是**两个进程**，所以状态不能放内存、也不能共用一个文件：

| 文件 | 写者 | 读者 | 内容 |
|---|---|---|---|
| `schedule.json`（见 `schedule.py`） | api（页面保存） | 执行器（每 tick 读） | 配置：enabled / cron / sources / mode / limit / since |
| `schedule_state.json` | **执行器** | api（页面展示） | 运行态：running / 上次执行时刻与结果 / 本轮源 |
| `schedule_run_now.json` | **api**（「立即执行一次」按钮） | 执行器（**读到即删**） | 触发请求：requestedAt |

⚠️ **一文件一写者**是这里的核心约束：两个进程同时写同一个 JSON 会互相截断，
所以"触发"用独立文件（api 只写、执行器只删），而不是往状态文件里塞字段。

⚠️ env 覆盖**只接受绝对路径**（相对路径忽略并回落默认）—— 理由同 `sources/state.py`：
wheel 装进 site-packages 后默认位置落在镜像内部，容器里必须由 env 指到 bind 的 `/data`。

⚠️ 读失败一律**回落空状态**（记日志、不抛）：状态文件损坏不该让 api 页面或执行器起不来。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from comic_core.paths import SCHEDULE_STATE_FILE, SCHEDULE_TRIGGER_FILE

logger = logging.getLogger(__name__)

#: 运行态字段（缺字段时按这个补全，页面不必到处判 None）
_EMPTY_STATE: dict = {
    "running": False,
    "lastRunAt": None,     # ISO
    "lastRunTs": None,     # epoch 秒：判定「这一轮跑过没有」（执行器内部用，也便于排查）
    "lastStatus": None,    # running / done / failed
    "lastMessage": None,
    "lastSources": [],
    "lastTrigger": None,   # 定时 / 手动
    "lastTaskId": None,    # 本轮的任务号（能按它在管理台日志页筛日志）
    "cronError": None,     # 表达式非法时的原因（写者是执行器，api 只读来显示）
    "pid": None,           # 执行器进程号（运维排查用）
    "heartbeatAt": None,   # 最近一次心跳（判断执行器是否活着）
}


def _resolve(env_name: str, default: Path) -> Path:
    env = os.environ.get(env_name, "").strip()
    if env and os.path.isabs(env):
        return Path(env)
    return default


def state_path() -> Path:
    """运行态文件位置：env `COMIC_SCHEDULE_STATE_FILE`（绝对路径）优先。"""
    return _resolve("COMIC_SCHEDULE_STATE_FILE", SCHEDULE_STATE_FILE)


def trigger_path() -> Path:
    """「立即执行」触发文件位置：env `COMIC_SCHEDULE_TRIGGER_FILE`（绝对路径）优先。"""
    return _resolve("COMIC_SCHEDULE_TRIGGER_FILE", SCHEDULE_TRIGGER_FILE)


def load_schedule_state() -> dict:
    """读运行态（**始终返回完整字段的 dict**）。"""
    state = dict(_EMPTY_STATE)
    path = state_path()
    if not path.exists():
        return state
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:
        logger.exception("读取定时任务运行态失败，回落空状态：%s", path)
        return state
    if isinstance(raw, dict):
        for key in _EMPTY_STATE:
            if key in raw:
                state[key] = raw[key]
    return state


def save_schedule_state(state: dict) -> None:
    """写运行态（**尽力而为**：写失败只记日志，不打断执行器主循环）。"""
    merged = dict(_EMPTY_STATE)
    merged.update({k: v for k, v in state.items() if k in _EMPTY_STATE})
    try:
        state_path().write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), "utf-8"
        )
    except Exception:
        logger.exception("写入定时任务运行态失败：%s", state_path())


def request_run_now(user: dict | None = None) -> dict:
    """api 侧：写一条「立即执行」请求（页面按钮）。

    与状态文件分开写，所以不会和正在跑的轮次抢同一个文件。写失败**要抛** ——
    用户点了按钮却没请求出去，比"静默什么都没发生"更该看到报错。

    `user` = 点按钮的那个账号（`{"id":…, "username":…}`）：一并写进请求，执行器会把它
    记进任务表 —— 于是"立即执行"这一轮也算**与人绑定**，而不是笼统算成"系统"。
    """
    payload = {
        "requestedAt": datetime.now().isoformat(timespec="seconds"),
        "userId": (user or {}).get("id"),
        "username": (user or {}).get("username") or "",
    }
    trigger_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
    )
    return payload


def consume_run_now() -> dict | None:
    """执行器侧：取出并**删除**触发请求；没有则返回 `None`。"""
    path = trigger_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text("utf-8"))
    except Exception:
        logger.exception("读取「立即执行」请求失败，按已消费处理：%s", path)
        payload = None
    try:
        path.unlink()
    except Exception:
        logger.exception("删除「立即执行」请求失败：%s", path)
    return payload if isinstance(payload, dict) else {"requestedAt": None}
