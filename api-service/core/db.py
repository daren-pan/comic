"""存储句柄（本项目唯一存储方案 = MySQL）。

- `db`       ：漫画/采集侧读写（comic / chapter / page…），只读查询为主；
- `users`    ：用户中心（user / favorite / history）；
- `comments` ：评论区（comment）；
- `settings` ：全站级键值配置（app_setting）。

都是**进程级单例**，通过 FastAPI 依赖或直接导入复用。
"""
from __future__ import annotations

from . import bootstrap  # noqa: F401  —— 先导入以完成 sys.path 引导，供下方 comic_core 使用
from comic_core.storage.mysql import (
    MySQLCommentStore,
    MySQLSettingStore,
    MySQLStorage,
    MySQLUserStore,
)

db = MySQLStorage()
users = MySQLUserStore()
comments = MySQLCommentStore()
settings = MySQLSettingStore()
