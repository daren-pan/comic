"""授权页接口 —— 给其他用户授权（**仅超级管理员**）。

`/#/admin/users` 对应的后端：列出全部用户、把某个用户设为 `admin`（普通管理员）或 `user`（普通用户）。

**鉴权**：router 上挂 `require_superadmin`（**不是** `require_admin`）—— 未登录 401 /
非超管 403。这一处差别是安全要求：授权页若能由普通管理员进，它就能把真正的超管降级
（2026-09-18 用户实测到的漏洞）。

放在独立模块而不是塞进 `admin.py`：那个模块是采集动作（采集/转存/巡检/日志），
这里是账号与授权，两者业务域不同、**门禁等级也不同**。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.responses import ok
from core.security import require_superadmin
from schemas import AdminUserRoleBody
from services import accounts

router = APIRouter(tags=["admin-users"], dependencies=[Depends(require_superadmin)])


@router.get("/api/admin/users")
def admin_list_users(keyword: str | None = None, page: int = 1, page_size: int = 20):
    """用户列表（关键字匹配用户名/昵称，分页）。"""
    return ok(accounts.list_users(keyword=keyword, page=page, page_size=page_size))


@router.post("/api/admin/users/{user_id}/role")
def admin_set_user_role(
    user_id: int, body: AdminUserRoleBody, actor: dict = Depends(require_superadmin)
):
    """把某个用户设为 `admin` / `user`（授权 / 取消授权）。

    拒绝的情况（400）：改自己、授予 `superadmin`、目标是超级管理员 —— 见 `services/accounts.set_role`。
    """
    try:
        changed = accounts.set_role(user_id, body.role, actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(status_code=404, detail="用户不存在")
    return ok({"id": user_id, "role": body.role}, "已更新角色")
