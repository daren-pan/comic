"""邮件通道：SMTP 发验证码（标准库 `smtplib`，**不引第三方依赖**）。

为什么落在 `api-service` 而不是 `comic-core`：核心包是「不依赖 HTTP 框架的共用内核」，
发信是 api 侧的出站动作，且只有 api 用。

## 配置（全部走环境变量，**每次发送时读取** —— 改配置不必改代码）

| 变量 | 默认 | 说明 |
|---|---|---|
| `COMIC_SMTP_HOST` | 空 | 如 `smtp.qq.com`；空 = 未配置 |
| `COMIC_SMTP_PORT` | `587` | `465` 时自动走 `SMTP_SSL` |
| `COMIC_SMTP_USER` | 空 | 登录名 / 发件账号 |
| `COMIC_SMTP_PASSWORD` | 空 | 口令或**授权码**；只从 env 读，**不入库、不进日志** |
| `COMIC_SMTP_TLS` | `1` | 587 走 `starttls()` |
| `COMIC_MAIL_FROM` | = `COMIC_SMTP_USER` | 发件人显示地址 |
| `COMIC_MAIL_FALLBACK` | 空 | `log` = 未配置 / 发信失败时把验证码写 WARNING 日志并视为成功（**仅本地开发与验收用**） |

## 行为约定

- **不抛异常**：成功返回 `True`，未配置 / 失败返回 `False`（由调用方决定 503 还是重试）；
- 正常路径**绝不打印验证码**，只有 `COMIC_MAIL_FALLBACK=log` 时才打印；
- 失败日志里的收件人做**脱敏**（`ab***@qq.com`），绝不打印授权码；
- 超时 **10 秒**：必须小于前端请求层的 10s（`comic-web/src/api/request.ts` 的 `TIMEOUT`），
  否则前端先报超时，用户根本看不到后端的 503 文案。
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

#: 与 `comic.message` / `comic.admin` 同族：root 上挂着落库 Handler，所以这些 WARNING 会自动进 `log_record`。
logger = logging.getLogger("comic.auth.mail")

#: 必须 < 前端请求层的 10s（见模块头）
TIMEOUT = 10

#: 用途 → 邮件里的中文说法
_PURPOSE_LABEL = {"reset": "找回密码", "bind": "绑定邮箱"}


def _env(name: str, default: str = "") -> str:
    """读环境变量（去空白）；**每次调用都现读** —— 改配置不必重启（与设计 §3.4 一致）。"""
    return (os.environ.get(name) or default).strip()


def mask_email(email: str) -> str:
    """脱敏邮箱：本地名 ≥3 位取前 2 位，否则取首字母，后接 `***`；域名原样。

    `ab@qq.com` → `a***@qq.com`；`abc@qq.com` → `ab***@qq.com`。
    无 `@` 的脏值整串打码，避免把意外内容原样写进日志。
    """
    text = (email or "").strip()
    local, sep, domain = text.partition("@")
    if not sep:
        return "***"
    head = local[:2] if len(local) >= 3 else local[:1]
    return f"{head}***@{domain}"


def is_configured() -> bool:
    """是否配了可用的 SMTP（要有主机 + 发件地址；发件地址缺省取登录名）。"""
    return bool(_env("COMIC_SMTP_HOST")) and bool(_env("COMIC_MAIL_FROM") or _env("COMIC_SMTP_USER"))


def _fallback_log(to_email: str, code: str) -> bool:
    """`COMIC_MAIL_FALLBACK=log` 时把验证码写 WARNING 日志并视为成功；否则返回 `False`。

    ⚠️ **仅供本地开发 / 验收**：日志会进 `log_record` 表，等于把凭证展示给所有管理员，
    生产环境绝不能开。
    """
    if _env("COMIC_MAIL_FALLBACK").lower() != "log":
        return False
    logger.warning(
        "【邮件降级】未真实发信，收件人=%s 验证码 %s（COMIC_MAIL_FALLBACK=log，仅限本地开发 / 验收）",
        mask_email(to_email),
        code,
    )
    return True


def _build_message(to_email: str, code: str, purpose: str) -> EmailMessage:
    label = _PURPOSE_LABEL.get(purpose, "邮箱验证")
    msg = EmailMessage()
    msg["Subject"] = f"【聚漫画】{label}验证码：{code}"
    msg["From"] = _env("COMIC_MAIL_FROM") or _env("COMIC_SMTP_USER")
    msg["To"] = to_email
    msg.set_content(
        f"您好！\n\n"
        f"您正在{label}，本次验证码为：\n\n"
        f"    {code}\n\n"
        f"验证码 10 分钟内有效，且只能使用一次。\n"
        f"如果这不是您本人的操作，请忽略本邮件 —— 您的账号与密码不会有任何变化。\n\n"
        f"—— 聚漫画\n"
    )
    return msg


def send_verify_code(to_email: str, code: str, purpose: str) -> bool:
    """发一封验证码邮件 → 成功 `True`；未配置 / 失败 `False`（**不抛异常**）。

    `purpose`：`reset`（找回密码）/ `bind`（绑定邮箱），只影响邮件文案。
    发信失败时**不在这里删库**：删刚插入的码行是调用方（`services/email_codes.issue`）的职责，
    这样"删行 + 503"这一对语义只在一处。
    """
    if not is_configured():
        logger.warning("发送验证码邮件失败 email=%s reason=SMTP 未配置", mask_email(to_email))
        return _fallback_log(to_email, code)

    host = _env("COMIC_SMTP_HOST")
    try:
        port = int(_env("COMIC_SMTP_PORT", "587") or 587)
    except ValueError:
        port = 587
    user = _env("COMIC_SMTP_USER")
    password = _env("COMIC_SMTP_PASSWORD")
    use_ssl = port == 465                       # 465 = SMTPS（隐式 TLS），其余走明文 + 可选 STARTTLS
    use_tls = _env("COMIC_SMTP_TLS", "1").lower() not in ("0", "false", "no", "off")
    msg = _build_message(to_email, code, purpose)

    try:
        client = (
            smtplib.SMTP_SSL(host, port, timeout=TIMEOUT)
            if use_ssl
            else smtplib.SMTP(host, port, timeout=TIMEOUT)
        )
        with client:                            # 退出时自动 quit（异常时也会尽力断开）
            if not use_ssl and use_tls:
                client.starttls()
            if user and password:
                client.login(user, password)
            client.send_message(msg)
    except Exception as e:  # 网络 / 认证 / 被拒收都归一处：不让发信失败变成 500
        logger.warning("发送验证码邮件失败 email=%s reason=%s", mask_email(to_email), e)
        return _fallback_log(to_email, code)
    return True
