"""管理台「后台任务」的 MySQL 读写（`admin_task` 表）。

两个使用方：

- **写入**：api-service 的 `services/tasks.py` —— 触发时插一行 `running`，结束时改成 `done`/`failed`；
- **读取**：同文件（管理台任务列表、前端 `taskId` 轮询、启动时的残留清理）。

为什么单独一个类、不并进 `MySQLStorage`：同 `log_store.py` 的理由 —— 任务与「漫画 / 章节 / 页」
是两套完全不同的数据，查询方式（按触发人 / 时间 / 状态）与保留策略都与主数据无关。

⚠️ 这是"任务表"从**进程内 dict 搬到库**的落点（2026-10-06），因此这里也负责两件以前不需要的事：

1. **JSON 列的编解码**（`result` / `params`）：写入 `json.dumps`，读出 `json.loads`；
2. **残留 `running` 的清理**（`reap_running`）：api 重启后把上一进程没跑完的任务标成中断。

时间语义与 `log_record` 一致：`DATETIME` 存**写入进程的本机时间**（容器必须配 `TZ`），
读出时由 `_row_out` 统一转成 ISO 字符串（与旧的内存版 `tasks.recent()` 出参形状保持一致）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from ._pool import pooled_conn
from ._util import _DSN

logger = logging.getLogger(__name__)

#: 入库列（`id` 自增，不在其中）
TASK_COLUMNS: tuple[str, ...] = (
    "task_id", "task_type", "status", "message", "result", "params",
    "user_id", "username", "started_at", "finished_at",
)

#: 查询返回的列（比入库多一个自增 id：同秒多条时的稳定排序兜底）
LIST_COLUMNS: tuple[str, ...] = ("id",) + TASK_COLUMNS

#: 单次最多返回多少条（防前端一次拉全表）
MAX_LIMIT = 200


def _row_out(row: dict) -> dict:
    """把一行（DB 原始值）转成给前端的形状：JSON 列解码、时间转 ISO 字符串。"""
    out = dict(row)
    for key in ("result", "params"):
        value = out.get(key)
        if isinstance(value, (str, bytes)):
            try:
                out[key] = json.loads(value)
            except Exception:   # 脏数据不该让整个列表接口 500
                logger.warning("admin_task.%s 不是合法 JSON，原样返回：%r", key, value)
    for key in ("started_at", "finished_at"):
        value = out.get(key)
        if isinstance(value, datetime):
            out[key] = value.isoformat(timespec="seconds")
    return out


class MySQLTaskStore:
    """`admin_task` 表的读写（连接来自**共享池**，见 `._pool`）。"""

    def __init__(self, dsn: dict | None = None) -> None:
        self.dsn = dsn or _DSN

    # ---------------- 写入 ----------------
    def insert(self, row: dict) -> None:
        """登记一个任务（状态由调用方给，通常 `running`）。`result`/`params` 自动序列化。"""
        payload = {c: row.get(c) for c in TASK_COLUMNS}
        for key in ("result", "params"):
            value = payload.get(key)
            if isinstance(value, (dict, list)):
                payload[key] = json.dumps(value, ensure_ascii=False)
        cols = ", ".join(TASK_COLUMNS)
        placeholders = ", ".join(["%s"] * len(TASK_COLUMNS))
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO admin_task ({cols}) VALUES ({placeholders})",
                    tuple(payload[c] for c in TASK_COLUMNS),
                )

    def finish(self, task_id: str, *, status: str, message: str = "",
               result=None) -> None:
        """收尾：写状态 / 摘要 / 结果 / 完成时间。"""
        payload = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else None
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE admin_task
                       SET status = %s, message = %s, result = %s, finished_at = %s
                       WHERE task_id = %s""",
                    (str(status), str(message or "")[:500], payload,
                     datetime.now(), str(task_id)),
                )

    def reap_running(self, before: datetime, message: str) -> list[dict]:
        """把 `before` 之前开始、且还挂在 `running` 的任务标成中断，**返回被处理的行**。

        返回行（而不是行数）是为了让调用方**补发消息**：这些任务也是"跑完了（被打断）"，
        消息中心必须看得到，否则它们只在「最近任务」里露头。

        ⚠️ 用 `started_at < before`（`before` = **本进程启动时刻**）而不是"所有 running"：
        将来真上了多 worker，A 的启动就不会把 B 正在跑的任务误标成中断。
        """
        cols = ", ".join(LIST_COLUMNS)
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {cols} FROM admin_task WHERE status = 'running' AND started_at < %s",
                    (before,),
                )
                rows = [_row_out(r) for r in cur.fetchall()]
                if not rows:
                    return []
                now = datetime.now()
                cur.execute(
                    """UPDATE admin_task
                       SET status = 'failed', message = %s, finished_at = %s
                       WHERE status = 'running' AND started_at < %s""",
                    (str(message)[:500], now, before),
                )
        stamp = now.isoformat(timespec="seconds")
        return [{**r, "status": "failed", "message": str(message)[:500], "finished_at": stamp}
                for r in rows]

    # ---------------- 读取 ----------------
    def get(self, task_id: str) -> dict | None:
        cols = ", ".join(LIST_COLUMNS)
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {cols} FROM admin_task WHERE task_id = %s", (str(task_id),))
                row = cur.fetchone()
                return _row_out(row) if row else None

    def recent(self, limit: int = 30, user_id: int | None = None) -> list[dict]:
        """最近的任务（默认全站；给 `user_id` 则只看某账号触发的）。"""
        size = max(1, min(int(limit or 30), MAX_LIMIT))
        where, params = "", []
        if user_id is not None:
            where, params = " WHERE user_id = %s", [int(user_id)]
        cols = ", ".join(LIST_COLUMNS)
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {cols} FROM admin_task{where} ORDER BY id DESC LIMIT %s",
                    params + [size],
                )
                return [_row_out(r) for r in cur.fetchall()]
