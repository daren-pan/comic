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

from core import config  # noqa: F401  —— 先完成 sys.path 引导（使 comic_crawler 可导入）
from comic_crawler import logctx

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
        # 把「当前任务」绑到本线程的日志上下文：之后这个线程里打的日志都会自动带上
        # task_id / task_type，落到 log_record 表供管理台「按任务查」（见 comic_crawler.logctx）
        logctx.bind_task(task_id, task_type)
        try:
            result = fn()
            _TASKS[task_id].update(
                status="done", message="ok", result=result,
                finishedAt=datetime.now().isoformat(timespec="seconds"),
            )
        except Exception as exc:
            # ⚠️ 只打任务 id（如 import-9-1789523396）在日志页定位不到任何东西 —— 必须把
            # 异常摘要带上：「导入哪一部作品失败」的信息就在异常消息里
            # （如「…按合规约定不收录：《XXX》」）。结构化字段补 reason 供按原因筛选；
            # 更细的源侧上下文（comic_title 等）由 crawler 侧再记一条（见 scheduling.ondemand）。
            _logger.exception(
                "后台任务 %s 失败：%s", task_id, exc,
                extra={"log_fields": {"event": "task.fail", "reason": str(exc)}},
            )
            _TASKS[task_id].update(
                status="failed", message=str(exc), result=None,
                finishedAt=datetime.now().isoformat(timespec="seconds"),
            )

    threading.Thread(target=_runner, daemon=True).start()


def get(task_id: str) -> dict | None:
    return _TASKS.get(task_id)


def recent(limit: int = 30) -> list[dict]:
    return sorted(_TASKS.values(), key=lambda t: t["startedAt"], reverse=True)[:limit]
