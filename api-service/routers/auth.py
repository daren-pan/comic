"""认证接口：注册 / 登录 / 当前用户（JWT + bcrypt）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.db import users
from core.responses import ok
from core.security import get_current_user, hash_password, make_token, verify_password
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
    user = users.create_user(username, hash_password(body.password), body.nickname.strip())
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
