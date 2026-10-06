"""消息可见性：`visible_roles()` —— 纯函数，**不连库**。

消息中心面向所有登录用户，可见性只有一处口径：消息上的 `min_role`（**最低角色要求**）。
本文件钉住三件事：

1. **单调性**：角色越高，能看到的 `min_role` 集合只增不减（超管 ⊇ 管理员 ⊇ 普通用户）；
2. **超集语义**：`min_role='admin'` 的消息，超管也看得到；
3. **不越权**：认不出的角色按最低档处理，且任何角色都包含 `''`（所有登录用户）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comic_core.storage.mysql.message_store import visible_roles  # noqa: E402


class TestVisibleRoles(unittest.TestCase):
    def test_every_role_sees_broadcast(self) -> None:
        for role in ("user", "admin", "superadmin", "", None, "unknown"):
            self.assertIn("", visible_roles(role), role)

    def test_user_sees_only_user_and_broadcast(self) -> None:
        self.assertEqual(set(visible_roles("user")), {"", "user"})

    def test_admin_sees_user_level_too(self) -> None:
        self.assertEqual(set(visible_roles("admin")), {"", "user", "admin"})

    def test_superadmin_sees_all_levels(self) -> None:
        self.assertEqual(set(visible_roles("superadmin")), {"", "user", "admin", "superadmin"})

    def test_monotonic_by_rank(self) -> None:
        user, admin, superadmin = (set(visible_roles(r)) for r in ("user", "admin", "superadmin"))
        self.assertTrue(user < admin < superadmin, "角色越高，能看到的只多不少")

    def test_unknown_role_is_treated_as_lowest(self) -> None:
        for role in ("", None, "root", "ADMIN"):     # 大小写不等价，也别猜
            self.assertEqual(set(visible_roles(role)), {"", "user"}, repr(role))


if __name__ == "__main__":
    unittest.main()
