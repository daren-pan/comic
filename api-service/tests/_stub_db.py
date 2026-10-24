"""api-service 测试**共用**的 `core.db` 桩 —— 只能有一份，各测试文件不许再自己造。

为什么必须共用（这里踩过一次，别重犯）：

- `unittest discover -s tests` 把**所有**测试文件跑在**同一个进程**里，而
  `sys.modules['core.db']` 是**进程级全局**；
- 应用模块写的是 `from core.db import db` / `from core.db import users` ——
  **导入时绑定值**，之后换 `sys.modules` 里的模块对象**不会**改变已导入模块里绑定的那个对象。

于是「两个测试文件各装一份桩」必然互相污染：**先**触发 `serializers` 导入的那份桩决定了
`serializers.db`；另一个文件（它的断言依赖自己那份假存储"被调用过"）就会看到
「一次批量查询都没有」这类假失败。2026-09-18 加授权页鉴权测试时就踩了：
`test_admin_authz` 让 `test_users_listing` 的 5 个用例报 `'NoneType' object has no attribute ...`。

用法（在**导入任何应用模块之前**调用）：

    from _stub_db import DB, USERS, install_stub
    install_stub()                                   # ← 必须先装桩
    from routers.users import favorites, history     # noqa: E402

两个单例（`DB` / `USERS`）在各自的 `setUp` 里 `reset()` 即可。
2026-10-24 起多了第三个：`CODES`（`email_code` 验证码表，见 `routers/auth` 的找回密码 / 绑定邮箱）。
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta


class FakeDB:
    """假漫画存储：记录批量 / 逐条调用，用来断言"没有 N+1"。"""

    def __init__(self) -> None:
        self.comics: dict[int, dict] = {}
        self.chapters: dict[int, dict] = {}      # chapter_id -> {"id": .., "comic_id": ..}
        self.batch_calls: list[list[int]] = []
        self.single_calls: list[int] = []

    def reset(self) -> None:
        self.comics = {}
        self.chapters = {}
        self.batch_calls = []
        self.single_calls = []

    # --- 被路由器 / 序列化层调用 ---
    def get_comics_by_ids(self, comic_ids: list[int]) -> dict[int, dict]:
        if not comic_ids:  # 与 MySQLStorage 一致：空输入直接返回，不发查询
            return {}
        self.batch_calls.append(list(comic_ids))
        return {i: self.comics[i] for i in comic_ids if i in self.comics}

    def get_comic(self, comic_id: int):
        self.single_calls.append(comic_id)  # ← 出现即说明 N+1 回来了
        return self.comics.get(comic_id)

    def get_chapter(self, chapter_id: int):
        """单章 —— `put_history` 用它校验「这一章真属于这部作品」（防外键失败与脏进度）。"""
        return self.chapters.get(chapter_id)

    def get_comic_tags_bulk(self, comic_ids: list[int]) -> dict[int, list[str]]:
        return {}

    def get_comic_tags(self, comic_id: int) -> list[str]:
        return []


class FakeUsers:
    """假用户中心：收藏 / 历史（列表接口） + 账号 / 授权（管理台与授权页）。"""

    def __init__(self) -> None:
        self.fav_ids: list[int] = []
        self.history_rows: list[dict] = []
        # 历史归属 / 写入（断言"登录用户走账号、游客走匿名 id"用）
        self.history_reads: list[str] = []
        self.history_writes: list[tuple] = []
        self.history_deletes: list[tuple] = []
        # 账号与授权
        self.rows: list[dict] = []
        self.created: list[dict] = []
        self.role_calls: list[tuple[str, str]] = []
        self.list_calls: list[dict] = []

    def reset(self) -> None:
        self.fav_ids = []
        self.history_rows = []
        self.history_reads = []
        self.history_writes = []
        self.history_deletes = []
        self.rows = []
        self.created = []
        self.role_calls = []
        self.list_calls = []

    # --- 收藏 / 历史 ---
    def list_favorites(self, user_id: str) -> list[int]:
        return list(self.fav_ids)

    def list_history(self, user_id: str) -> list[dict]:
        self.history_reads.append(user_id)
        return list(self.history_rows)

    def upsert_history(self, user_id: str, comic_id: int, chapter_id: int, page_no: int) -> None:
        self.history_writes.append((user_id, comic_id, chapter_id, page_no))

    def delete_history(self, user_id: str, comic_id: int) -> None:
        self.history_deletes.append((user_id, comic_id))

    # --- 账号与授权 ---
    def make(self, uid: int, username: str, role: str, nickname: str = "") -> dict:
        """造一行用户（`role` 用 'admin' / 'user'）。"""
        return {
            "id": uid,
            "username": username,
            "nickname": nickname or username,
            "role": role,
            "created_at": "2026-09-18 10:00:00",
            "password_hash": "$2b$12$fake",
            # 邮箱相关列为 NULL（= 未绑定）+ 从未改过密码 —— 与老库里的行同形
            "email": None,
            "password_changed_at": None,
        }

    def get_user(self, user_id: str):
        return next((r for r in self.rows if str(r["id"]) == str(user_id)), None)

    def get_user_by_username(self, username: str):
        return next((r for r in self.rows if r["username"] == username), None)

    # --- 邮箱（2026-10-24：找回密码 / 绑定邮箱）---
    def get_user_by_email(self, email: str):
        """与 `MySQLUserStore` 同口径：按归一后的邮箱找，NULL 行永远不会命中。"""
        wanted = (email or "").strip().lower()
        if not wanted:
            return None
        return next((r for r in self.rows if (r.get("email") or "").strip().lower() == wanted), None)

    def set_user_email(self, user_id: str, email: str) -> bool:
        """空串写 `None`（= MySQL 的 NULL）；被别人占用时返回 False（唯一键冲突的那一半）。"""
        row = self.get_user(user_id)
        if not row:
            return False
        value = (email or "").strip().lower() or None
        if value:
            owner = self.get_user_by_email(value)
            if owner and str(owner["id"]) != str(user_id):
                return False
        row["email"] = value
        return True

    def count_privileged(self) -> int:
        """特权用户数（`superadmin` + `admin`）—— 契约里的"库里还没人能管理"判据。"""
        return sum(1 for r in self.rows if r["role"] in ("superadmin", "admin"))

    def create_user(
        self, username: str, password_hash: str, nickname: str, role: str = "user"
    ) -> dict:
        row = self.make(len(self.rows) + 1, username, role, nickname)
        row["password_hash"] = password_hash
        self.rows.append(row)
        self.created.append(dict(row))
        return dict(row)

    def list_users(self, keyword: str | None = None, page: int = 1, page_size: int = 20):
        self.list_calls.append({"keyword": keyword, "page": page, "page_size": page_size})
        rows = [
            r
            for r in self.rows
            if not keyword or keyword in r["username"] or keyword in r["nickname"]
        ]
        return rows[(page - 1) * page_size : page * page_size], len(rows)

    def set_user_role(self, user_id: str, role: str) -> bool:
        self.role_calls.append((str(user_id), role))
        row = self.get_user(user_id)
        if not row:
            return False
        row["role"] = role
        return True


class FakeCodes:
    """假验证码表（`email_code`）：**内存里做真语义**，不是"只记录调用"的空壳。

    为什么要有语义：`services/email_codes` 的正确性几乎全在时序上（60 秒冷却、每小时配额、
    错误累计到 5 作废、过期、条件 UPDATE 抢占）。空壳桩（方法都 `return None`）会让那些
    分支永远走不到，测试就变成"断言函数被调用过"，测不出任何东西。

    时间用真实的 `datetime.now()`（与生产同一条路径），需要"一小时前发的码"时用
    `backdate()` 把行的 `created_at` 往前挪 —— 比冻结时钟简单，也不引入依赖。
    """

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._seq = 0

    def reset(self) -> None:
        self.rows = []
        self._seq = 0

    # --- 测试辅助（生产契约里没有这些）---
    def backdate(self, seconds: int) -> None:
        """把所有行的 `created_at` 往前挪 `seconds` 秒（模拟"上次发码是 N 秒之前"）。"""
        for row in self.rows:
            row["created_at"] = row["created_at"].replace(microsecond=0) - timedelta(seconds=seconds)

    def active_rows(self) -> list[dict]:
        """还"活着"的行（未消费 + 未过期），断言"旧码被顶掉"用。"""
        now = datetime.now()
        return [r for r in self.rows if r["consumed_at"] is None and r["expires_at"] > now]

    # --- EmailCodeStore 契约 ---
    def insert_code(self, email, purpose, code_hash, expires_at, req_ip) -> int:
        self._seq += 1
        self.rows.append(
            {
                "id": self._seq,
                "email": email,
                "purpose": purpose,
                "code_hash": code_hash,
                "attempts": 0,
                "req_ip": req_ip or "",
                "expires_at": expires_at,
                "consumed_at": None,
                "created_at": datetime.now().replace(microsecond=0),
            }
        )
        return self._seq

    def latest_active(self, email, purpose):
        now = datetime.now()
        hit = [
            r
            for r in self.rows
            if r["email"] == email
            and r["purpose"] == purpose
            and r["consumed_at"] is None
            and r["expires_at"] > now
        ]
        return dict(hit[-1]) if hit else None

    def latest_created_at(self, email, purpose):
        hit = [r for r in self.rows if r["email"] == email and r["purpose"] == purpose]
        return hit[-1]["created_at"] if hit else None

    def incr_attempts(self, code_id: int) -> int:
        for row in self.rows:
            if row["id"] == code_id:
                row["attempts"] += 1
                if row["attempts"] >= 5:        # 与存储层 MAX_ATTEMPTS 同口径
                    row["consumed_at"] = datetime.now().replace(microsecond=0)
                return row["attempts"]
        return 5

    def consume(self, code_id: int) -> bool:
        now = datetime.now()
        for row in self.rows:
            if row["id"] == code_id and row["consumed_at"] is None and row["expires_at"] > now:
                row["consumed_at"] = now.replace(microsecond=0)
                return True
        return False

    def invalidate_active(self, email, purpose) -> int:
        now = datetime.now().replace(microsecond=0)
        hit = [r for r in self.rows if r["email"] == email and r["purpose"] == purpose and r["consumed_at"] is None]
        for row in hit:
            row["consumed_at"] = now
        return len(hit)

    def count_recent(self, email=None, ip=None, *, since) -> int:
        if email:
            return sum(1 for r in self.rows if r["email"] == email and r["created_at"] >= since)
        return sum(1 for r in self.rows if r["req_ip"] == ip and r["created_at"] >= since)

    def delete_code(self, code_id: int) -> None:
        self.rows = [r for r in self.rows if r["id"] != code_id]

    def purge_expired(self, before) -> int:
        keep = [r for r in self.rows if r["created_at"] >= before]
        removed = len(self.rows) - len(keep)
        self.rows = keep
        return removed


DB = FakeDB()
USERS = FakeUsers()
CODES = FakeCodes()

_MARK = "_comic_test_stub"


def install_stub() -> None:
    """把桩装进 `sys.modules['core.db']`（可重复调用，无副作用）。

    必须在 import 任何应用模块**之前**调用 —— 应用模块是 `from core.db import ...`
    （导入时绑定值），装晚了就绑到真存储上去（真 `MySQLStorage.__init__` 会试连一次库）。
    """
    stub = sys.modules.get("core.db")
    if stub is not None and getattr(stub, _MARK, False):
        return
    stub = types.ModuleType("core.db")
    setattr(stub, _MARK, True)
    stub.db = DB
    stub.users = USERS
    # ⚠️ `codes` 漏了会让 `routers.auth` 导入即 `AttributeError`（它是 `from core.db import codes`），
    # 后果不是"某个用例红"，而是**整个 unittest discover 挂掉**（设计 R12）。
    stub.codes = CODES
    sys.modules["core.db"] = stub
