"""日志上下文（当前后台任务的 id / 类型）—— 让每条日志自动带上"属于哪个任务"。

为什么需要：管理台日志查询页要能"按任务查"（某次转存跑了什么、失败在哪几话）。任务 id
由 `services.tasks` 生成，但采集 / 转存 / 巡检的代码在 crawler 包里，拿不到 api 侧的变量 ——
所以用一个 `contextvars.ContextVar` 做传递：任务线程进来时 `bind_task(...)`，之后该线程里
任何日志都自动带上它。

⚠️ **不跨线程传播**：`ThreadPoolExecutor` 的工作线程不会继承父线程的 context。
所以"线程池里只收集、回到主线程才写日志"的写法才安全（转存的失败明细就是聚合后回主线程写的）；
若将来出现"在工作线程里直接打日志且必须带任务 id"的场景，需要显式把 `current()` 塞进
`extra={"log_fields": {...}}`。

任务号的生成也放在这里（`new_task_id`）—— 它同时喂给 `log_record.task_id` 与 `admin_task.task_id`，
而这两个写者分别在 api 与 comic-scheduler 两个进程里，必须**同一套规则**。
"""
from __future__ import annotations

import contextvars
import secrets
import time

_CURRENT: contextvars.ContextVar[dict] = contextvars.ContextVar("comic_log_ctx", default={})


def bind_task(task_id: str, task_type: str) -> contextvars.Token:
    """把当前任务的 id / 类型绑到本线程（返回 token，可用于恢复）。"""
    return _CURRENT.set({"task_id": str(task_id or ""), "task_type": str(task_type or "")})


def current() -> dict:
    """当前线程绑定的任务信息（没绑定则返回空 dict）。"""
    return _CURRENT.get()


def new_task_id(prefix: str) -> str:
    """造任务号：`<类型>-<秒级时间戳>-<6 位随机>`。

    形状要求：一眼能看出**类型**与**大致时间**（日志页与任务列表都靠它认）。
    ⚠️ 随机后缀是必需的，不是装饰：任务号在 `admin_task` 上有唯一键，而
    ① 定时执行器一轮接一轮地跑、② api 与执行器是不同进程 —— 只用"秒级时间戳"会撞号
    （实测：同一秒内第二次插库直接 `Duplicate entry`，第二轮的收尾还会覆盖第一轮的行）。
    早先的进程内自增计数器同样不行：重启归零，会与历史任务撞。
    """
    return f"{prefix}-{int(time.time())}-{secrets.token_hex(3)}"
