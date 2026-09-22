"""认证：口令散列（bcrypt）+ 令牌签发/校验（JWT）+ 当前用户依赖 + 角色门槛。

演示用途密钥，生产环境用 `COMIC_JWT_SECRET` 注入强随机值。

**角色三档**（`user.role`，见 `docs/auth.md` §8）：

| 值 | 名字 | 能做什么 |
|---|---|---|
| `superadmin` | 超级管理员 | 管理台 + 日志 + **授权页**（给别人授权/取消）。**全库只有一个**，只在"首个注册用户"时产生 |
| `admin` | 普通管理员 | 管理台 + 日志；**进不了授权页**（授不了权） |
| `user` | 普通用户（默认） | 无任何管理台权限 |

为什么必须分两档（2026-09-18 用户实测出的漏洞）：原先只有 `admin` 一档，而授权页也只要 `admin`
就能进 —— 于是**被授权的普通管理员可以把真正的超管降级，甚至互相降级**。
现在"能管采集日志"与"能给人授权"是两个独立门槛：`require_admin` / `require_superadmin`。

**角色不写进 token**：每次请求由 `get_current_user` 从库里读出，所以刚被改角色**立即生效**
（不必等 7 天 token 过期）；代价是每个带鉴权的请求多一次按主键查库。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import users

_JWT_SECRET = os.environ.get("COMIC_JWT_SECRET", "comic-demo-secret-change-me")
_JWT_ALGO = "HS256"
_JWT_EXP_HOURS = 24 * 7  # 7 天

ROLE_SUPERADMIN = "superadmin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"

#: 能进管理台/日志的角色（超管 + 普通管理员）
ADMIN_ROLES = (ROLE_SUPERADMIN, ROLE_ADMIN)
#: 授权页能**授予**的角色（超管不在内：全库只有一个，只能由引导/迁移脚本产生）
ASSIGNABLE_ROLES = (ROLE_ADMIN, ROLE_USER)

_bearer = HTTPBearer(auto_error=False)


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def make_token(user_id: int, username: str) -> str:
    now = datetime.now()
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=_JWT_EXP_HOURS)).timestamp()),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def decode_token(token: str) -> dict:
    """解码并校验 token；无效/过期抛 401。"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token")
    return payload


def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """从 `Authorization: Bearer <token>` 解析当前登录用户。"""
    if cred is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    payload = decode_token(cred.credentials)
    user = users.get_user(payload.get("sub", ""))
    if not user:
        raise HTTPException(status_code=401, detail="user not found")
    return user


def get_optional_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict | None:
    """**尽力**解析当前登录用户：无 token / token 无效 / 用户已不存在 → `None`（不抛 401）。

    给「登录了按账号、没登录按匿名 id」这类接口用（目前只有**阅读历史**）。

    为什么不复用 `get_current_user`：历史对游客开放（前端只在 localStorage 里放一个
    匿名 UUID，不要求登录），所以**不能**因为缺凭证就 401。token 过期时也当游客处理，
    免得用户连"读到第几页"都存不下来 —— 真需要登录的接口（收藏 / 管理台）会自己 401，
    由前端拦截器统一跳登录页。
    """
    if cred is None:
        return None
    try:
        payload = decode_token(cred.credentials)
    except HTTPException:
        return None
    return users.get_user(payload.get("sub", ""))


def is_admin(user: dict | None) -> bool:
    """是否有**管理台权限**（`superadmin` 或 `admin`）—— 不含授权页。"""
    return bool(user) and user.get("role") in ADMIN_ROLES


def is_superadmin(user: dict | None) -> bool:
    """是否超级管理员（**只有它**能进授权页）。"""
    return bool(user) and user.get("role") == ROLE_SUPERADMIN


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """管理台门槛（`routers/admin.py`：采集 / 转存 / 巡检 / 导入 / 任务 / **日志**）。

    - **未登录** → 401（由 `get_current_user` 抛出，前端拦截器据此跳登录页）；
    - **已登录但无管理台权限** → 403（前端提示"需要管理员权限"，不清登录态）。

    超管与普通管理员都能过 —— 日志页面属于管理台，两者都可看。
    """
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_superadmin(user: dict = Depends(get_current_user)) -> dict:
    """超级管理员门槛（`routers/admin_users.py`：**授权页**，给他人授权/取消）。

    ⚠️ 与 `require_admin` 分开是**安全要求**，不是分级美观：若授权页也只要 `admin`，
    被授权的普通管理员反手就能把真正的超管降级（2026-09-18 实测到的漏洞）。
    """
    if not is_superadmin(user):
        raise HTTPException(status_code=403, detail="需要超级管理员权限")
    return user
