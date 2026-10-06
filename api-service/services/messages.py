"""消息中心（`message` 表 + 已读记账 `message_read` + 「正在跑的任务」）—— 所有登录用户的**通知中心**。

## 谁能看到什么

消息带**收件范围**（`to_user_id` / `min_role`，见 `mysql_schema.sql`）：

| 场景 | 收件范围 | 谁能看到 |
|---|---|---|
| 采集/巡检等**任务**消息 | `min_role='admin'` | 管理员 + 超管 |
| 全员通知（活动、维护公告） | `min_role=''` | 所有登录用户 |
| 定向通知（"你收藏的作品更新了"） | `to_user_id=<某人>` | 只有他 |
| 只给超管 | `min_role='superadmin'` | 只有超管 |

判定口径只有一个纯函数：`message_store.visible_roles(role)`（"最低角色要求"语义，
所以 `min_role='admin'` 时超管也看得到 —— 超管是管理员的超集）。

## 一个来源还是两个？

**消息只来自 `message` 表**，但列表里还会出现"**正在跑**的任务"——它们是**活的状态**，
还没「发生完」，所以不写消息行；由 `feed()` 在返回时临时并进来（跑完由任务侧发那条消息）。
这样同一件事**不会**在任务表与消息表里各存一份状态（两份迟早不一致）。
⚠️ 任务消息是管理员范围的，所以**只有管理员及以上的列表里**才会出现"正在跑的任务"。

## 读写契约

- 读：`feed(user, ...)`（列表，含未读数）、`unread_count(user)`
- 写：`publish()` —— **只此一处**（`POST /api/messages` 调它；api 自己的任务收尾也调它）。
  写入口唯一，是为了让校验/收敛/收件范围兜底只实现一遍。
- 已读：`mark_read()` / `mark_all_read()` —— **按账号各一份**（`message_read` 表）

前端契约用驼峰（与其它接口一致），DB 行到契约的转换在 `_to_contract()` 里。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

_logger = logging.getLogger("comic.message")

#: 列表默认/上限条数
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

#: 任务类消息的收件范围（管理台的事，普通用户不需要看）
TASK_MIN_ROLE = "admin"

#: 各任务类型的中文名（标题用；与前端 `kindLabel` 取值一致）
_KIND_LABELS = {
    "sync": "采集",
    "transfer": "转存",
    "inspect": "巡检",
    "heal": "封面自愈",
    "import": "按需导入",
    "schedule": "定时轮次",
    "system": "系统",
}


def _store():
    """消息表读写句柄（**测试可替换**：换成内存假实现即可脱离 MySQL 断言逻辑）。"""
    from comic_core.storage.mysql.message_store import MySQLMessageStore

    return MySQLMessageStore()


def _task_store():
    from comic_core.storage.mysql.task_store import MySQLTaskStore

    return MySQLTaskStore()


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind or "消息")


def _iso(value) -> str | None:
    """时间 → 前端好解析的 ISO 字符串（`T` 分隔）。字符串一律归一，别把空格形式丢给 JS。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value).strip().replace(" ", "T")


def _params_of(row: dict) -> dict | None:
    """入参快照：JSON 列（pymysql 给的是字符串）→ dict；坏数据不算错，返回 None。

    列表里据此显示"这条消息说的是哪段时间范围内的数据"（见前端的 `paramSummary`）。
    """
    value = row.get("params")
    if isinstance(value, (dict, list)):
        return value           # type: ignore[return-value]
    if isinstance(value, (str, bytes)) and value:
        try:
            decoded = json.loads(value)
        except Exception:
            _logger.warning("message.params 不是合法 JSON，忽略：%r", value)
            return None
        return decoded if isinstance(decoded, (dict, list)) else None
    return None


def _to_contract(row: dict) -> dict:
    """消息行 → 前端契约（驼峰）。`read` 由 `LEFT JOIN message_read`（本人）算出来。"""
    return {
        "id": f"msg-{row.get('id')}",          # 字符串 id：与"正在跑的任务"（用任务号）同一个字段
        "messageId": row.get("id"),            # 标记已读要用的数字 id（任务条目为 null）
        "kind": row.get("kind") or "system",
        "level": row.get("level") or "info",
        "title": row.get("title") or "",
        "body": row.get("body") or "",
        "params": _params_of(row),             # 入参快照（含起始时间 since）
        "taskId": row.get("task_id") or "",
        "source": row.get("source") or "",
        "username": row.get("username") or "",
        "minRole": row.get("min_role") or "",
        "status": "failed" if row.get("level") == "error" else "done",
        "time": _iso(row.get("created_at")),
        "read": row.get("read_at") is not None,
    }


def _running_to_contract(task: dict) -> dict:
    """正在跑的任务 → 消息条目（临时条目：还没有 message 行）。

    ⚠️ 也带上 `params`：**在跑的时候就要能看出这轮的时间范围**（比如"起始 2026-10-01"），
    等它跑完，那条正式消息里同样带着这份入参。
    """
    kind = task.get("task_type") or "system"
    return {
        "id": task.get("task_id"),             # 用任务号做 id：跑完那条消息另有 id，不会撞
        "messageId": None,
        "kind": kind,
        "level": "info",
        "title": f"{kind_label(kind)}进行中…",
        "body": "任务运行中，完成后会在这里再发一条结果消息",
        "params": _params_of(task),
        "taskId": task.get("task_id") or "",
        "source": "",
        "username": task.get("username") or "",
        "minRole": TASK_MIN_ROLE,
        "status": "running",
        "time": _iso(task.get("started_at")),
        "read": True,                          # 运行中的不计未读
    }


def _sees_tasks(user: dict | None) -> bool:
    """这个人能不能看到任务类消息（决定列表里要不要并入"正在跑的任务"）。"""
    from comic_core.storage.mysql.message_store import visible_roles

    return TASK_MIN_ROLE in visible_roles((user or {}).get("role"))


def feed(user: dict, limit: int = DEFAULT_LIMIT, unread_only: bool = False) -> dict:
    """**发给这个账号的**消息列表 + 未读数，按时间倒序。

    返回 `{items, unread}` —— 未读数与列表一次拿回，前端轮询只发一个请求。
    管理员及以上的列表里还会并入"正在跑的任务"（活状态，见模块 docstring）。
    """
    size = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    store = _store()
    rows = store.list(user=user, limit=size, unread_only=unread_only)
    items = [_to_contract(r) for r in rows]

    if not unread_only and _sees_tasks(user):   # 只看未读时不掺运行中的任务（它们不算未读）
        try:
            running = [t for t in _task_store().recent(size) if t.get("status") == "running"]
            items.extend(_running_to_contract(t) for t in running)
        except Exception:    # 任务表读不到不该让消息列表整体失败
            _logger.exception("读取运行中的任务失败（消息列表不包含它们）")
        items.sort(key=lambda it: (it.get("time") or "", str(it.get("id") or "")), reverse=True)
        items = items[:size]

    try:
        unread = store.unread_count(user)
    except Exception:
        _logger.exception("统计未读数失败")
        unread = sum(1 for it in items if not it.get("read") and it.get("status") != "running")
    return {"items": items, "unread": unread}


def unread_count(user: dict) -> int:
    return _store().unread_count(user)


def publish(payload: dict) -> dict:
    """发一条消息（**写入口唯一**）。

    `payload` 用前端契约的驼峰（`taskId` / `userId` / `toUserId` / `minRole` / `params` / `kind` /
    `level` / `title` / `body`…），存储层负责收敛脏值（未知 `level` 落 `info`、未知 `minRole` 落
    "所有登录用户"、`params` 截断、超长截断）。返回新建的条目。
    """
    row = {
        "kind": payload.get("kind") or "system",
        "level": payload.get("level") or "info",
        "title": payload.get("title") or "",
        "body": payload.get("body") or "",
        "params": payload.get("params"),
        "task_id": payload.get("taskId") or "",
        "source": payload.get("source") or "",
        "user_id": payload.get("userId"),
        "username": payload.get("username") or "",
        "to_user_id": payload.get("toUserId"),
        "min_role": payload.get("minRole") or "",
        "created_at": payload.get("createdAt") or datetime.now(),
    }
    msg_id = _store().publish(row)
    row["id"] = msg_id
    row["read_at"] = None
    return _to_contract(row)


def publish_task(task: dict) -> dict | None:
    """任务收尾时发一条消息（**api 内部直调**，不走 HTTP；收件范围 = 管理员及以上）。

    ⚠️ 发货失败只记 warning：消息是可观测性，不该让任务本身失败。
    """
    try:
        from comic_core.storage.mysql.message_store import task_message

        row = task_message(task)
        msg_id = _store().publish(row)
        row["id"] = msg_id
        row["read_at"] = None
        return _to_contract(row)
    except Exception:
        _logger.exception("任务 %s 的消息发布失败（不影响任务结果）", task.get("task_id"))
        return None


def mark_read(message_id: int, user: dict) -> int:
    """标记"**我**读过这条"，返回新增的记账行数（0 = 本来已读）。"""
    return _store().mark_read(int(message_id), user)


def mark_all_read(user: dict) -> int:
    """把**我看到的**全部标为已读，返回新增的记账行数（别人不受影响）。"""
    return _store().mark_all_read(user)
