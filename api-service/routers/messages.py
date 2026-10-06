"""消息中心 HTTP 接口（`/api/messages`）—— **所有登录用户**读，其他模块写。

## 谁能调

| 接口 | 门槛 | 谁在用 |
|---|---|---|
| `GET /api/messages` / `GET /api/messages/unread` | **`get_current_user`（登录即可）** | 顶栏铃铛、消息页（内容按**当前账号**的收件范围过滤） |
| `POST /api/messages` | `require_admin_or_service` | api 自己（任务收尾）、`comic-scheduler`（服务令牌）、运维脚本、外部系统 |
| `POST /api/messages/{id}/read` / `read-all` | `get_current_user` | 消息页（**按账号各记一份**） |

⚠️ **可见范围由数据决定，不由接口决定**：同一条 `GET /api/messages`，普通用户只看到
`min_role=''`/`'user'` 或定向发给他的消息；管理员还多看到任务消息（`min_role='admin'`）。
判定口径只有一处：`comic_core.storage.mysql.message_store.visible_roles`。

⚠️ **写入只有这一个入口**（2026-10-06 定）：校验与收敛（`kind`/`level`/`minRole` 合法值、
长度上限、鉴权）都在这条路上实现一遍，别的进程就不会绕过去写脏数据。进程间调用带
`X-Service-Token`（HMAC，见 `comic_core/notify.py`），不必为机器造账号。

## 为什么列表里会有"正在跑的任务"

消息表里只有**发生完的事**；正在跑的任务是**活的状态**，由 `services.messages.feed()` 临时并进来
（**仅管理员及以上** —— 任务消息本来就是管理员范围的）。好处是同一件事不会在任务表与消息表里
各存一份状态，而定时轮次在跑的时候就能看见。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.responses import ok
from core.security import get_current_user, require_admin_or_service
from schemas import MessageBody
from services import messages

router = APIRouter(tags=["messages"])


@router.get("/api/messages")
def list_messages(limit: int = 50, unread_only: bool = False,
                  user: dict = Depends(get_current_user)):
    """**发给我的**消息列表（最近 N 条）+ 未读数。

    可见范围：定向发给我的（`toUserId`）+ 我这个角色够得着的（`minRole`，见模块 docstring）。
    `unread_only=true` 只返回未读（此时不掺"正在跑的任务"—— 它们不算未读）。
    返回形状：`{items: [...], unread: N}`；`items[].id` 字符串（消息 = `msg-<id>`，
    正在跑的任务 = 任务号），标记已读要用 `messageId`（任务条目为 `null`）。
    """
    return ok(messages.feed(user, limit=limit, unread_only=unread_only))


@router.get("/api/messages/unread")
def unread(user: dict = Depends(get_current_user)):
    """我的未读数（只给角标用；列表接口本来也会带回来）。"""
    return ok({"unread": messages.unread_count(user)})


@router.post("/api/messages")
def publish_message(body: MessageBody, auth: dict = Depends(require_admin_or_service)):
    """发一条消息 —— **其他模块的写入入口**。

    - 管理台/外部系统：带管理员 JWT；
    - 进程间：带 `X-Service-Token`（由 `comic_core.notify.publish_message` 生成）。

    **收件范围**（不填 = 所有登录用户）：`toUserId` 定向某人；`minRole` 最低角色要求
    （`''`/`user` < `admin` < `superadmin`，`admin` 时超管也看得到）。
    `kind` 自由（任务消息用任务类型：`sync`/`inspect`/`heal`/`import`/`schedule`；
    其它写者自定义，如 `system`/`notice`）；`level` 取 `info`/`warn`/`error`（非法值落 `info`）。
    """
    return ok(messages.publish(body.model_dump()))


@router.post("/api/messages/{message_id}/read")
def mark_read(message_id: int, user: dict = Depends(get_current_user)):
    """把某一条标记为**我**已读（`message_id` 是列表里的 `messageId`）；别人的未读不受影响。"""
    return ok({"changed": messages.mark_read(message_id, user)})


@router.post("/api/messages/read-all")
def mark_all_read(user: dict = Depends(get_current_user)):
    """把**我看到的**全部标为已读（按账号各一份：`message_read` 表）。"""
    return ok({"changed": messages.mark_all_read(user)})
