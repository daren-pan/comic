"""一次性迁移：补上消息中心的两张表 / 两个新列（按角色与指定用户推送）。

背景：消息中心最初做成"仅管理员"、且**已读是全局一份**。2026-10-06 改成**面向所有登录用户**
的通知中心，于是需要：

- `message.to_user_id` / `message.min_role`：**收件范围**（定向某人 / 最低角色要求）；
- 新表 `message_read(message_id, user_id, read_at)`：**已读按账号各一份** ——
  广播消息 A 读过不该把 B 的角标也清掉（这正是"全局一份"做不到的）；
- `message.params`：**入参快照**（`since`/`until`/`mode`/`limit`…）—— 列表里据此显示
  "这条消息说的是哪段时间范围内的数据"（`since` = 起始时间，为空 = 按源自身水位）；
- 去掉 `message.read_at`（被 `message_read` 取代；本表当天才建，若已有已读标记会打印提示）。

**DDL 唯一真源是 `comic-core/sql/mysql_schema.sql`** —— 建表语句从那里**抠出来**执行，
不复制一份（避免两处漂移）；`ALTER` 部分是本脚本特有的（"只建表"的脚本补不了列）。

**幂等**：`CREATE TABLE IF NOT EXISTS` + 先查 `information_schema` 再 `ALTER`，可重复运行。
**可回滚**（表里只有消息与已读记账，删掉不损业务数据）：
    DROP TABLE message_read;
    ALTER TABLE message DROP COLUMN to_user_id, DROP COLUMN min_role, ADD COLUMN read_at DATETIME NULL;

用法（在 comic 仓库根目录）：
    cd crawler-service && .venv/Scripts/python.exe ../tools/add_message_table.py
连接参数用环境变量 `COMIC_MYSQL_*` 覆盖（默认兜底读仓库根 `deploy/.env`：宿主 `127.0.0.1:3309`）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "comic-core", "src"))

from comic_core.storage.mysql import MySQLStorage  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
# ⚠️ 这是**运行时读取**的真实路径（下方 _ddl() 会 read_text）——
#    schema 已随存储域迁到公共内核，不再是 crawler-service/sql/。
SCHEMA_FILE = REPO_ROOT / "comic-core" / "sql" / "mysql_schema.sql"

#: 要确保存在的表（顺序即依赖顺序；DDL 都从 schema 抠）
TABLES: tuple[str, ...] = ("message", "message_read")

#: `message` 需要补的列（列名 → 加列语句；老库的 message 建得早，缺这几个）
MESSAGE_NEW_COLUMNS: dict[str, str] = {
    "to_user_id": "ALTER TABLE message ADD COLUMN to_user_id INT NULL AFTER username",
    "min_role": "ALTER TABLE message ADD COLUMN min_role VARCHAR(16) NOT NULL DEFAULT '' AFTER to_user_id",
    # 入参快照：让列表能显示"这条消息对应哪段时间范围"（since/until/mode/limit…）
    "params": "ALTER TABLE message ADD COLUMN params JSON NULL AFTER body",
}

#: 已废弃的列（被 message_read 取代）：名 → 删列语句
MESSAGE_DROPPED_COLUMNS: dict[str, str] = {
    "read_at": "ALTER TABLE message DROP COLUMN read_at",
}


def _ddl(table: str) -> str:
    """从 schema 文件里抠出建表语句（唯一真源，不在这里重抄一份 DDL）。"""
    text = SCHEMA_FILE.read_text(encoding="utf-8")
    marker = f"CREATE TABLE IF NOT EXISTS {table} ("
    try:
        start = text.index(marker)
    except ValueError:  # pragma: no cover
        raise SystemExit(f"❌ {SCHEMA_FILE} 里找不到 {table} 的建表语句")
    return text[start : text.index(";", start) + 1]


def _columns(store: MySQLStorage, table: str) -> list[str]:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                   ORDER BY ORDINAL_POSITION""",
                (table,),
            )
            return [str(r["c"]) for r in cur.fetchall()]


def _count(store: MySQLStorage, table: str) -> int:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            return int(cur.fetchone()["n"])


def _run(store: MySQLStorage, sql: str) -> None:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)


def main() -> int:
    store = MySQLStorage()

    # ---------- 1) 建表（新库/已删表的情况） ----------
    for table in TABLES:
        if _columns(store, table):
            print(f"  = 表 {table} 已存在")
            continue
        _run(store, _ddl(table))
        print(f"  + 已创建表 {table}")

    # ---------- 2) 已存在的 message 补列 / 去旧列 ----------
    cols = _columns(store, "message")
    for name, sql in MESSAGE_NEW_COLUMNS.items():
        if name in cols:
            print(f"  = message.{name} 已存在，跳过")
            continue
        _run(store, sql)
        print(f"  + 已加列 message.{name}")
    for name, sql in MESSAGE_DROPPED_COLUMNS.items():
        if name not in cols:
            print(f"  = message.{name} 不存在，跳过")
            continue
        read_rows = _count(store, "message") if name == "read_at" else 0
        if read_rows:
            print(f"  ⚠️ message 里还有 {read_rows} 条消息（旧 read_at 的已读标记不再使用）")
        _run(store, sql)
        print(f"  - 已删除废弃列 message.{name}（已读改由 message_read 按账号记）")

    # ---------- 3) 复查 ----------
    print()
    for table in TABLES:
        cols = _columns(store, table)
        print(f"复查：{table} 共 {len(cols)} 列 —— {', '.join(cols)}")
        print(f"      {table} 现有 {_count(store, table)} 行")
    print("\n回滚（如需）：DROP TABLE message_read;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
