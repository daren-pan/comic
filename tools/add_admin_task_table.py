"""一次性迁移：为已有库补上 `admin_task` 表（管理台后台任务落库）。

背景：管理台「触发采集 / 巡检 / 封面自愈 / 按需导入」的任务原先登记在**进程内 dict** 里
（`api-service/services/tasks.py`）—— api 一重启，任务就没了、前端那个 `taskId` 再也查不到，
也答不出"这回是谁点的"。落库之后：

- **重启不丢**：残留的 `running` 由 `tasks.reap_stale()` 标成「服务重启，任务中断」；
- **与触发账号绑定**：`user_id` + `username`（冗余一份，账号改名/删号后仍看得懂）。

**DDL 唯一真源是 `comic-core/sql/mysql_schema.sql`** —— 本脚本从那里**抠出**
`CREATE TABLE IF NOT EXISTS admin_task` 语句执行，不复制一份 DDL（避免两处漂移）。
新库用建库脚本时本来就会带上这张表，本脚本只为**已有库**补。

**幂等**：`CREATE TABLE IF NOT EXISTS`，可重复运行。
**可回滚**（表里只有任务记录，删掉不损业务数据）：
    DROP TABLE admin_task;

用法（在 comic 仓库根目录）：
    cd crawler-service && .venv/Scripts/python.exe ../tools/add_admin_task_table.py
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
TABLE = "admin_task"


def _ddl() -> str:
    """从 schema 文件里抠出建表语句（唯一真源，不在这里重抄一份 DDL）。"""
    if not SCHEMA_FILE.exists():
        raise SystemExit(
            f"[错误] 找不到 {SCHEMA_FILE}\n"
            "   DDL 唯一真源是 comic-core/sql/mysql_schema.sql；容器里跑要把它挂进去：\n"
            "     -v ../tools:/app/tools:ro -v ../comic-core/sql:/app/comic-core/sql:ro\n"
            "   （deploy/up.sh --migrate 已带这两个挂载）"
        )
    text = SCHEMA_FILE.read_text(encoding="utf-8")
    marker = f"CREATE TABLE IF NOT EXISTS {TABLE} ("
    try:
        start = text.index(marker)
    except ValueError:  # pragma: no cover
        raise SystemExit(f"❌ {SCHEMA_FILE} 里找不到 {TABLE} 的建表语句")
    return text[start : text.index(";", start) + 1]


def _columns(store: MySQLStorage) -> list[str]:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                   ORDER BY ORDINAL_POSITION""",
                (TABLE,),
            )
            return [str(r["c"]) for r in cur.fetchall()]


def main() -> int:
    store = MySQLStorage()
    existed = bool(_columns(store))
    if not existed:
        with store._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_ddl())
        print(f"  + 已创建表 {TABLE}")
    else:
        print(f"  = 表 {TABLE} 已存在，未改动（本脚本只建表，不加列）")

    cols = _columns(store)
    print(f"\n复查：{TABLE} 共 {len(cols)} 列 —— {', '.join(cols)}")
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM {TABLE}")
            print(f"      现有 {cur.fetchone()['n']} 行任务记录")
    print("\n回滚（如需）：DROP TABLE admin_task;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
