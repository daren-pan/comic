"""把日志落进 MySQL（`log_record` 表）的 logging Handler。

设计要点（每条都对应一条项目约定或踩过的坑）：

1. **后台线程 + 队列 + 批量 `executemany`**：绝不在 `emit()` 里建连接。存储层单次建连接约
   20ms 量级，若每条日志各建一次，一次采集/转存就能拖慢秒级 —— 正是「硬性约定·性能」禁止的
   "代价随数据量线性增长"。这里凑够 `BATCH` 条或超过 `FLUSH_SECONDS` 才刷一次。
2. **只收自家日志**：root logger 上还有 httpx 等第三方（WARNING 级也会有），
   用 `LOG_SOURCES` 白名单过滤，DB 里只留 `comic_crawler.* / comic.admin / services.*` 的业务日志。
3. **写库失败不拖垮业务**：异常全部吞掉并计数，只往 stderr 打一行（**不经 logging**，否则递归），
   日志最多丢几条，绝不让采集/转存因为"记日志失败"而失败。
4. **退出前尽力刷完**：注册 `atexit`，进程正常退出时把缓冲里的记录写完。

`record_to_row()` 刻意做成**纯函数**（不碰连接、不启线程），单测可以直接喂 `LogRecord` 断言取值。
"""
from __future__ import annotations

import atexit
import logging
import queue
import sys
import threading
import time
from datetime import datetime

from ... import logctx
from .log_store import LOG_COLUMNS, MySQLLogStore

# 只收这些 logger 前缀的日志（见模块说明第 2 条）
LOG_SOURCES: tuple[str, ...] = ("comic_crawler", "comic.admin", "services")

BATCH = 50            # 攒够多少条刷一次
FLUSH_SECONDS = 2.0   # 或最多等这么久
QUEUE_MAX = 5000      # 缓冲上限；满了丢新日志并计数（宁可丢日志，不阻塞业务）

# 超长截断：message / exc_text 是 TEXT（64KB），单条日志不该撑爆它
MESSAGE_MAX = 4000
EXC_MAX = 8000


def _clip(value: object, limit: int) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _exc_text(record: logging.LogRecord) -> str:
    """异常堆栈（logging 只在格式化时生成 `exc_text`，这里显式取一次）。"""
    if not record.exc_info:
        return ""
    return _clip(logging.Formatter().formatException(record.exc_info), EXC_MAX)


def record_to_row(record: logging.LogRecord) -> dict:
    """`LogRecord` → `log_record` 表的一行（**纯函数**）。

    通用字段来自记录本身，任务信息来自 `logctx`，业务字段来自
    `extra={"log_fields": {...}}`（拿不到就留空，不影响入库）。
    """
    fields: dict = dict(logctx.current())
    extra = getattr(record, "log_fields", None)
    if isinstance(extra, dict):
        fields.update(extra)
    return {
        "created_at": datetime.fromtimestamp(record.created),
        "level": str(record.levelname)[:8],
        "logger": str(record.name)[:64],
        "message": _clip(record.getMessage(), MESSAGE_MAX),
        "task_id": _clip(fields.get("task_id"), 64),
        "task_type": _clip(fields.get("task_type"), 16),
        "exc_type": str(record.exc_info[0].__name__) if record.exc_info else "",
        "exc_text": _exc_text(record),
        "source": _clip(fields.get("source"), 64),
        "comic_id": _as_int(fields.get("comic_id")),
        "comic_title": _clip(fields.get("comic_title"), 255),
        "chapter_id": _as_int(fields.get("chapter_id")),
        "chapter_title": _clip(fields.get("chapter_title"), 255),
        "endpoint": _clip(fields.get("endpoint"), 255),
        "pages": _as_int(fields.get("pages")),
        "reason": _clip(fields.get("reason"), 255),
        "event": _clip(fields.get("event"), 32),
    }


class MySQLLogHandler(logging.Handler):
    """把日志批量写进 `log_record` 表（后台线程，见模块说明）。"""

    def __init__(self, store: MySQLLogStore | None = None, level: int = logging.INFO) -> None:
        super().__init__(level=level)
        self.store = store or MySQLLogStore()
        self._q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.dropped = 0      # 队列满被丢掉的条数
        self.write_errors = 0  # 写库失败次数

    # ---- 过滤器：只收自家 logger ----
    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith(LOG_SOURCES):
            return
        try:
            self._ensure_thread()
            self._q.put_nowait(record_to_row(record))
        except queue.Full:
            self.dropped += 1
        except Exception:  # 记日志本身绝不能影响业务
            self.write_errors += 1

    # ---- 后台刷盘 ----
    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="mysqllog", daemon=True
                )
                self._thread.start()
                atexit.register(self.close)

    def _run(self) -> None:
        buf: list[dict] = []
        last = time.monotonic()
        while True:
            try:
                buf.append(self._q.get(timeout=FLUSH_SECONDS))
            except queue.Empty:
                pass
            now = time.monotonic()
            if buf and (len(buf) >= BATCH or now - last >= FLUSH_SECONDS):
                self._flush(buf)
                buf = []
                last = now

    def _flush(self, rows: list[dict]) -> None:
        try:
            self.store.insert_many(rows)
        except Exception as exc:
            self.write_errors += 1
            # 直接写 stderr，**不要走 logging**（否则又回到本 handler → 递归）
            print(f"[mysqllog] 日志落库失败（丢弃 {len(rows)} 条）: {exc}", file=sys.stderr)

    def close(self) -> None:
        """停止并尽力把缓冲里的记录刷完（`atexit` 也会调它）。"""
        try:
            rows = []
            while True:
                rows.append(self._q.get_nowait())
        except queue.Empty:
            pass
        if rows:
            self._flush(rows)
        self._thread = None
        super().close()


def install(level: int = logging.INFO) -> MySQLLogHandler:
    """把 Handler 挂到 root logger 上（由 `core/logging_setup.setup()` 调用）。"""
    handler = MySQLLogHandler(level=level)
    logging.getLogger().addHandler(handler)
    return handler
