"""账号与授权（管理台「授权页」）。

只有**超级管理员**能用（`routers/admin_users.py` 挂在 `require_superadmin` 上，
不是 `require_admin` —— 否则普通管理员反手就能把超管降级）。提供两个动作：
**列出用户**（关键字 + 分页）与**设置角色**。

### 三档角色（见 `docs/auth.md` §8）

| 值 | 名字 | 能做什么 | 谁来产生 |
|---|---|---|---|
| `superadmin` | 超级管理员 | 管理台 + 日志 + **授权页** | **只有"首个注册用户"**（或 `tools/add_user_role.py --superadmin <用户名>` 手动转移） |
| `admin` | 普通管理员 | 管理台 + 日志，**不能授权** | 由超管在授权页授予 |
| `user` | 普通用户（默认） | 无管理台权限 | 默认 / 超管取消授权 |

### 为什么授权动作有这么几条硬规则

- **不能授予 `superadmin`**：超管"只有第一个才有"，能随便造第二个就失去了这个约束；
- **不能改自己**：唯一的超管把自己降级后再也没人能进授权页（只能上服务器改库）；
- **不能改超级管理员**：超管全库唯一且不可被降级 —— 这条与上一条一起，保证"降级超管"这件事
  **在接口层面根本不可能发生**（要被授权的普通管理员想动超管，连入口都进不来）。
  真要转移超管身份，走 `tools/add_user_role.py --superadmin <用户名>`（要服务器权限，属运维动作）。
"""
from __future__ import annotations

from core.db import users  # noqa: F401  —— 先导入以完成 sys.path 引导
from core.security import ASSIGNABLE_ROLES, ROLE_SUPERADMIN
from comic_crawler.storage.mysql import MAX_PAGE_SIZE
from serializers import to_admin_user

DEFAULT_PAGE_SIZE = 20


def list_users(keyword: str | None = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
    """分页列用户 → `{items, total, page, pageSize}`（按 id 升序，先注册的在前）。

    分页参数归一后**同时用于查询与回报** —— 否则"传 0 却报 20"这类不一致会让人误判
    （与 `services/logs.query` 同一约定）。`MAX_PAGE_SIZE` 是存储包给出的接口侧上限。
    """
    p = max(1, int(page or 1))
    size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    rows, total = users.list_users(
        keyword=(keyword or "").strip() or None, page=p, page_size=size
    )
    return {
        "items": [to_admin_user(r) for r in rows],
        "total": total,
        "page": p,
        "pageSize": size,
    }


def set_role(user_id: int, role: str, actor: dict) -> bool:
    """把目标用户设为 `admin` / `user`（授权 / 取消授权）。返回 `False` = 目标用户不存在。

    拒绝的情况抛 `ValueError`（由路由器翻成 HTTP 400），见模块头"硬规则"三节：
    改自己、授予 `superadmin`、目标是超级管理员。
    """
    if role not in ASSIGNABLE_ROLES:
        raise ValueError(f"只能授予 {' / '.join(ASSIGNABLE_ROLES)}（超级管理员全库唯一，如需转移请用 tools/add_user_role.py）")
    if int(actor["id"]) == int(user_id):
        raise ValueError("不能修改自己的角色（避免把自己锁在管理台外）")
    target = users.get_user(str(user_id))
    if target and target.get("role") == ROLE_SUPERADMIN:
        raise ValueError("不能修改超级管理员的角色（如需转移请用 tools/add_user_role.py --superadmin <用户名>）")
    return users.set_user_role(str(user_id), role)
