"""后台任务注册表。

采集 / 转存是耗时动作，走后台线程执行，前端凭 `taskId` 轮询进度
（`GET /api/admin/tasks/{id}`），避免 HTTP 请求长时间挂起。

任务表存在内存里（进程重启即清空），对演示用途足够；生产可换 Redis/DB。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

_logger = logging.getLogger("comic.admin")

_TASKS: dict[str, dict] = {}
_SEQ = 0
_LOCK = threading.Lock()


def new_task_id(prefix: str) -> str:
    global _SEQ
    with _LOCK:
        _SEQ += 1
        return f"{prefix}-{_SEQ}-{int(time.time())}"


def run_task(task_id: str, task_type: str, fn) -> None:
    """登记任务并起后台线程执行 `fn()`，把返回值/异常写回任务表。"""
    _TASKS[task_id] = {
        "id": task_id,
        "type": task_type,
        "status": "running",
        "message": "运行中",
        "result": None,
        "startedAt": datetime.now().isoformat(timespec="seconds"),
        "finishedAt": None,
    }

    def _runner():
        try:
            result = fn()
            _TASKS[task_id].update(
                status="done", message="ok", result=result,
                finishedAt=datetime.now().isoformat(timespec="seconds"),
            )
        except Exception as exc:
            _logger.exception("后台任务 %s 失败", task_id)
            _TASKS[task_id].update(
                status="failed", message=str(exc), result=None,
                finishedAt=datetime.now().isoformat(timespec="seconds"),
            )

    threading.Thread(target=_runner, daemon=True).start()


def get(task_id: str) -> dict | None:
    return _TASKS.get(task_id)


def recent(limit: int = 30) -> list[dict]:
    return sorted(_TASKS.values(), key=lambda t: t["startedAt"], reverse=True)[:limit]
