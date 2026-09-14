"""存储层 MySQL 实现（本项目唯一存储后端）。

- `_util.py`       —— 连接参数、热度算法（`HEAT_*` / `heat_sql`）、时间归一
- `comic_store.py` —— `MySQLStorage`：漫画/章节/页/同步日志（采集侧 + 只读查询）
- `user_store.py`  —— `MySQLUserStore`：用户/收藏/阅读历史
- `log_store.py`   —— `MySQLLogStore`：运行日志（`log_record` 表）的读写与保留策略
- `log_handler.py` —— `MySQLLogHandler`：把日志批量落库的 logging Handler

**扩展点**：换存储后端只需在同级再开一个目录实现 `storage.base` 的两个契约，
上游（采集、调度、API）无需改动。
"""
from ._util import HEAT_BASE, HEAT_PER_FAVORITE, HEAT_PER_VIEW, heat_sql
from .comic_store import MySQLStorage
from .log_handler import MySQLLogHandler, record_to_row
from .log_store import MAX_PAGE_SIZE, MySQLLogStore, build_filters
from .user_store import MySQLUserStore

__all__ = [
    "MySQLStorage",
    "MySQLUserStore",
    "MySQLLogStore",
    "MAX_PAGE_SIZE",
    "MySQLLogHandler",
    "record_to_row",
    "build_filters",
    "HEAT_BASE",
    "HEAT_PER_VIEW",
    "HEAT_PER_FAVORITE",
    "heat_sql",
]
