"""运行日志的**查询**（管理台「日志查询」页）。

数据来源：`log_record` 表 —— 日志由 `comic_crawler.storage.mysql.log_handler` 在打日志时
自动落库（后台线程批量写，见该模块）。本模块只负责**读**：条件筛选 + 分页 + 单条详情 + 保留策略。

与旧实现的关键区别：过去是"读 `logs/api.log` 末尾 N 行"给弹窗看（前端每 4 秒轮询一次），
现在改为**查库** —— 能按级别 / 源站 / 作品 / 章节 / 任务 / 关键字 / 时间窗任意组合筛，
也就不再需要轮询。日志文件仍然照常写（运维 `tail` 用），但不再是查询的数据源。

**时间一律按北京时间出参**（`to_beijing`）—— 库里存的是"写入进程的本机时间"，容器时区对不对
不该让看日志的人去猜（2026-09-18 用户要求"时间列改为北京时间"）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core import config  # noqa: F401  —— 先完成 sys.path 引导（使 comic_crawler 可导入）
from core.pagination import normalize
from comic_crawler.facade import MySQLLogStore

# 进程内复用一个 store（它自己每次调用建连接，无状态）
_store = MySQLLogStore()

DEFAULT_PAGE_SIZE = 50

# 展示时区：日志页的时间列固定按北京时间显示（中国无夏令时，固定 +08:00 即可）
BEIJING_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

# 读取进程的本机时区偏移。compose 已把 app/scheduler 统一到 `COMIC_TZ`（默认 Asia/Shanghai），
# 但漏配 / 改完没重建容器时就是 UTC —— 那正是"服务器上日志时间早 8 小时"的成因。
_LOCAL_UTC_OFFSET = datetime.now().astimezone().utcoffset() or timedelta(0)

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


def to_beijing(value):
    """库里的 naive 时间 → 北京时间字符串 `YYYY-MM-DD HH:MM:SS`。

    两边的约定要对上，才不会又出现"页面时间差 8 小时"：

    - **存储侧**：所有时间列是 **naive 本机时间**（`_util._now()` / `datetime.fromtimestamp`），
      即"写入进程自己钟表上的时间"；
    - **展示侧**：日志页一律北京时间。

    所以这里走「按读取进程的时区补上 tzinfo → 换算到 +08:00」：

    - 容器已配 `TZ=Asia/Shanghai`（compose 默认）→ 偏移就是 +8 → **恒等变换**，页面照旧；
    - 容器还是 UTC（漏配 / 没重建）→ 自动补 8 小时，页面直接正确。

    代价：**读进程与写进程的时区必须一致**（compose 用同一个 `COMIC_TZ` 注入 app 与 scheduler，
    天然满足）。真出现两边不一致时，这里只能按读侧时区解释，历史行会有 8 小时误差。

    ⚠️ **只管展示，不管筛选**：`since` / `until` 仍按存储侧时区直接比较（不换算）——
    容器时区配对了（`COMIC_TZ`）两边本来就一致；容器还是 UTC 时，筛选边界会与时间列差 8 小时。
    这是**已知且刻意保留**的：给筛选做时区换算要连"只给日期 = 含当天全天"的边界语义一起改，
    而根因（容器时区）本来就该在部署侧解决。发现筛选对不上，先查 `docker exec comic-app date`。
    """
    if value is None or not hasattr(value, "strftime"):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone(_LOCAL_UTC_OFFSET))
    return value.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def to_log_row(row: dict, with_exc: bool = False) -> dict:
    """日志行 → 前端契约（`log_record` 表 → 驼峰）。

    时间统一格式化成**北京时间** `YYYY-MM-DD HH:MM:SS`（见 `to_beijing`）；
    `excText`（堆栈全文）只在详情接口带 —— 一页 50 条堆栈太占响应体。

    ⚠️ 刻意**不放在 `serializers.py`**：那个模块做的是**通用**领域对象的形状转换
    （comic / chapter / page / user），而日志行（`log_record`）只此一处消费 ——
    映射与时间格式化（`to_beijing`）就近留在日志服务内更内聚。

    （2026-09-24 之前还有一条更硬的理由：`serializers` 曾导入 `core.db`，谁 import 它
    谁就连带加载真实存储句柄，单测做不了"纯逻辑不连库"。该问题已随 serializers 变纯
    而消失，此处只保留"就近内聚"这一条。）
    """
    out = {
        "id": row["id"],
        "createdAt": to_beijing(row.get("created_at")),
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
    p, size = normalize(page, page_size, DEFAULT_PAGE_SIZE)
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
