"""存储层 MySQL 实现：用户中心（user / favorite / history）。

对应 api-service 的收藏/历史接口；连接参数与时间工具见 `._util`。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql

from ..base import UserStore
from ._util import _DSN, _now


class MySQLUserStore(UserStore):
    """用户中心 MySQL 实现（UserStore 契约）。每个调用独立连接，autocommit 提交。"""

    def __init__(self, dsn: dict | None = None) -> None:
        self.dsn = dsn or _DSN

    @contextmanager
    def _conn(self) -> Iterator[pymysql.connections.Connection]:
        conn = pymysql.connect(**self.dsn)
        try:
            yield conn
        finally:
            conn.close()

    def list_favorites(self, user_id: str) -> list[int]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT comic_id FROM favorite WHERE user_id=%s ORDER BY created_at DESC",
                    (user_id,),
                )
                return [int(r["comic_id"]) for r in cur.fetchall()]

    # ---- 用户账户（登录/注册） ----
    def get_user_by_username(self, username: str) -> dict | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user WHERE username=%s", (username,))
                row = cur.fetchone()
                return dict(row) if row else None

    def create_user(self, username: str, password_hash: str, nickname: str) -> dict:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO user (username, password_hash, nickname, created_at)
                       VALUES (%s,%s,%s,%s)""",
                    (username, password_hash, nickname, _now()),
                )
                conn.commit()
                cur.execute("SELECT * FROM user WHERE id=%s", (cur.lastrowid,))
                return dict(cur.fetchone())

    def get_user(self, user_id: str) -> dict | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user WHERE id=%s", (user_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def is_favorite(self, user_id: str, comic_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM favorite WHERE user_id=%s AND comic_id=%s",
                    (user_id, comic_id),
                )
                return cur.fetchone() is not None

    def set_favorite(self, user_id: str, comic_id: int, fav: bool) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                if fav:
                    cur.execute(
                        "INSERT IGNORE INTO favorite (user_id, comic_id, created_at) VALUES (%s,%s,%s)",
                        (user_id, comic_id, _now()),
                    )
                else:
                    cur.execute(
                        "DELETE FROM favorite WHERE user_id=%s AND comic_id=%s",
                        (user_id, comic_id),
                    )

    def list_history(self, user_id: str) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT h.comic_id, h.chapter_id, h.page_no, h.read_at,
                              ch.title AS chapter_title
                       FROM history h LEFT JOIN chapter ch ON ch.id = h.chapter_id
                       WHERE h.user_id=%s ORDER BY h.read_at DESC LIMIT 50""",
                    (user_id,),
                )
                return list(cur.fetchall())

    def upsert_history(self, user_id: str, comic_id: int, chapter_id: int, page_no: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO history (user_id, comic_id, chapter_id, page_no, read_at)
                       VALUES (%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE
                           chapter_id=VALUES(chapter_id), page_no=VALUES(page_no),
                           read_at=VALUES(read_at)""",
                    (user_id, comic_id, chapter_id, page_no, _now()),
                )

    def delete_history(self, user_id: str, comic_id: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM history WHERE user_id=%s AND comic_id=%s",
                    (user_id, comic_id),
                )
