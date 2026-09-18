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
"""
from __future__ import annotations

import sys
import types


class FakeDB:
    """假漫画存储：记录批量 / 逐条调用，用来断言"没有 N+1"。"""

    def __init__(self) -> None:
        self.comics: dict[int, dict] = {}
        self.batch_calls: list[list[int]] = []
        self.single_calls: list[int] = []

    def reset(self) -> None:
        self.comics = {}
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

    def get_comic_tags_bulk(self, comic_ids: list[int]) -> dict[int, list[str]]:
        return {}

    def get_comic_tags(self, comic_id: int) -> list[str]:
        return []


class FakeUsers:
    """假用户中心：收藏 / 历史（列表接口） + 账号 / 授权（管理台与授权页）。"""

    def __init__(self) -> None:
        self.fav_ids: list[int] = []
        self.history_rows: list[dict] = []
        # 账号与授权
        self.rows: list[dict] = []
        self.created: list[dict] = []
        self.role_calls: list[tuple[str, str]] = []
        self.list_calls: list[dict] = []

    def reset(self) -> None:
        self.fav_ids = []
        self.history_rows = []
        self.rows = []
        self.created = []
        self.role_calls = []
        self.list_calls = []

    # --- 收藏 / 历史 ---
    def list_favorites(self, user_id: str) -> list[int]:
        return list(self.fav_ids)

    def list_history(self, user_id: str) -> list[dict]:
        return list(self.history_rows)

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
        }

    def get_user(self, user_id: str):
        return next((r for r in self.rows if str(r["id"]) == str(user_id)), None)

    def get_user_by_username(self, username: str):
        return next((r for r in self.rows if r["username"] == username), None)

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


DB = FakeDB()
USERS = FakeUsers()

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
    sys.modules["core.db"] = stub
