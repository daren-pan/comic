"""往消息中心**投递消息**（`POST /api/messages`）—— 给 api 之外的其他进程/模块用。

## 为什么是 HTTP 而不是直接写库

消息中心是**平台级能力**：api、独立进程 `comic-scheduler`、运维脚本、将来的外部系统都可能
往里发消息。约定**写入只走 HTTP 一个入口**（2026-10-06 定）—— 好处是校验/收敛（`kind`/`level`
的合法值、长度上限、鉴权）只有一处实现，不会出现"某个进程绕过接口写了条脏消息"。

api 自己发消息（任务收尾）**不走这里**：同进程直调 `services.messages.publish()`，省一次
自己调自己的 HTTP。

## 鉴权：服务令牌（HMAC，不新增密钥、不新增依赖）

写入接口要挡匿名调用。管理台用管理员 JWT；**进程间调用**用这里的服务令牌：

    X-Service-Token: <ts>.<hexdigest>
    hexdigest = HMAC-SHA256(secret, ts) 的十六进制

- `secret` 复用 `COMIC_JWT_SECRET`（compose 的 `x-app-env` 已经同时给了 app 与 scheduler，
  不必再加一个环境变量）；
- `ts` 是**秒级 Unix 时间戳**，服务端校验 `|now - ts| <= 300s`（防重放，窗口与定时任务的
  宽限窗口同一个量级）；
- 用标准库 `hmac`/`hashlib` 实现 —— 这个模块是 `comic_core` 的一部分，公共内核不引入 JWT 依赖。

## 配置

- `COMIC_API_BASE`：api 的地址（容器里 `http://comic-app:8000`，本地默认 `http://127.0.0.1:8000`）；
- `COMIC_JWT_SECRET`：与 api 共享的密钥（**没有它就只能本机默认值**，生产必须显式配）。

投递失败**不抛异常给调用方**（除非显式传 `raise_on_error=True`）：消息是可观测性，
不该因为它没发出去就让采集/任务失败 —— 调用方记一条 warning 即可。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

#: 一个 API 基础地址（容器里是服务名，本地是 127.0.0.1:8000）
DEFAULT_API_BASE = "http://127.0.0.1:8000"

#: 服务令牌有效期（秒）—— 服务端按同一窗口校验
TOKEN_TTL_SECONDS = 300

#: 请求头名（api 侧 `core/security.py` 用同一个常量名）
SERVICE_TOKEN_HEADER = "X-Service-Token"

#: 单次投递超时（秒）：这是个"顺手发一条"的动作，不该拖住采集
TIMEOUT_SECONDS = 5


def api_base() -> str:
    return (os.environ.get("COMIC_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def service_secret() -> str:
    """与 api 共享的密钥 —— 复用 JWT 密钥（compose 的 x-app-env 已同时注入两个服务）。"""
    return os.environ.get("COMIC_JWT_SECRET") or ""


def make_service_token(secret: str | None = None, *, ts: int | None = None) -> str:
    """造服务令牌：`<ts>.<hmac>`。**纯函数**（时间戳可注入，便于单测）。"""
    key = (secret if secret is not None else service_secret()).encode("utf-8")
    stamp = str(int(ts if ts is not None else time.time()))
    digest = hmac.new(key, stamp.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{stamp}.{digest}"


def verify_service_token(token: str, secret: str | None = None, *, now: int | None = None) -> bool:
    """校验服务令牌（**纯函数**，api 侧与服务端单测共用）。"""
    key = (secret if secret is not None else service_secret()).encode("utf-8")
    if not key or not token or "." not in token:
        return False
    stamp, _, digest = token.partition(".")
    if not stamp.isdigit() or not digest:
        return False
    current = int(now if now is not None else time.time())
    if abs(current - int(stamp)) > TOKEN_TTL_SECONDS:
        return False
    expected = hmac.new(key, stamp.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest)


def publish_message(
    *,
    kind: str = "system",
    level: str = "info",
    title: str = "",
    body: str = "",
    params: dict | None = None,
    task_id: str = "",
    source: str = "",
    user_id: int | None = None,
    username: str = "",
    to_user_id: int | None = None,
    min_role: str = "",
    raise_on_error: bool = False,
) -> dict | None:
    """向 api 投递一条消息，成功返回 `{"id": ...}`，失败返回 `None`（并记 warning）。

    **入参快照** `params`（可选）：任务类消息放 `since`/`until`/`mode`/`limit`/`sources`/`action`…
    —— 消息中心据此显示"这条消息说的是哪段时间范围内的数据"（`since` 就是起始时间）。

    **收件范围**（两个条件同时成立才可见，见 `mysql_schema.sql` 的 `message` 表）：
    - `to_user_id`：定向发给某个人（`None` = 不限人）；
    - `min_role` ：最低角色要求（`''` = 所有**登录**用户；`'user' < 'admin' < 'superadmin'`，
      即 `'admin'` 时超管也看得到）。任务类消息传 `'admin'`。

    `raise_on_error=True` 时把异常抛给调用方（写调用方的单测/脚本用）。
    """
    payload = {
        "kind": kind, "level": level, "title": title, "body": body, "params": params,
        "taskId": task_id, "source": source, "userId": user_id, "username": username,
        "toUserId": to_user_id, "minRole": min_role,
    }
    url = f"{api_base()}/api/messages"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            SERVICE_TOKEN_HEADER: make_service_token(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw or "{}").get("data")
    except Exception as exc:   # noqa: BLE001 —— 投递失败不重要，但也别静默
        if raise_on_error:
            raise
        logger.warning("消息投递失败（%s %s）：%s", kind, title, exc)
        return None
