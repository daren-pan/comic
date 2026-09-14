"""运行日志的 MySQL 读写（`log_record` 表）。

两个使用方：

- **写入**：`log_handler.MySQLLogHandler`（logging Handler）批量插入，见该模块说明；
- **读取**：api-service 的 `services/logs.py`（管理台「日志查询」页按条件筛）。

为什么单独一个类、不并进 `MySQLStorage`：日志与「漫画 / 章节 / 页」是两套完全不同的数据 ——
日志是"只看最近"的流水，查询方式（按级别/源站/任务/时间窗）和保留策略（`purge`）都与主数据无关，
混在一起会让存储类继续膨胀。

`build_filters()` 刻意做成**纯函数**（不碰连接）：单测里可以直接断言"每个条件生成的 SQL 与参数"，
不必连库。
"""
from __future__ import annotations

from datetime import datetime

from ._util import _DSN, _until_bound
import pymysql

# 入库列顺序（与 log_handler.record_to_row 的产出对应）
LOG_COLUMNS: tuple[str, ...] = (
    "created_at", "level", "logger", "message",
    "task_id", "task_type", "exc_type", "exc_text",
    "source", "comic_id", "comic_title", "chapter_id", "chapter_title",
    "endpoint", "pages", "reason", "event",
)

# 查询返回的列（不含 exc_text 全文 —— 详情按需再取，避免列表接口把堆栈全带上）
LIST_COLUMNS = (
    "id", "created_at", "level", "logger", "message",
    "task_id", "task_type", "source", "comic_id", "comic_title",
    "chapter_id", "chapter_title", "endpoint", "pages", "reason", "event", "exc_type",
)

MAX_PAGE_SIZE = 200


def build_filters(
    *,
    level: str | None = None,
    source: str | None = None,
    event: str | None = None,
    task_id: str | None = None,
    comic_id: int | None = None,
    keyword: str | None = None,
    since=None,
    until=None,
) -> tuple[list[str], list]:
    """把查询条件拼成 `(WHERE 子句列表, 参数列表)` —— **纯函数，便于单测**。

    时间窗语义与转存一致（**双端含**）：`since` 只给日期 = 当日 00:00；
    `until` 只给日期 = **含当天全天**（内部转成次日 00:00 排他），带时刻则含该时刻。
    """
    conds: list[str] = []
    params: list[object] = []
    if level:
        conds.append("level = %s")
        params.append(str(level).upper())
    if source:
        conds.append("source = %s")
        params.append(str(source))
    if event:
        conds.append("event = %s")
        params.append(str(event))
    if task_id:
        conds.append("task_id = %s")
        params.append(str(task_id))
    if comic_id:
        conds.append("comic_id = %s")
        params.append(int(comic_id))
    if keyword and str(keyword).strip():   # 纯空白 = 不限（否则会拼出 LIKE '%%' 把结果全拉回来）
        kw = f"%{str(keyword).strip()}%"
        conds.append("(message LIKE %s OR comic_title LIKE %s OR chapter_title LIKE %s OR reason LIKE %s)")
        params.extend([kw, kw, kw, kw])
    if since is not None:
        conds.append("created_at >= %s")
        params.append(since if isinstance(since, datetime) else str(since))
    if until is not None:
        end, exclusive = _until_bound(until)
        conds.append("created_at < %s" if exclusive else "created_at <= %s")
        params.append(end)
    return conds, params


class MySQLLogStore:
    """`log_record` 表的读写（每次调用一条连接，autocommit —— 与 `MySQLStorage` 一致）。"""

    def __init__(self, dsn: dict | None = None) -> None:
        self.dsn = dsn or _DSN

    def _conn(self):
        return pymysql.connect(**self.dsn)

    # ---------------- 写入 ----------------
    def insert_many(self, rows: list[dict]) -> int:
        """**一次连接**批量写入（`executemany`）。返回写入行数；`rows` 为空时不建连接。"""
        if not rows:
            return 0
        cols = ", ".join(LOG_COLUMNS)
        placeholders = ", ".join(["%s"] * len(LOG_COLUMNS))
        values = [tuple(r.get(c) for c in LOG_COLUMNS) for r in rows]
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO log_record ({cols}) VALUES ({placeholders})", values
                )
            return len(values)
        finally:
            conn.close()

    # ---------------- 读取 ----------------
    def query(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        with_exc: bool = False,
        **filters,
    ) -> tuple[list[dict], int]:
        """按条件分页查询 → `(items, total)`，**按 id 倒序**（= 时间倒序，同秒也稳定）。

        `with_exc=True` 时附带 `exc_text` 堆栈全文（列表页不带，详情才要）。
        """
        conds, params = build_filters(**filters)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        cols = ", ".join(LIST_COLUMNS) + (", exc_text" if with_exc else "")
        size = max(1, min(int(page_size or 50), MAX_PAGE_SIZE))
        offset = max(0, (max(1, int(page or 1)) - 1) * size)
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) AS c FROM log_record{where}", params)
                total = int(cur.fetchone()["c"])
                cur.execute(
                    f"SELECT {cols} FROM log_record{where} ORDER BY id DESC LIMIT %s OFFSET %s",
                    params + [size, offset],
                )
                return list(cur.fetchall()), total
        finally:
            conn.close()

    def get(self, log_id: int) -> dict | None:
        """单条（含堆栈全文）—— 查询页点开某行时用。"""
        cols = ", ".join(LIST_COLUMNS) + ", exc_text"
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {cols} FROM log_record WHERE id = %s", (int(log_id),))
                return cur.fetchone()
        finally:
            conn.close()

    # ---------------- 保留策略 ----------------
    def purge(self, days: int = 30) -> int:
        """删除 `days` 天前的日志，返回删除行数。

        默认**不做自动清理**（本地演示量不大）；表涨起来后由管理台手动触发
        （`POST /api/admin/logs/purge`）或将来接定时任务。
        """
        keep = max(1, int(days))
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM log_record WHERE created_at < (NOW() - INTERVAL %s DAY)", (keep,)
                )
                return int(cur.rowcount)
        finally:
            conn.close()
