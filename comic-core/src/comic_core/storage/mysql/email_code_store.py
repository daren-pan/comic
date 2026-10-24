"""存储层 MySQL 实现：邮箱验证码（`email_code` 表）。

一行 = 一次发码请求，供 `api-service/services/email_codes.py` 做「生成 / 校验 / 频控」。
与其它 store 同构：连接来自共享池（`._pool`），全部单条 SQL、走 `idx_code_lookup` /
`idx_code_ip` / `idx_code_created` 三条索引 —— 没有全表扫，也没有「先查一批再逐条查」。

**为什么这些状态必须落库**：60 秒冷却、每小时配额、失败次数、单次消费都要跨重启、
跨多 worker 生效。放进程内存时表现为「刚收到的码立刻无效」「重启后冷却失效」这类
最难查的线上问题；本项目也没有 Redis 之类的缓存组件（唯一存储 = MySQL）。

**为什么 `purpose` 是必填参数**：`reset`（找回密码）与 `bind`（绑定邮箱）共用一张表，
一旦默认成某个值，「忘记传参」就会变成静默串码 —— 拿绑定邮箱的码去重置密码。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import pymysql

from ..base import EmailCodeStore
from ._pool import pooled_conn
from ._util import _DSN, _now

#: 单个验证码允许的错误次数上限（到顶整行作废，此后正确码也不再接受）。
#: 与 `api-service/services/email_codes.py` 同源：那边 `from ... import MAX_ATTEMPTS` 后比较返回值，
#: 不在两处各写一个 5（两处硬编码一旦漂移，就是「提示重试」和「真的作废」对不上）。
MAX_ATTEMPTS = 5


class MySQLEmailCodeStore(EmailCodeStore):
    """`email_code` 的读写（`EmailCodeStore` 契约）。连接来自共享池，autocommit 提交。"""

    def __init__(self, dsn: dict | None = None) -> None:
        self.dsn = dsn or _DSN

    @contextmanager
    def _conn(self) -> Iterator[pymysql.connections.Connection]:
        with pooled_conn(self.dsn) as conn:
            yield conn

    def insert_code(
        self, email: str, purpose: str, code_hash: str, expires_at: datetime, req_ip: str
    ) -> int:
        now = _now()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO email_code
                           (email, purpose, code_hash, expires_at, req_ip, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (email, purpose, code_hash, expires_at, req_ip or "", now),
                )
                return int(cur.lastrowid)

    def latest_active(self, email: str, purpose: str) -> dict | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT * FROM email_code
                       WHERE email=%s AND purpose=%s AND consumed_at IS NULL AND expires_at > %s
                       ORDER BY id DESC LIMIT 1""",
                    (email, purpose, _now()),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def latest_created_at(self, email: str, purpose: str) -> datetime | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT created_at FROM email_code
                       WHERE email=%s AND purpose=%s ORDER BY id DESC LIMIT 1""",
                    (email, purpose),
                )
                row = cur.fetchone()
                return row["created_at"] if row else None

    def incr_attempts(self, code_id: int) -> int:
        """失败次数 +1 并返回新值；到 `MAX_ATTEMPTS` 时**顺手写 `consumed_at`** 整行作废。

        ⚠️ 刻意拆成三条语句，**不写成一条 `SET attempts=attempts+1, consumed_at=IF(attempts+1>=N,...)`**：
        MySQL 的单表 UPDATE 里赋值**从左往右**生效，后一个赋值引用 `attempts` 时看到的是**已 +1 的值**，
        于是 `attempts + 1` 实际等于「旧值 + 2」—— 实测让作废提前一次发生（第 4 次错就把行废了，
        第 5 次返回「没有可用码」而不是「次数过多」），且正确码会在第 5 次之前就失效。
        这里每次校验最多 3 次往返，不在热路径上，可读性与正确性优先。
        """
        now = _now()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE email_code SET attempts = attempts + 1 WHERE id=%s", (code_id,))
                cur.execute("SELECT attempts FROM email_code WHERE id=%s", (code_id,))
                row = cur.fetchone()
                attempts = int(row["attempts"]) if row else MAX_ATTEMPTS
                if attempts >= MAX_ATTEMPTS:
                    cur.execute(
                        "UPDATE email_code SET consumed_at=%s WHERE id=%s AND consumed_at IS NULL",
                        (now, code_id),
                    )
                return attempts

    def consume(self, code_id: int) -> bool:
        """条件 UPDATE 抢占（`consumed_at IS NULL AND expires_at > now`）→ 是否抢到。

        用条件 UPDATE 而**不是**「先 SELECT 判断、再 UPDATE」：后者在双击 / 并发重放下
        有两个请求同时看到「未消费」的时间窗，单次有效就破功了。
        时间下界取应用侧 `_now()`（与 `expires_at` / `created_at` 的写入同源），
        不用 SQL 的 `NOW()` —— 容器时区与进程时区不一致时，`NOW()` 会让判定整体漂移。
        """
        now = _now()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE email_code SET consumed_at=%s
                       WHERE id=%s AND consumed_at IS NULL AND expires_at > %s""",
                    (now, code_id, now),
                )
                return cur.rowcount == 1

    def invalidate_active(self, email: str, purpose: str) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE email_code SET consumed_at=%s
                       WHERE email=%s AND purpose=%s AND consumed_at IS NULL""",
                    (_now(), email, purpose),
                )
                return cur.rowcount

    def count_recent(
        self, email: str | None = None, ip: str | None = None, *, since: datetime
    ) -> int:
        """`created_at >= since` 的行数，按 `email` 或按 `req_ip` 二选一。

        `since` 是**必填 keyword-only**（契约里 `since=...` 只是示意）：给它一个默认值会让
        「忘了传」变成配额永远查到 0，即频控静默失效 —— 这种默认值比报错危险。
        """
        if not email and not ip:
            raise ValueError("count_recent 必须给 email 或 ip 之一")
        if email:
            sql, arg = "SELECT COUNT(*) AS n FROM email_code WHERE email=%s AND created_at >= %s", email
        else:
            sql, arg = "SELECT COUNT(*) AS n FROM email_code WHERE req_ip=%s AND created_at >= %s", ip
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (arg, since))
                return int(cur.fetchone()["n"])

    def delete_code(self, code_id: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM email_code WHERE id=%s", (code_id,))

    def purge_expired(self, before: datetime) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM email_code WHERE created_at < %s", (before,))
                return cur.rowcount
