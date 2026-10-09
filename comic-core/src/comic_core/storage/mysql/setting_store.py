"""存储层 MySQL 实现：**全站级键值配置**（`app_setting` 表）。

只有一件事要放这里：那些**运行期要能改**、又不属于"某一行数据"的平台开关。
目前唯一的使用者是**全站评论总开关**（键 `comment_enabled`，见 `comment_store`）。

为什么用表而不是 `.env` / 配置文件：这是**管理台一个按钮就要生效**的业务开关 ——
环境变量改完得重启容器，不合适；配置文件的并发写又要自己造锁。
表天然幂等、并发安全，也顺手有 `updated_at` 可查。

值一律按**字符串**存（`'1'` / `'0'`），由读取方解释；**键不存在 = 取调用方给的默认值**
（所以全新库里这张表可以是空的，不必预先播种）。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql

from ._pool import pooled_conn
from ._util import _DSN, _now

#: 全站评论总开关的键名（唯一使用者；再多了就在各自模块里定义常量，别都堆这儿）
KEY_COMMENT_ENABLED = "comment_enabled"


class MySQLSettingStore:
    """`app_setting` 的读写。连接来自共享池（`._pool`），autocommit 提交。"""

    def __init__(self, dsn: dict | None = None) -> None:
        self.dsn = dsn or _DSN

    @contextmanager
    def _conn(self) -> Iterator[pymysql.connections.Connection]:
        with pooled_conn(self.dsn) as conn:
            yield conn

    def get(self, key: str, default: str = "") -> str:
        """读一个键；**键不存在返回 `default`**（不写回、不播种）。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT v FROM app_setting WHERE k = %s", (key,))
                row = cur.fetchone()
        return str(row["v"]) if row else default

    def set(self, key: str, value: str) -> None:
        """写一个键（存在即覆盖，不存在即插入）。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO app_setting (k, v, updated_at) VALUES (%s, %s, %s)
                       ON DUPLICATE KEY UPDATE v = VALUES(v), updated_at = VALUES(updated_at)""",
                    (key, str(value), _now()),
                )

    def get_bool(self, key: str, default: bool = True) -> bool:
        """按布尔读：`'1'/'true'/'yes'/'on'`（不分大小写）为真，其余为假；键不存在取 `default`。"""
        raw = self.get(key, "").strip().lower()
        if not raw:
            return default
        return raw in ("1", "true", "yes", "on")

    def set_bool(self, key: str, value: bool) -> None:
        self.set(key, "1" if value else "0")
