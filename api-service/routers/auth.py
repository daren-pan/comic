"""认证接口：注册 / 登录 / 当前用户（JWT + bcrypt + 角色引导）。

**首个注册用户自动成为超级管理员**（用户 2026-09-18 决策）：库里**一个特权用户都没有**
（既没有 `superadmin` 也没有 `admin`）时，新注册的用户直接给 `superadmin`，否则给默认的 `user`。
这样全新部署**不用任何手动步骤**就能进管理台与授权页（老库由 `tools/add_user_role.py` 补）。

⚠️ 两个注意点：
- `superadmin` **全库只有一个**，注册通道不会造第二个（授权页也授不了，见 `services/accounts.py`）；
- 站点对外且**尚无特权用户**时，谁先注册谁就是超管。部署好请**立刻注册**，或先用迁移脚本指定。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

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
from schemas import ChangePasswordBody, LoginBody, RegisterBody, UpdateProfileBody
from schemas_out import ApiEnvelope, AuthResultOut, UserOut
from serializers import user_out
from services.avatars import MAX_AVATAR_BYTES, clear_avatar, save_avatar

router = APIRouter(tags=["auth"])

# 长度策略刻意写在这里而**不是** `schemas` 的 Field：Pydantic 的越界报错是 422 + 英文 detail，
# 而这些是用户直接看得见的提示（见 api/request.ts 的 errorMessage 会把 detail 原样展示）。
USERNAME_MIN, USERNAME_MAX = 3, 32
PASSWORD_MIN, PASSWORD_MAX = 6, 128   # 上限只防"超长入参"（bcrypt 本身在 72 字节处截断），不做强度策略
NICKNAME_MAX = 64                     # = user.nickname VARCHAR(64)，超了写库必失败


@router.post("/api/auth/register", response_model=ApiEnvelope[AuthResultOut])
def register(body: RegisterBody):
    username = body.username.strip()
    if not (USERNAME_MIN <= len(username) <= USERNAME_MAX):
        raise HTTPException(
            status_code=400, detail=f"用户名长度需为 {USERNAME_MIN}-{USERNAME_MAX} 个字符"
        )
    if not (PASSWORD_MIN <= len(body.password) <= PASSWORD_MAX):
        raise HTTPException(
            status_code=400, detail=f"密码长度需为 {PASSWORD_MIN}-{PASSWORD_MAX} 位"
        )
    # 上限是 2026-09-21 补的：原先只判下限，超长昵称会撞 `user.nickname VARCHAR(64)` 变成 500
    nickname = body.nickname.strip()
    if len(nickname) > NICKNAME_MAX:
        raise HTTPException(status_code=400, detail=f"昵称长度不能超过 {NICKNAME_MAX} 个字符")
    if users.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    # 引导：库里没有任何特权用户 → 第一个注册者成为**超级管理员**（见模块头）
    role = ROLE_USER if users.count_privileged() else ROLE_SUPERADMIN
    user = users.create_user(username, hash_password(body.password), nickname, role)
    return ok({"token": make_token(user["id"], user["username"]), "user": user_out(user)}, "register success")



@router.post("/api/auth/login", response_model=ApiEnvelope[AuthResultOut])
def login(body: LoginBody):
    username = body.username.strip()
    # 越界一律并按「用户名或密码错误」返回：若这里返 400、密码错返 401，
    # 就等于给了攻击者一个「这个口令长度/用户名形态存在与否」的探测差异面。
    if not (USERNAME_MIN <= len(username) <= USERNAME_MAX) or not (
        PASSWORD_MIN <= len(body.password) <= PASSWORD_MAX
    ):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user = users.get_user_by_username(username)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return ok({"token": make_token(user["id"], user["username"]), "user": user_out(user)}, "login success")


@router.get("/api/auth/me", response_model=ApiEnvelope[UserOut])
def me(user: dict = Depends(get_current_user)):
    return ok(user_out(user))


# ---------------- 个人资料（2026-10-12，个人中心页）----------------
# 三件事都**只改自己的**：user 来自 token，接口不接受 user_id 参数 —— 天然免越权。


@router.put("/api/auth/me", response_model=ApiEnvelope[UserOut])
def update_me(body: UpdateProfileBody, user: dict = Depends(get_current_user)):
    """改昵称（登录名 `username` 不可改；长度口径同注册）。"""
    nickname = body.nickname.strip()
    if not (1 <= len(nickname) <= NICKNAME_MAX):
        raise HTTPException(status_code=400, detail=f"昵称长度需为 1-{NICKNAME_MAX} 个字符")
    users.update_nickname(user["id"], nickname)
    return ok(user_out(users.get_user(user["id"])), "昵称已更新")


@router.put("/api/auth/password", response_model=ApiEnvelope[None])
def change_password(body: ChangePasswordBody, user: dict = Depends(get_current_user)):
    """改密码：先验原密码（不对 400），新密码长度口径与注册一致。"""
    if not verify_password(body.oldPassword, user["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if not (PASSWORD_MIN <= len(body.newPassword) <= PASSWORD_MAX):
        raise HTTPException(status_code=400, detail=f"新密码长度需为 {PASSWORD_MIN}-{PASSWORD_MAX} 位")
    users.update_password(user["id"], hash_password(body.newPassword))
    return ok({}, "密码已更新")


@router.post("/api/auth/avatar", response_model=ApiEnvelope[UserOut])
async def upload_avatar(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """上传头像（multipart 字段名 `file`）。校验 / 落盘在 `services.avatars`（≤2MB、JPG/PNG/WebP/GIF）。"""
    # 只读「上限 + 1」字节：超大文件不必整个读进内存再判
    data = await file.read(MAX_AVATAR_BYTES + 1)
    try:
        url = save_avatar(user["id"], data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    users.update_avatar(user["id"], url)
    return ok(user_out(users.get_user(user["id"])), "头像已更新")


@router.delete("/api/auth/avatar", response_model=ApiEnvelope[UserOut])
def reset_avatar(user: dict = Depends(get_current_user)):
    """恢复默认头像（清库内 URL + 删头像文件）。"""
    clear_avatar(user["id"])
    users.update_avatar(user["id"], "")
    return ok(user_out(users.get_user(user["id"])), "已恢复默认头像")
