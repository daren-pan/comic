"""存储层 MySQL 实现：**评论区**（`comment` 表）。

对应漫画详情页底部的评论区。两条口径是用户 2026-10-09 的决策：

- **只收登录用户** —— 所以 `user_id` 一定是账号 id（不是匿名 UUID），
  列表里能给出稳定的作者；未登录的写入口在 api 层就挡掉了。
  列型仍是 `VARCHAR(64)`（与 `favorite` / `history` 的 `user_id` 同型，便于共用 helper）。
- **开关是两级**（全站总开关 + 单作品开关），**判定不在这里** ——
  这里只管数据；"能不能评"由 api 侧的 `services.comments` 组装
  （见 `comic_core.storage.mysql.setting_store.KEY_COMMENT_ENABLED` 与 `comic.comment_enabled`）。

作者昵称**刻意不冗余存**：读取时 `LEFT JOIN user` 取**当前**昵称（改名后评论区跟着变），
账号已删则 `username/nickname` 为 NULL —— 由读取侧兜底显示「已注销用户」。
（对比 `admin_task` / `message` 冗余存了 username：那两张是**审计**记录，要留住"当时是谁"；
评论区的作者名是**展示**信息，跟当前状态走更合理。）
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql

from ._pool import pooled_conn
from ._util import _DSN, _now


class MySQLCommentStore:
    """`comment` 表的读写。连接来自共享池（`._pool`），autocommit 提交。"""

    def __init__(self, dsn: dict | None = None) -> None:
        self.dsn = dsn or _DSN

    @contextmanager
    def _conn(self) -> Iterator[pymysql.connections.Connection]:
        with pooled_conn(self.dsn) as conn:
            yield conn

    def list_comments(
        self, comic_id: int, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict], int]:
        """某部作品的评论，**最新在前**，返回 `(rows, total)`。

        一条 SQL 取回该页，另一条取总数 —— 都是 `(comic_id, id)` 索引上的等值/范围扫描，
        不分页拉全量（见 AGENTS.md「硬性约定·性能」）。

        行里除评论本体外带 `username` / `nickname`（作者账号已删则为 NULL）。
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM comment WHERE comic_id = %s", (comic_id,))
                total = int(cur.fetchone()["c"])
                cur.execute(
                    """SELECT cm.id, cm.comic_id, cm.user_id, cm.content, cm.created_at,
                              u.username, u.nickname
                       FROM comment cm
                       LEFT JOIN user u ON u.id = cm.user_id
                       WHERE cm.comic_id = %s
                       ORDER BY cm.id DESC
                       LIMIT %s OFFSET %s""",
                    (comic_id, page_size, (page - 1) * page_size),
                )
                return list(cur.fetchall()), total

    def add_comment(self, comic_id: int, user_id: str, content: str) -> int:
        """新增一条评论，返回新行 id。长度/空值校验在 api 层（Pydantic）做，这里不重复。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO comment (comic_id, user_id, content, created_at)
                       VALUES (%s, %s, %s, %s)""",
                    (comic_id, str(user_id), content, _now()),
                )
                return int(cur.lastrowid)

    def delete_comment(self, comment_id: int) -> bool:
        """删除一条评论 → 是否真的删掉了（False = 该 id 本来就不存在）。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM comment WHERE id = %s", (comment_id,))
                return cur.rowcount > 0

    def count_comments(self, comic_id: int) -> int:
        """某部作品的评论数（`list_comments` 顺带也会给，单独留着给"只看条数"的调用方）。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM comment WHERE comic_id = %s", (comic_id,))
                return int(cur.fetchone()["c"])
