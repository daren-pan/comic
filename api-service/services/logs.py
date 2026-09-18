"""运行日志的**查询**（管理台「日志查询」页）。

数据来源：`log_record` 表 —— 日志由 `comic_crawler.storage.mysql.log_handler` 在打日志时
自动落库（后台线程批量写，见该模块）。本模块只负责**读**：条件筛选 + 分页 + 单条详情 + 保留策略。

与旧实现的关键区别：过去是"读 `logs/api.log` 末尾 N 行"给弹窗看（前端每 4 秒轮询一次），
现在改为**查库** —— 能按级别 / 源站 / 作品 / 章节 / 任务 / 关键字 / 时间窗任意组合筛，
也就不再需要轮询。日志文件仍然照常写（运维 `tail` 用），但不再是查询的数据源。
"""
from __future__ import annotations

from core import config  # noqa: F401  —— 先完成 sys.path 引导（使 comic_crawler 可导入）
from comic_crawler.storage.mysql import MAX_PAGE_SIZE, MySQLLogStore

# 进程内复用一个 store（它自己每次调用建连接，无状态）
_store = MySQLLogStore()

DEFAULT_PAGE_SIZE = 50

# 供前端筛选下拉用：日志里可能出现的事件类型（与各调用点写入的 event 对齐）
EVENTS: tuple[str, ...] = (
    "sync.start", "sync.done", "sync.fail",
    "transfer.done", "transfer.fail",
    "inspect.done", "inspect.fail",
    "import.done", "import.fail",
    "cover.ok", "cover.fail", "cover.heal",
    "read.pages", "read.fail", "search.fail",
    "task.fail", "env.warn",
)

LEVELS: tuple[str, ...] = ("INFO", "WARNING", "ERROR")


def to_log_row(row: dict, with_exc: bool = False) -> dict:
    """日志行 → 前端契约（`log_record` 表 → 驼峰）。

    时间统一格式化成 `YYYY-MM-DD HH:MM:SS`（和过去看日志文件时一致）；
    `excText`（堆栈全文）只在详情接口带 —— 一页 50 条堆栈太占响应体。

    ⚠️ 刻意**不放在 `serializers.py`**：那个模块在导入时就 `from core.db import db`（真实存储句柄），
    一旦这里 import 它，任何导入日志服务的地方都会连带加载 `core.db` —— 单测就再也做不到
    "纯逻辑不连库"了（本项目明确维持这条约定）。
    """
    created = row.get("created_at")
    if hasattr(created, "strftime"):
        created = created.strftime("%Y-%m-%d %H:%M:%S")
    out = {
        "id": row["id"],
        "createdAt": created,
        "level": row.get("level") or "",
        "logger": row.get("logger") or "",
        "message": row.get("message") or "",
        "taskId": row.get("task_id") or "",
        "taskType": row.get("task_type") or "",
        "excType": row.get("exc_type") or "",
        "source": row.get("source") or "",
        "comicId": row.get("comic_id"),
        "comicTitle": row.get("comic_title") or "",
        "chapterId": row.get("chapter_id"),
        "chapterTitle": row.get("chapter_title") or "",
        "endpoint": row.get("endpoint") or "",
        "pages": row.get("pages"),
        "reason": row.get("reason") or "",
        "event": row.get("event") or "",
    }
    if with_exc:
        out["excText"] = row.get("exc_text") or ""
    return out


def query(
    *,
    level: str | None = None,
    source: str | None = None,
    event: str | None = None,
    task_id: str | None = None,
    comic_id: int | None = None,
    keyword: str | None = None,
    since=None,
    until=None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    with_exc: bool = False,
) -> dict:
    """按条件分页查日志 → `{items, total, page, pageSize}`（按时间倒序）。"""
    # 先把分页参数归一，再同时用于查询与回报 —— 否则"传 0 却报 50"这类不一致会让人误判
    p = max(1, int(page or 1))
    size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    items, total = _store.query(
        page=p,
        page_size=size,
        with_exc=with_exc,
        level=level,
        source=source,
        event=event,
        task_id=task_id,
        comic_id=comic_id,
        keyword=keyword,
        since=since,
        until=until,
    )
    return {
        "items": [to_log_row(r) for r in items],
        "total": total,
        "page": p,
        "pageSize": size,
    }


def detail(log_id: int) -> dict | None:
    """单条日志（含异常堆栈全文）—— 查询页点开某行时用。"""
    row = _store.get(log_id)
    return to_log_row(row, with_exc=True) if row else None


def purge(days: int = 30) -> int:
    """删除 `days` 天前的日志（管理台手动触发；默认不做自动清理）。"""
    return _store.purge(days)


def options() -> dict:
    """筛选下拉的候选值（级别 / 事件类型）。"""
    return {"levels": list(LEVELS), "events": list(EVENTS)}
