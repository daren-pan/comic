"""认证接口：注册 / 登录 / 当前用户（JWT + bcrypt + 角色引导）。

**首个注册用户自动成为超级管理员**（用户 2026-09-18 决策）：库里**一个特权用户都没有**
（既没有 `superadmin` 也没有 `admin`）时，新注册的用户直接给 `superadmin`，否则给默认的 `user`。
这样全新部署**不用任何手动步骤**就能进管理台与授权页（老库由迁移 `0004_add_user_role.sql` 补，见 tools/migrations/）。

⚠️ 两个注意点：
- `superadmin` **全库只有一个**，注册通道不会造第二个（授权页也授不了，见 `services/accounts.py`）；
- 站点对外且**尚无特权用户**时，谁先注册谁就是超管。部署好请**立刻注册**，或先用迁移脚本指定。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

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
from schemas import (
    BindEmailBody,
    ChangePasswordBody,
    LoginBody,
    RegisterBody,
    ResetPasswordBody,
    SendCodeBody,
    UpdateProfileBody,
)
from schemas_out import ApiEnvelope, AuthResultOut, UserOut
from serializers import user_out
from services import email_codes, mailer
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


# ---------------- 邮箱验证码：忘记密码 + 绑定邮箱（2026-10-24）----------------
# 全部写成**同步 `def`**（不是 `async def`）：`smtplib` 是阻塞调用，FastAPI 会把同步端点丢进
# 线程池，才不会堵住事件循环。写成 async def 就等于用一个 10 秒的阻塞拖住整个事件循环（设计 R9）。
#
# 文案与状态码都**集中在这里**（`services/email_codes` 只回报原因），因为前端会把 `detail`
# 原样展示给用户，同时也是「双端文案等价」的唯一来源。

#: 冷却 / 配额的提示语：句中的秒数取常量，别在文案里再写死一个 60
_COOLDOWN_TEXT = f"操作过于频繁，请 {email_codes.COOLDOWN_SECONDS} 秒后再试"
_QUOTA_TEXT = "操作过于频繁，请稍后再试"
_SEND_FAILED_TEXT = "验证码发送失败，请稍后重试"
_BAD_CODE_TEXT = "验证码错误或已失效"
_TOO_MANY_TEXT = "验证码错误次数过多，请重新获取"
_EMAIL_TAKEN_TEXT = "该邮箱已被其他账号绑定"


def _client_ip(request: Request) -> str:
    """取申请来源 IP（每 IP 小时配额用）：`X-Forwarded-For` 首段 → `request.client.host` → `''`。

    反代下 `client.host` 恒为网关地址，所以优先读 `X-Forwarded-For`；取不到就写空串 ——
    邮箱维度的配额才是主防线，IP 配额只是 best-effort（设计 R6）。
    """
    forwarded = request.headers.get("x-forwarded-for") or ""
    ip = forwarded.split(",")[0].strip() if forwarded else ""
    if not ip and request.client is not None:
        ip = request.client.host or ""
    return ip[:64]  # = email_code.req_ip VARCHAR(64)


def _checked_email(raw: str) -> str:
    """归一 + 校验邮箱 → 合法则返回归一后的值，否则 400（中文提示）。

    两个匿名 / 登录端点共用，保证「格式不对」的判定口径完全一致（反枚举也要求一致）。
    """
    email = email_codes.normalize_email(raw)
    error = email_codes.check_email(email)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return email


def _checked_code(raw: str) -> str:
    """校验验证码形状（6 位纯数字）→ 否则 400；返回去空白后的码。"""
    code = (raw or "").strip()
    if not (code.isdigit() and len(code) == email_codes.CODE_LENGTH):
        raise HTTPException(status_code=400, detail="验证码格式不正确")
    return code


def _raise_issue_failure(result: str) -> None:
    """把 `issue()` 的失败原因翻成 HTTP 错误（`ok` 分支由调用方处理）。

    冷却剩余秒数不拼进文案：同一个 60 秒窗口里提示「请 59 秒后再试」会随重试次数抖动，
    而验收与双端文案要的是**逐字一致**的那一句（见 `_COOLDOWN_TEXT`）。
    """
    if result == "cooldown":
        raise HTTPException(status_code=429, detail=_COOLDOWN_TEXT)
    if result in ("quota_email", "quota_ip"):
        raise HTTPException(status_code=429, detail=_QUOTA_TEXT)
    if result == "send_failed":
        raise HTTPException(status_code=503, detail=_SEND_FAILED_TEXT)


@router.post("/api/auth/password/reset/code", response_model=ApiEnvelope[dict])
def send_reset_code(body: SendCodeBody, request: Request):
    """**匿名**：给「已绑定该邮箱的账号」发一条找回密码验证码。

    ⚠️ **反枚举**：邮箱未注册时也走完全相同的路径（同样校验 → 同样查冷却与配额 → 同样落库
    → 只是不发信），状态码与文案逐字一致。所以这里**绝不能**因为「查不到用户」就返 404。
    """
    email = _checked_email(body.email)
    result, _seconds = email_codes.issue(email, "reset", _client_ip(request))
    _raise_issue_failure(result)
    return ok({"cooldownSeconds": email_codes.COOLDOWN_SECONDS}, "若该邮箱已注册，验证码已发送")


@router.post("/api/auth/password/reset", response_model=ApiEnvelope[dict])
def reset_password(body: ResetPasswordBody):
    """**匿名**：用邮箱验证码重置密码（成功后旧密码与**已签发的 token 同时失效**）。

    校验顺序刻意是「邮箱 → 码形状 → 新密码长度 → 码是否正确」：前三条都不消耗验证码，
    用户不会因为密码填短了而白白烧掉一次机会（也少一次失败计数）。
    """
    email = _checked_email(body.email)
    code = _checked_code(body.code)
    if not (PASSWORD_MIN <= len(body.newPassword) <= PASSWORD_MAX):
        raise HTTPException(status_code=400, detail=f"新密码长度需为 {PASSWORD_MIN}-{PASSWORD_MAX} 位")

    result = email_codes.check_and_consume(email, "reset", code)
    if result == "too_many":
        raise HTTPException(status_code=429, detail=_TOO_MANY_TEXT)
    if result != "ok":
        # no_code / expired / mismatch 一律同一句：不给攻击者探测「过期」「已用」「不符」的差异
        raise HTTPException(status_code=400, detail=_BAD_CODE_TEXT)

    user = users.get_user_by_email(email)
    if not user:  # 理论上走不到（只有已注册邮箱才发过信），兜一层避免 500
        raise HTTPException(status_code=400, detail=_BAD_CODE_TEXT)
    # 走与「个人中心改密」同一个写点：hash + 刷新 password_changed_at → 旧 token 立即失效
    users.update_password(user["id"], hash_password(body.newPassword))
    return ok({}, "密码已重置，请用新密码登录")


@router.post("/api/auth/email/code", response_model=ApiEnvelope[dict])
def send_bind_code(body: SendCodeBody, request: Request, user: dict = Depends(get_current_user)):
    """**需登录**：给当前账号要绑定的邮箱发一条验证码。

    先判「这邮箱是不是已被**别的账号**绑了」→ 409（绑自己的当前邮箱不算冲突）。
    与 #1 的区别：这里不需要反枚举（调用方已登录，且邮箱占用与否本来就要明说）。
    """
    email = _checked_email(body.email)
    owner = users.get_user_by_email(email)
    if owner and str(owner["id"]) != str(user["id"]):
        raise HTTPException(status_code=409, detail=_EMAIL_TAKEN_TEXT)
    result, _seconds = email_codes.issue(email, "bind", _client_ip(request))
    _raise_issue_failure(result)
    return ok({"cooldownSeconds": email_codes.COOLDOWN_SECONDS}, "验证码已发送")


@router.put("/api/auth/email", response_model=ApiEnvelope[dict])
def bind_email(body: BindEmailBody, user: dict = Depends(get_current_user)):
    """**需登录**：校验验证码后把邮箱绑到**当前账号**（不接受 userId —— 天然免越权）。

    占用检查放在 `check_and_consume` **之前**：码是对的但邮箱已被抢，不该白白烧掉一个有效码。
    并发情况下两人同时绑定同一邮箱：`uk_email` 兜底，`set_user_email` 返回 False → 409（设计 R14）。
    """
    email = _checked_email(body.email)
    code = _checked_code(body.code)

    owner = users.get_user_by_email(email)
    if owner and str(owner["id"]) != str(user["id"]):
        raise HTTPException(status_code=409, detail=_EMAIL_TAKEN_TEXT)

    result = email_codes.check_and_consume(email, "bind", code)
    if result == "too_many":
        raise HTTPException(status_code=429, detail=_TOO_MANY_TEXT)
    if result != "ok":
        raise HTTPException(status_code=400, detail=_BAD_CODE_TEXT)

    if not users.set_user_email(user["id"], email):
        raise HTTPException(status_code=409, detail=_EMAIL_TAKEN_TEXT)
    return ok({"email": mailer.mask_email(email)}, "邮箱已绑定")


@router.get("/api/auth/email", response_model=ApiEnvelope[dict])
def read_email(user: dict = Depends(get_current_user)):
    """**需登录**：读当前账号的绑定邮箱（脱敏）。

    未绑定 → `{"email": "", "bound": False}`：个人中心据此显示「立即绑定」或「更换」。
    回脱敏值而不是完整邮箱 —— 这个响应没有「需要完整地址」的用途，少一处泄露面。
    """
    email = (user.get("email") or "").strip()
    if not email:
        return ok({"email": "", "bound": False})
    return ok({"email": mailer.mask_email(email), "bound": True})
