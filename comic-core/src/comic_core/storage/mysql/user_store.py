"""存储层 MySQL 实现：用户中心（user / favorite / history）。

对应 api-service 的收藏/历史接口；连接参数见 `._util`，取连接走**共享连接池**（`._pool`）。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql

from ..base import UserStore
from ._pool import pooled_conn
from ._util import _DSN, _now


class MySQLUserStore(UserStore):
    """用户中心 MySQL 实现（UserStore 契约）。连接来自共享池，autocommit 提交。"""

    def __init__(self, dsn: dict | None = None) -> None:
        self.dsn = dsn or _DSN

    @contextmanager
    def _conn(self) -> Iterator[pymysql.connections.Connection]:
        """借一条**池化**连接（与 `MySQLStorage._conn` 同一套，见 `._pool`）。"""
        with pooled_conn(self.dsn) as conn:
            yield conn

    def list_favorites(self, user_id: str) -> list[int]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT comic_id FROM favorite WHERE user_id=%s ORDER BY created_at DESC",
                    (user_id,),
                )
                return [int(r["comic_id"]) for r in cur.fetchall()]

    def list_favoriters(self, comic_ids: list[int], listed_only: bool = True) -> dict[int, list[int]]:
        """**一次**取多部作品的收藏者 → `{comic_id: [user_id, ...]}`（见契约 `UserStore`）。

        收藏者必是登录用户（收藏接口要求登录），JOIN `user` 表兜底：账号已删的行自然滤掉
        （`favorite.user_id` 是数字串，过完 JOIN 再转 int，脏数据不会漏进来）。
        `comic_id` 过滤走 `idx_fav_comic`；`listed_only` 再叠一层 `comic.listed = 1`
        —— 下架作品不通知（详情页 404，通知了只会点进死链）。
        """
        if not comic_ids:
            return {}
        ids = [int(i) for i in comic_ids]
        placeholders = ", ".join(["%s"] * len(ids))
        cond = " AND c.listed = 1" if listed_only else ""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT f.comic_id, f.user_id
                        FROM favorite f
                        JOIN user u ON u.id = f.user_id
                        JOIN comic c ON c.id = f.comic_id
                        WHERE f.comic_id IN ({placeholders}){cond}""",
                    ids,
                )
                out: dict[int, list[int]] = {}
                for r in cur.fetchall():
                    out.setdefault(int(r["comic_id"]), []).append(int(r["user_id"]))
                return out

    # ---- 用户账户（登录/注册） ----
    def get_user_by_username(self, username: str) -> dict | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user WHERE username=%s", (username,))
                row = cur.fetchone()
                return dict(row) if row else None

    def create_user(
        self, username: str, password_hash: str, nickname: str, role: str = "user"
    ) -> dict:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO user (username, password_hash, nickname, role, created_at)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (username, password_hash, nickname, role, _now()),
                )
                conn.commit()
                cur.execute("SELECT * FROM user WHERE id=%s", (cur.lastrowid,))
                return dict(cur.fetchone())

    def count_privileged(self) -> int:
        """特权用户数（`superadmin` + `admin`）—— 为 0 说明还没人能做管理动作。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM user WHERE role IN ('superadmin','admin')")
                return int(cur.fetchone()["n"])

    def list_users(
        self, keyword: str | None = None, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict], int]:
        """用户列表（授权页）：一条 COUNT + 一条 `LIMIT` 查询，不在 Python 侧切片。

        关键字为 `None`/空串时不加 `WHERE`（少一次全表 LIKE 判断）。
        """
        where, params = "", []
        if keyword:
            where = " WHERE username LIKE %s OR nickname LIKE %s"
            like = f"%{keyword}%"
            params = [like, like]
        offset = (page - 1) * page_size
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) AS n FROM user{where}", params)
                total = int(cur.fetchone()["n"])
                cur.execute(
                    f"""SELECT id, username, nickname, role, created_at FROM user{where}
                        ORDER BY id LIMIT %s OFFSET %s""",
                    [*params, page_size, offset],
                )
                return [dict(r) for r in cur.fetchall()], total

    def set_user_role(self, user_id: str, role: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE user SET role=%s WHERE id=%s", (role, user_id))
                conn.commit()
                return cur.rowcount > 0

    def get_user(self, user_id: str) -> dict | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user WHERE id=%s", (user_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    # ---- 邮箱（2026-10-24，「忘记密码 / 绑定邮箱」的账号定位方式）----
    def get_user_by_email(self, email: str) -> dict | None:
        """按邮箱取用户（走 `uk_email`）。`email` 由调用方归一（`strip().lower()`）。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user WHERE email=%s", (email,))
                row = cur.fetchone()
                return dict(row) if row else None

    def set_user_email(self, user_id: str, email: str) -> bool:
        """绑定 / 更换邮箱；空串写 `NULL`。

        返回语义（契约 `UserStore.set_user_email`）：
        - `True`  = 写成功（**包括"值没变"**：重复绑同一邮箱、清空本来就是 `NULL` 的邮箱）；
        - `False` = 用户不存在 **或** 该邮箱已被别的账号占用（唯一键冲突，不抛异常）。

        ⚠️ 空串 → `NULL` 是**硬要求**：`uk_email` 不比较 `NULL`，而 `''` 是普通值 ——
        第二个未绑定用户写 `''` 会直接 1062（设计 R10）。
        ⚠️ **不能只靠 `rowcount > 0`**：MySQL 的 UPDATE 在"新值 == 旧值"时返回 0 行，
        于是"重复绑同一邮箱"会被误判成失败、调用方给用户 409「该邮箱已被其他账号绑定」
        （2026-10-24 实测：`set_user_email(15, '')` 在 email 本就是 NULL 时返回了 False）。
        0 行时再补一次存在性查询，把"没变化"与"人不在了"区分开。
        并发绑定同一邮箱由 `uk_email` 兜底（设计 R14）：`IntegrityError` → `False` → 调用方 409。
        """
        value = (email or "").strip().lower() or None
        with self._conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("UPDATE user SET email=%s WHERE id=%s", (value, user_id))
                except pymysql.err.IntegrityError:
                    conn.rollback()
                    return False
                conn.commit()
                if cur.rowcount > 0:
                    return True
                # 0 行 = 「值没变」或「用户不存在」，补一条按主键的存在性查询才能区分
                cur.execute("SELECT 1 FROM user WHERE id=%s", (user_id,))
                return cur.fetchone() is not None

    # ---- 个人资料（改昵称 / 改密码 / 改头像，2026-10-12）----
    def update_nickname(self, user_id: str, nickname: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE user SET nickname=%s WHERE id=%s", (nickname, user_id))
                conn.commit()

    def update_password(self, user_id: str, password_hash: str) -> None:
        """写新密码 + 刷新 `password_changed_at`（后者让旧 token 立即失效，见契约 `UserStore`）。

        改密与「忘记密码重置」共用这一个写点 —— 只有一处写 `password_changed_at`，
        `core/security.get_current_user` 就只需比较这一个时刻。
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user SET password_hash=%s, password_changed_at=%s WHERE id=%s",
                    (password_hash, _now(), user_id),
                )
                conn.commit()

    def update_avatar(self, user_id: str, avatar_url: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE user SET avatar_url=%s WHERE id=%s", (avatar_url, user_id))
                conn.commit()

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
