"""后台任务注册表（**落库版**，表 `admin_task`）。

采集 / 转存 / 巡检 / 按需导入都是耗时动作，走后台线程执行，前端凭 `taskId` 轮询
（`GET /api/admin/tasks/{id}`），避免 HTTP 请求长时间挂起
（前端 `request.ts` 的 `TIMEOUT = 10000`，同步等结果必被掐断）。

⚠️ **2026-10-06 起，任务表从进程内 dict 搬到 MySQL**（`admin_task`，读写实现见
`comic_core.storage.mysql.task_store`）。搬的理由就两条，都是原实现做不到的：

1. **不丢**：api 重启/重部署后任务还在，前端那个 `taskId` 仍查得到；上一进程没跑完的
   `running` 由 `reap_stale()` 在启动时标成「服务重启，任务中断」——而不是留下一行永远
   转圈的假状态；
2. **与账号绑定**：`run_task(..., user=...)` 记下**是谁点的**（`user_id` + `username`），
   任务列表可按账号筛、出问题能追溯到人。

⚠️ 任务的**执行仍在 api 进程内**的后台线程（刻意的，见 `docs/deploy.md` §8：手动触发是
"人等着看结果"的短任务，与常驻的定时执行不同 —— 后者在独立进程 `comic-scheduler` 里）。
本模块只管"任务的状态与归属"，不负责采集本身。
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from core import bootstrap  # noqa: F401  —— 先完成 sys.path 引导（使 comic_core 可导入）
from comic_core import logctx

_logger = logging.getLogger("comic.admin")

#: 残留任务被标成中断时的说明（启动时用）
INTERRUPTED = "服务重启，任务中断"

#: DB 列 → 前端契约（驼峰）。⚠️ 形状必须与改造前的**内存版**一致（前端 `AdminTask` 就按这个读），
#: 只多了触发账号 `userId` / `username` 与入参快照 `params`。
_CONTRACT_KEYS: dict[str, str] = {
    "task_id": "id",
    "task_type": "type",
    "status": "status",
    "message": "message",
    "result": "result",
    "params": "params",
    "user_id": "userId",
    "username": "username",
    "started_at": "startedAt",
    "finished_at": "finishedAt",
}


def _to_contract(row: dict | None) -> dict | None:
    """DB 行 → 前端契约（驼峰）。自增 `id` 不外露 —— 对外的主键是任务号 `task_id`。"""
    if row is None:
        return None
    return {out: row.get(src) for src, out in _CONTRACT_KEYS.items()}


def _store():
    """任务表的读写句柄（**测试可替换**：把它换成一个内存假实现即可脱离 MySQL 断言逻辑）。"""
    from comic_core.storage.mysql.task_store import MySQLTaskStore

    return MySQLTaskStore()


def _messages():
    """消息中心的发布句柄（**测试可替换**：换掉它就不必真的发消息/连库）。"""
    from services import messages

    return messages


def new_task_id(prefix: str) -> str:
    """造任务号 —— 实现收口在 `comic_core.logctx`（api 与 `comic-scheduler` 两个进程共用一份规则）。"""
    return logctx.new_task_id(prefix)


def _finish(task_id: str, status: str, message: str, result=None) -> None:
    """收尾：写库（**尽力而为**：写不进去只记日志，别让后台线程再崩一次）+ 往消息中心发一条。

    消息走**进程内**的服务函数（同进程不必自己调自己一次 HTTP）；独立进程
    `comic-scheduler` 那份走 `POST /api/messages`（见 `comic_core/notify.py`）。
    """
    try:
        _store().finish(task_id, status=status, message=message, result=result)
    except Exception:
        _logger.exception("任务 %s 收尾写库失败（状态 %s）", task_id, status)
    _publish(task_id)


def _publish(task_id: str) -> None:
    """把这一条任务发进消息中心（发失败不影响任务本身）。"""
    try:
        row = _store().get(task_id)
        if not row:
            return
        # 任务表出参是 snake_case，消息构造器吃的也是这一份，不必再转契约
        _messages().publish_task({
            "task_id": row.get("task_id"),
            "task_type": row.get("task_type"),
            "status": row.get("status"),
            "message": row.get("message"),
            "result": row.get("result"),
            "params": row.get("params"),
            "user_id": row.get("user_id"),
            "username": row.get("username"),
            "finished_at": row.get("finished_at"),
        })
    except Exception:
        _logger.exception("任务 %s 的消息发布失败（不影响任务）", task_id)


def execute(task_id: str, task_type: str, fn) -> None:
    """任务体：绑日志上下文 → 跑 `fn()` → 把结果/异常写回库。

    ⚠️ 单独抽成函数（而不是塞在线程里的闭包）：便于**同步单测**——测试直接调它，
    不必去等线程、也不必连库（换掉 `_store()` 即可）。
    """
    # 把「当前任务」绑到本线程的日志上下文：之后这个线程里打的日志都会自动带上
    # task_id / task_type，落到 log_record 表供管理台「按任务查」（见 comic_core.logctx）
    logctx.bind_task(task_id, task_type)
    try:
        result = fn()
        _finish(task_id, "done", "ok", result)
    except Exception as exc:
        # ⚠️ 只打任务 id（如 import-9-1789523396）在日志页定位不到任何东西 —— 必须把
        # 异常摘要带上：「导入哪一部作品失败」的信息就在异常消息里
        # （如「…按合规约定不收录：《XXX》」）。结构化字段补 reason 供按原因筛选；
        # 更细的源侧上下文（comic_title 等）由 crawler 侧再记一条（见 scheduling.ondemand）。
        _logger.exception(
            "后台任务 %s 失败：%s", task_id, exc,
            extra={"log_fields": {"event": "task.fail", "reason": str(exc)}},
        )
        _finish(task_id, "failed", str(exc), None)


def register(task_id: str, task_type: str, *, user: dict | None = None,
             params: dict | None = None) -> None:
    """登记任务（落库 `running`，含触发账号与入参快照）。

    与执行分开：`run_task` = 登记 + 起后台线程；测试直接 `register` + `execute`（同步、无线程）。
    """
    _store().insert({
        "task_id": task_id,
        "task_type": task_type,
        "status": "running",
        "message": "运行中",
        "result": None,
        "params": params or None,
        "user_id": (user or {}).get("id"),
        "username": (user or {}).get("username") or "",
        "started_at": datetime.now(),
        "finished_at": None,
    })


def run_task(task_id: str, task_type: str, fn, *, user: dict | None = None,
             params: dict | None = None) -> None:
    """登记任务（落库 `running`）并起后台线程执行。

    `user` = 触发者的账号字典（`core.security` 那套：含 `id` / `username`）；
    `params` = 入参快照（源 / 模式 / limit / since…），便于事后复盘"当时点的是什么"。
    """
    register(task_id, task_type, user=user, params=params)
    threading.Thread(target=execute, args=(task_id, task_type, fn), daemon=True).start()


def get(task_id: str) -> dict | None:
    """单个任务（前端契约形状）；查不到返回 `None`（路由转 404）。"""
    return _to_contract(_store().get(task_id))


def recent(limit: int = 30, user_id: int | None = None) -> list[dict]:
    """最近的任务（按 id 倒序 = 时间倒序）；给 `user_id` 则只看某账号触发的。"""
    return [_to_contract(r) for r in _store().recent(limit, user_id=user_id)]


def reap_stale(started_before: datetime | None = None) -> int:
    """把**本进程启动之前**开始、还挂在 `running` 的任务标成中断，返回处理条数。

    由 `main.py` 的 lifespan 在启动时调一次（尽力而为：数据库不通不该拦住 api 启动）。
    被处理的任务会**补发一条消息**（它们也是"跑完了，被打断"）—— 否则这些任务只在
    「最近任务」里露头，消息中心看不到。

    ⚠️ 用"启动时刻"而不是"所有 running"作界：将来真上了多 worker，A 的启动也不会把
    B 正在跑的任务误标成中断（这与 `docs/deploy.md` §8 的多进程改造前提一致）。
    """
    before = started_before or datetime.now()
    try:
        rows = _store().reap_running(before, INTERRUPTED)
    except Exception:
        _logger.exception("启动时清理残留任务失败（不影响服务启动）")
        return 0
    for row in rows:
        _publish(row["task_id"])
    return len(rows)
