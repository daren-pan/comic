"""管理台 / 日志 / 授权页的**三档角色**鉴权与授权边界。

**纯逻辑、不连库**：在导入应用模块**之前**装 `tests/_stub_db.py` 的桩（`sys.modules['core.db']`），
所以 `MySQLStorage` 不会被实例化、也不会打开任何连接；假用户存储只实现本测试触达的方法。

⚠️ 桩统一用 `_stub_db` 那一份，**不要在本文件再造一个** —— `sys.modules['core.db']` 是进程级全局，
而应用模块是 `from core.db import ...`（导入时绑定值），两份桩会互相污染（详见该模块文件头）。

### 三档角色与两道门（`docs/auth.md` §8）

| 角色 | 管理台 + 日志（`require_admin`） | 授权页（`require_superadmin`） |
|---|---|---|
| `superadmin` 超级管理员（全库唯一） | ✅ | ✅ |
| `admin` 普通管理员 | ✅ | ❌ **403** |
| `user` 普通用户 | ❌ 403 | ❌ 403 |

为什么每条都值得守（都对应真踩过的坑）：

1. **两道门必须真的分开**：2026-09-18 用户实测到 —— 原先授权页也只要 `admin`，
   于是**被授权的普通管理员反手就能把真正的超管降级**。这里既做结构断言（两个 router
   各挂各的依赖），也做行为断言（普通管理员调授权接口 → 403）。
2. **超管不可被降级、也不可被授予**：超管"只有第一个才有"，接口层面不允许造第二个或降级它
   —— 上面那个漏洞就是从这两条缺失来的。
3. **不能改自己**：唯一的超管把自己降级后再也没人能进授权页（只能上服务器改库）。
4. **`role` 缺失时按普通用户处理**（fail-closed）：老库未迁移时绝不能默认放行。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi import HTTPException

APP_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for _p in (str(APP_DIR), str(TESTS_DIR)):   # tests 目录也入 path：单跑本文件时 _stub_db 才可导入
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _stub_db import USERS, install_stub  # noqa: E402

install_stub()  # 必须在导入应用模块之前装桩

from core.security import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_SUPERADMIN,
    ROLE_USER,
    require_admin,
    require_superadmin,
)
from routers import admin as admin_module  # noqa: E402
from routers import admin_users as admin_users_module  # noqa: E402
from routers.admin_users import admin_set_user_role  # noqa: E402
from routers.auth import register  # noqa: E402
from schemas import AdminUserRoleBody, RegisterBody  # noqa: E402
from services import accounts  # noqa: E402


def _dependency_names(route) -> list[str]:
    """路由实际挂上的依赖函数名（router 级 + 路由级都在里面）。"""
    return [getattr(d.call, "__name__", str(d.call)) for d in route.dependant.dependencies]


class _UsersReset(unittest.TestCase):
    """每个用例前把假存储清干净（`rows` 由各用例自己铺）。"""

    def setUp(self) -> None:
        USERS.reset()


class TestDoorsAreSeparated(unittest.TestCase):
    """结构守卫：两个 router 必须挂**不同**的门，且每个路由都被覆盖。"""

    def test_admin_router_requires_admin(self):
        missing = [
            r.path for r in admin_module.router.routes if "require_admin" not in _dependency_names(r)
        ]
        self.assertEqual(missing, [], f"管理台路由没挂 require_admin：{missing}")

    def test_authz_router_requires_superadmin(self):
        """授权页必须是 require_superadmin —— 挂成 require_admin 就等于把超管交给普通管理员处置。"""
        for route in admin_users_module.router.routes:
            names = _dependency_names(route)
            self.assertIn("require_superadmin", names, f"{route.path} 没挂 require_superadmin")
            self.assertNotIn("require_admin", names, f"{route.path} 错误地挂了 require_admin")

    def test_route_counts_are_expected(self):
        """数量断言：新增接口时会被提醒"顺便确认它该挂哪道门"。"""
        self.assertEqual(len(admin_module.router.routes), 12)      # 采集/转存/巡检/导入/任务/日志
        self.assertEqual(len(admin_users_module.router.routes), 2)  # 授权页：列表 + 设角色


class TestRequireAdmin(unittest.TestCase):
    """管理台门槛：超管与普通管理员都能过，其余 403。"""

    def test_superadmin_passes(self):
        user = {"id": 1, "role": ROLE_SUPERADMIN}
        self.assertIs(require_admin(user), user)

    def test_normal_admin_passes(self):
        """普通管理员**能**进管理台与日志页（这正是本次要区分的点）。"""
        user = {"id": 2, "role": ROLE_ADMIN}
        self.assertIs(require_admin(user), user)

    def test_normal_user_gets_403(self):
        with self.assertRaises(HTTPException) as cm:
            require_admin({"id": 3, "role": ROLE_USER})
        self.assertEqual(cm.exception.status_code, 403)

    def test_missing_role_is_denied(self):
        """没有 role（老库未迁移 / 脏数据）→ fail-closed，绝不默认放行。"""
        with self.assertRaises(HTTPException) as cm:
            require_admin({"id": 4})
        self.assertEqual(cm.exception.status_code, 403)


class TestRequireSuperadmin(unittest.TestCase):
    """授权页门槛：只有超管能过 —— 普通管理员也不行（这是漏洞的修复点）。"""

    def test_superadmin_passes(self):
        user = {"id": 1, "role": ROLE_SUPERADMIN}
        self.assertIs(require_superadmin(user), user)

    def test_normal_admin_gets_403(self):
        with self.assertRaises(HTTPException) as cm:
            require_superadmin({"id": 2, "role": ROLE_ADMIN})
        self.assertEqual(cm.exception.status_code, 403)

    def test_normal_user_gets_403(self):
        with self.assertRaises(HTTPException) as cm:
            require_superadmin({"id": 3, "role": ROLE_USER})
        self.assertEqual(cm.exception.status_code, 403)

    def test_missing_role_is_denied(self):
        with self.assertRaises(HTTPException) as cm:
            require_superadmin({"id": 4})
        self.assertEqual(cm.exception.status_code, 403)


class TestSetRole(_UsersReset):
    """授权动作的规则（服务层）。"""

    def setUp(self) -> None:
        super().setUp()
        USERS.rows = [
            USERS.make(1, "root", ROLE_SUPERADMIN),
            USERS.make(2, "alice", ROLE_ADMIN),
            USERS.make(3, "bob", ROLE_USER),
        ]

    def test_grants_admin(self):
        self.assertTrue(accounts.set_role(3, ROLE_ADMIN, {"id": 1}))
        self.assertEqual(USERS.get_user(3)["role"], ROLE_ADMIN)

    def test_revokes_admin(self):
        self.assertTrue(accounts.set_role(2, ROLE_USER, {"id": 1}))
        self.assertEqual(USERS.get_user(2)["role"], ROLE_USER)

    def test_cannot_grant_superadmin(self):
        """超管全库唯一：授权页授不出第二个超管。"""
        with self.assertRaises(ValueError):
            accounts.set_role(3, ROLE_SUPERADMIN, {"id": 1})
        self.assertEqual(USERS.role_calls, [])

    def test_cannot_change_own_role(self):
        with self.assertRaises(ValueError):
            accounts.set_role(1, ROLE_USER, {"id": 1})
        self.assertEqual(USERS.role_calls, [])

    def test_cannot_demote_superadmin(self):
        """超管不可被降级 —— 「普通管理员把超管降掉」这条路在服务层就被堵死。"""
        with self.assertRaises(ValueError):
            accounts.set_role(1, ROLE_USER, {"id": 2})   # 调用者 alice 是普通管理员
        self.assertEqual(USERS.role_calls, [])

    def test_rejects_unknown_role(self):
        with self.assertRaises(ValueError):
            accounts.set_role(3, "root", {"id": 1})
        self.assertEqual(USERS.role_calls, [])

    def test_missing_user_returns_false(self):
        self.assertFalse(accounts.set_role(999, ROLE_ADMIN, {"id": 1}))


class TestListUsers(_UsersReset):
    """用户列表：分页参数归一后**回报值与查询值一致**（不能"传 0 却报 20"）。"""

    def setUp(self) -> None:
        super().setUp()
        USERS.rows = [USERS.make(i, f"user{i}", ROLE_USER) for i in range(1, 6)]

    def test_reported_page_size_matches_query(self):
        out = accounts.list_users(page_size=99999)
        self.assertEqual(out["pageSize"], USERS.list_calls[-1]["page_size"])
        self.assertEqual(out["page"], 1)
        self.assertEqual(out["total"], 5)

    def test_blank_keyword_becomes_none(self):
        accounts.list_users(keyword="   ")
        self.assertIsNone(USERS.list_calls[-1]["keyword"])

    def test_keyword_is_passed_through(self):
        accounts.list_users(keyword=" alice ")
        self.assertEqual(USERS.list_calls[-1]["keyword"], "alice")

    def test_rows_are_serialized_with_role(self):
        item = accounts.list_users()["items"][0]
        self.assertEqual(item["username"], "user1")
        self.assertEqual(item["role"], ROLE_USER)
        self.assertNotIn("password_hash", item)           # 凭据绝不外泄
        self.assertNotIn("passwordHash", item)


class TestAdminUserRoleEndpoint(_UsersReset):
    """路由层把服务层的几种拒绝翻成 400/404。"""

    def setUp(self) -> None:
        super().setUp()
        USERS.rows = [
            USERS.make(1, "root", ROLE_SUPERADMIN),
            USERS.make(2, "alice", ROLE_ADMIN),
        ]

    def test_self_change_is_400(self):
        with self.assertRaises(HTTPException) as cm:
            admin_set_user_role(1, AdminUserRoleBody(role=ROLE_USER), actor={"id": 1})
        self.assertEqual(cm.exception.status_code, 400)

    def test_granting_superadmin_is_400(self):
        with self.assertRaises(HTTPException) as cm:
            admin_set_user_role(2, AdminUserRoleBody(role=ROLE_SUPERADMIN), actor={"id": 1})
        self.assertEqual(cm.exception.status_code, 400)

    def test_bad_role_is_400(self):
        with self.assertRaises(HTTPException) as cm:
            admin_set_user_role(2, AdminUserRoleBody(role="root"), actor={"id": 1})
        self.assertEqual(cm.exception.status_code, 400)

    def test_missing_user_is_404(self):
        with self.assertRaises(HTTPException) as cm:
            admin_set_user_role(999, AdminUserRoleBody(role=ROLE_ADMIN), actor={"id": 1})
        self.assertEqual(cm.exception.status_code, 404)

    def test_success_returns_new_role(self):
        out = admin_set_user_role(2, AdminUserRoleBody(role=ROLE_ADMIN), actor={"id": 1})
        self.assertEqual(out["code"], 0)
        self.assertEqual(out["data"], {"id": 2, "role": ROLE_ADMIN})


class TestFirstUserBecomesSuperadmin(_UsersReset):
    """注册引导：库里没有任何特权用户时，第一个注册者成为**超级管理员**。"""

    def test_first_registration_grants_superadmin(self):
        register(RegisterBody(username="root", password="secret123", nickname="站长"))
        self.assertEqual(USERS.created[-1]["role"], ROLE_SUPERADMIN)

    def test_later_registrations_are_normal_users(self):
        USERS.rows = [USERS.make(1, "root", ROLE_SUPERADMIN)]
        register(RegisterBody(username="alice", password="secret123", nickname=""))
        self.assertEqual(USERS.created[-1]["role"], ROLE_USER)

    def test_existing_normal_admin_blocks_bootstrap(self):
        """库里已有普通管理员（但没有超管）时，注册通道**不再**造超管 —— 免得被抢注册提权。

        （这种异常态由 `tools/add_user_role.py` 把最早的 admin 提升为超管来修，不靠注册通道猜。）
        """
        USERS.rows = [USERS.make(1, "alice", ROLE_ADMIN)]
        register(RegisterBody(username="mallory", password="secret123", nickname=""))
        self.assertEqual(USERS.created[-1]["role"], ROLE_USER)

    def test_role_is_exposed_in_auth_payload(self):
        """`/api/auth/login|register` 的出参必须带 role —— 前端顶栏入口与路由守卫都看它。"""
        out = register(RegisterBody(username="root", password="secret123", nickname=""))
        self.assertEqual(out["data"]["user"]["role"], ROLE_SUPERADMIN)
        self.assertNotIn("password_hash", out["data"]["user"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
