"""消息中心的 MySQL 读写（`message` 表 + 已读记账 `message_read`）。

三个使用方：

- **写入**：api 的 `services/messages.publish()`（任务收尾、以及 `POST /api/messages` 的外部写入）；
- **读取**：`list()` —— 按**当前账号**的收件范围过滤（见 `visible_roles()`）；
- **已读**：`mark_read()` / `mark_all_read()` —— **按账号各一份**（`message_read` 表）。

为什么单独一个类、不并进 `MySQLStorage`：与 `log_store` / `task_store` 同一理由 —— 消息是
"只看最近"的流水，查询方式（未读/时间窗/类型）与保留策略都与主数据无关。

`task_message()` 是**任务 → 消息**的形状转换（收件范围固定为"管理员及以上"），放在这里是因为
`comic-scheduler`（另一个进程）与 api 都要用它 —— 两边发出来的消息必须长得一样。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from ._pool import pooled_conn
from ._util import _DSN

logger = logging.getLogger(__name__)

#: 入库列（`id` 自增；已读在 `message_read` 表里按账号记，不在本表）
MESSAGE_COLUMNS: tuple[str, ...] = (
    "kind", "level", "title", "body", "params", "task_id", "source",
    "user_id", "username", "to_user_id", "min_role", "created_at",
)

#: 列表返回的列（**不含** `read_at` —— 它来自 JOIN `message_read`，见 `list()`）
LIST_COLUMNS: tuple[str, ...] = ("id",) + MESSAGE_COLUMNS

#: 级别（前端据此显示 完成/警告/失败）
LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"
LEVELS: tuple[str, ...] = (LEVEL_INFO, LEVEL_WARN, LEVEL_ERROR)

#: 角色档次（与 api 的 `core/security.py` 一致；用于把 `min_role` 展开成"此人能看到哪些"）
_ROLE_RANK = {"user": 1, "admin": 2, "superadmin": 3}

#: 单次最多返回多少条
MAX_LIMIT = 200

#: 各任务类型的中文名（标题用；与前端 `kindLabel` 的取值保持一致）
_KIND_LABELS = {
    "sync": "采集",
    "transfer": "转存",
    "inspect": "巡检",
    "heal": "封面自愈",
    "import": "按需导入",
    "schedule": "定时轮次",
    "system": "系统",
}


def visible_roles(role: str | None) -> tuple[str, ...]:
    """**这个角色能看到哪些 `min_role` 的取值** —— 可见性的唯一口径（纯函数，便于单测）。

    语义是"**最低角色要求**"：`min_role='admin'` 的消息，超管也看得到（超管是管理员的超集）；
    `min_role=''` 表示所有登录用户（读接口本身要求登录，所以不等同于"匿名也能看"）。
    认不出的角色按最低档处理（宁可少看，不可越权）。
    """
    rank = _ROLE_RANK.get(str(role or ""), 1)
    return tuple(name for name, r in _ROLE_RANK.items() if r <= rank) + ("",)


def _visibility_clause(user: dict | None) -> tuple[str, list]:
    """`(WHERE 片段, 参数)`：只返回**发给这个人**的消息（定向某人 + 角色档）。

    `user=None`（无账号）→ 什么都不返回（读接口本来也要求登录）。
    """
    if not user:
        return "1 = 0", []
    roles = visible_roles(user.get("role"))
    placeholders = ", ".join(["%s"] * len(roles))
    clause = f"(to_user_id IS NULL OR to_user_id = %s) AND min_role IN ({placeholders})"
    return clause, [user.get("id"), *roles]


def task_message(task: dict) -> dict:
    """**任务 → 消息**（api 与 `comic-scheduler` 共用；形状只此一份）。

    `task` = 一行任务（`admin_task` 的 DB 形状）：`task_id / task_type / status / message /
    result / username / user_id / finished_at`。

    规则：
    - **标题** = 「类型完成 / 类型失败」（一眼看出是什么、成没成）；
    - **级别** = done → `info`、failed → `error`（任务成败由级别承载，不再另设 status 列）；
    - **正文** = 服务端算好的整句（`result.summary`，定时轮次/按需导入有）→ 否则按类型拼统计 →
      否则用任务自己的 `message`；
    - **收件范围 = 管理员及以上**（`min_role='admin'`）：采集/巡检是管理台的事，普通用户不需要看；
    - `source`：单源任务取 `result` / `params` 里的源名（供列表显示"哪来的"）。
    """
    task_type = str(task.get("task_type") or "")
    label = _KIND_LABELS.get(task_type, task_type or "任务")
    status = str(task.get("status") or "")
    result = task.get("result") or {}
    if not isinstance(result, dict):
        result = {}

    title = f"{label}{'失败' if status == 'failed' else '完成'}"
    body = _body_of(task_type, status, result, str(task.get("message") or ""))
    level = LEVEL_ERROR if status == "failed" else LEVEL_INFO

    params = task.get("params") or {}
    source = ""
    if isinstance(params, dict):
        srcs = params.get("sources")
        source = "、".join(str(s) for s in srcs) if isinstance(srcs, list) else str(params.get("source") or "")

    return {
        "kind": task_type or "system",
        "level": level,
        "title": title,
        "body": body,
        # 入参快照：列表据此显示"哪段时间范围"（`since` = 起始时间，空 = 按源自身水位）
        "params": task.get("params") or None,
        "task_id": str(task.get("task_id") or ""),
        "source": source,
        "user_id": task.get("user_id"),
        "username": str(task.get("username") or ""),
        "to_user_id": None,
        "min_role": "admin",     # 任务消息只给管理员及以上看
        "created_at": _as_datetime(task.get("finished_at")),
    }


def _as_datetime(value) -> datetime:
    """把任务行里的时间归一到 `datetime`。

    ⚠️ 任务行的出参（`task_store._row_out`）是 **ISO 字符串**（`2026-10-06T17:04:55`），直接塞进
    MySQL 的 DATETIME 列会因为那个 `T` 报错/截断 —— 这里统一换回空格分隔（或直接解析）。
    """
    if value is None or value == "":
        return datetime.now()
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.now()


def _body_of(task_type: str, status: str, result: dict, message: str) -> str:
    """消息正文：优先服务端整句，其次按类型拼统计，最后退回任务 message。"""
    if status == "failed":
        return message or "任务失败"
    summary = result.get("summary")
    if isinstance(summary, str) and summary and task_type == "schedule":
        # 定时轮次：`run_round` 的整句（"定时：成功 3/3 个源"）+ 每源明细
        detail = _round_detail(result)
        return f"{summary}｜{detail}" if detail else summary
    stats = result.get("stats")
    if task_type == "sync" and isinstance(stats, dict):
        return (
            f"扫描 {stats.get('total_seen', 0)} 部 | 新增 {stats.get('new_comics', 0)}"
            f" | 更新 {stats.get('updated_comics', 0)} | 新增章节 {stats.get('new_chapters', 0)}"
            f" | 失败 {stats.get('failed', 0)}"
        )
    if task_type == "inspect":
        return (
            f"校验 {result.get('checked', 0)} | 转存 {result.get('transferred', 0)}"
            f" | 恢复 {result.get('recovered', 0)} | 失效 {result.get('invalid', 0)}"
        )
    if task_type == "heal":
        return (
            f"检查 {result.get('checked', 0)} | 修复 {result.get('healed', 0)}"
            f" | 跳过 {result.get('skipped', 0)} | 失败 {result.get('failed', 0)}"
        )
    if isinstance(summary, str) and summary:
        return summary
    return message if message and message != "ok" else "已完成"


def _round_detail(result: dict) -> str:
    results = result.get("results")
    if not isinstance(results, dict):
        return ""
    parts = []
    for name, value in results.items():
        if isinstance(value, dict):
            text = value.get("summary") or value.get("error") or ""
            parts.append(f"{name}: {text}" if text else str(name))
    return " · ".join(parts)


class MySQLMessageStore:
    """`message` 表的读写（连接来自**共享池**，见 `._pool`）。"""

    def __init__(self, dsn: dict | None = None) -> None:
        self.dsn = dsn or _DSN

    # ---------------- 写入 ----------------
    def publish(self, payload: dict) -> int:
        """发一条消息，返回自增 id。`level` / `min_role` / `kind` 会被收敛到合法值。

        写者可能是外部系统，所以这里对**收件范围**也做兜底：`min_role` 认不出就落 `''`
        （所有登录用户）—— 宁可是"发宽了"也不要是"发得没人看得见"？不对：认不出说明写错了，
        按最严处理会让人以为接口没生效。这里选**落默认（所有人）**，并在日志里留一条 warning。
        """
        row = {c: payload.get(c) for c in MESSAGE_COLUMNS}
        row["kind"] = str(row.get("kind") or "system")[:16]
        row["level"] = row["level"] if row.get("level") in LEVELS else LEVEL_INFO
        row["title"] = str(row.get("title") or "")[:255]
        row["body"] = str(row.get("body") or "")
        # 入参快照（JSON 列）：只收 dict/list，且截断到 2000 字符 —— 写者可能是外部系统，
        # 不能让它把一整份大对象塞进消息表。
        params = row.get("params")
        row["params"] = (
            json.dumps(params, ensure_ascii=False)[:2000]
            if isinstance(params, (dict, list))
            else None
        )
        row["task_id"] = str(row.get("task_id") or "")[:64]
        row["source"] = str(row.get("source") or "")[:64]
        row["username"] = str(row.get("username") or "")[:64]
        min_role = str(row.get("min_role") or "")
        if min_role and min_role not in _ROLE_RANK:
            logger.warning("消息的 min_role=%r 认不出，按「所有登录用户」处理", min_role)
            min_role = ""
        row["min_role"] = min_role
        row["created_at"] = _as_datetime(row.get("created_at"))
        cols = ", ".join(MESSAGE_COLUMNS)
        placeholders = ", ".join(["%s"] * len(MESSAGE_COLUMNS))
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO message ({cols}) VALUES ({placeholders})",
                    tuple(row[c] for c in MESSAGE_COLUMNS),
                )
                return int(cur.lastrowid or 0)

    # ---------------- 读取 ----------------
    def list(self, *, user: dict | None, limit: int = 50, unread_only: bool = False,
             kind: str | None = None) -> list[dict]:
        """**发给这个账号的**最近消息（按 id 倒序 = 时间倒序，同秒多条也稳定）。

        `read` 由 `LEFT JOIN message_read`（本人）算出来 —— 同一行对不同账号可以是不同值，
        这正是"按账号各一份已读"的意思。
        """
        size = max(1, min(int(limit or 50), MAX_LIMIT))
        vis, params = _visibility_clause(user)
        conds = [vis]
        if unread_only:
            conds.append("r.id IS NULL")
        if kind:
            conds.append("m.kind = %s")
            params.append(str(kind))
        where = " WHERE " + " AND ".join(conds)
        cols = ", ".join(f"m.{c}" for c in LIST_COLUMNS)
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT {cols}, r.read_at AS read_at
                        FROM message m
                        LEFT JOIN message_read r
                               ON r.message_id = m.id AND r.user_id = %s
                        {where}
                        ORDER BY m.id DESC LIMIT %s""",
                    [user.get("id") if user else None, *params, size],
                )
                return list(cur.fetchall())

    def unread_count(self, user: dict | None) -> int:
        """**这个账号**的未读数（顶栏角标）：可见消息里没有本人已读记账的那些。"""
        vis, params = _visibility_clause(user)
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT COUNT(*) AS n
                        FROM message m
                        LEFT JOIN message_read r
                               ON r.message_id = m.id AND r.user_id = %s
                        WHERE {vis} AND r.id IS NULL""",
                    [user.get("id") if user else None, *params],
                )
                return int(cur.fetchone()["n"])

    # ---------------- 已读（按账号各一份） ----------------
    def mark_read(self, msg_id: int, user: dict, *, at: datetime | None = None) -> int:
        """标记"**我**读过这条"，返回受影响行数（重复标记不报错、也不改时间）。

        用 `INSERT ... ON DUPLICATE KEY UPDATE id = id`：并发/重复调用都安全
        （唯一键 `uk_msg_read(message_id, user_id)` 兜住）。
        """
        if not user:
            return 0
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO message_read (message_id, user_id, read_at)
                       VALUES (%s, %s, %s)
                       ON DUPLICATE KEY UPDATE id = id""",
                    (int(msg_id), user.get("id"), at or datetime.now()),
                )
                return int(cur.rowcount)

    def mark_all_read(self, user: dict, *, at: datetime | None = None) -> int:
        """把**当前这个人能看到的**全部消息标为已读，返回新增的记账行数。

        ⚠️ 只记账不删消息；别人（别的账号）的未读不受影响 —— 这是与"全局一份"最本质的差别。
        """
        if not user:
            return 0
        vis, params = _visibility_clause(user)
        stamp = at or datetime.now()
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""INSERT INTO message_read (message_id, user_id, read_at)
                        SELECT m.id, %s, %s
                        FROM message m
                        LEFT JOIN message_read r
                               ON r.message_id = m.id AND r.user_id = %s
                        WHERE {vis} AND r.id IS NULL""",
                    (user.get("id"), stamp, user.get("id"), *params),
                )
                return int(cur.rowcount)

    # ---------------- 保留策略 ----------------
    def purge(self, days: int = 30) -> int:
        """删除 `days` 天前的消息（默认不自动清理，量起来了由运维/脚本调）。"""
        keep = max(1, int(days))
        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM message WHERE created_at < (NOW() - INTERVAL %s DAY)", (keep,))
                return int(cur.rowcount)
