"""认证接口：注册 / 登录 / 当前用户（JWT + bcrypt + 角色引导）。

**首个注册用户自动成为超级管理员**（用户 2026-09-18 决策）：库里**一个特权用户都没有**
（既没有 `superadmin` 也没有 `admin`）时，新注册的用户直接给 `superadmin`，否则给默认的 `user`。
这样全新部署**不用任何手动步骤**就能进管理台与授权页（老库由 `tools/add_user_role.py` 补）。

⚠️ 两个注意点：
- `superadmin` **全库只有一个**，注册通道不会造第二个（授权页也授不了，见 `services/accounts.py`）；
- 站点对外且**尚无特权用户**时，谁先注册谁就是超管。部署好请**立刻注册**，或先用迁移脚本指定。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.db import users
from core.responses import ok
from core.security import (
    ROLE_SUPERADMIN,
    ROLE_USER,
    get_current_user,
    hash_password,
    make_token,
    verify_password,
)
from schemas import LoginBody, RegisterBody
from serializers import user_out

router = APIRouter(tags=["auth"])


@router.post("/api/auth/register")
def register(body: RegisterBody):
    username = body.username.strip()
    if not (3 <= len(username) <= 32):
        raise HTTPException(status_code=400, detail="用户名长度需为 3-32 个字符")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")
    if users.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    # 引导：库里没有任何特权用户 → 第一个注册者成为**超级管理员**（见模块头）
    role = ROLE_USER if users.count_privileged() else ROLE_SUPERADMIN
    user = users.create_user(username, hash_password(body.password), body.nickname.strip(), role)
    return ok({"token": make_token(user["id"], user["username"]), "user": user_out(user)}, "register success")



@router.post("/api/auth/login")
def login(body: LoginBody):
    user = users.get_user_by_username(body.username.strip())
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return ok({"token": make_token(user["id"], user["username"]), "user": user_out(user)}, "login success")


@router.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    return ok(user_out(user))
