"""一次性迁移：为已有库补上 `log_record` 表（运行日志逐条落库）。

背景：运行日志原先只写文件 `logs/api.log`，管理台靠"读文件末尾 N 行"展示（前端还要每 4 秒轮询）。
现在改为**落库**：日志由 `comic_crawler.storage.mysql.log_handler` 在打日志时批量写进
`log_record`，管理台「日志查询」页按条件筛（级别 / 源站 / 作品 / 章节 / 任务 / 关键字 / 时间窗）。

**DDL 唯一真源是 `crawler-service/sql/mysql_schema.sql`** —— 本脚本从那里**抠出**
`CREATE TABLE IF NOT EXISTS log_record` 语句执行，不复制一份 DDL（避免两处漂移）。
新库用 `scripts/init_mysql.sh` 建库时本来就会带上这张表，本脚本只为已有库补。

**幂等**：`CREATE TABLE IF NOT EXISTS`，可重复运行。
**可回滚**（表里只有日志，删掉不损业务数据）：
    DROP TABLE log_record;

用法（在 comic 仓库根目录）：
    cd crawler-service && PYTHONPATH=src python ../tools/add_log_table.py
连接参数用环境变量 `COMIC_MYSQL_*` 覆盖（默认 127.0.0.1:3307）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler-service", "src"))

from comic_crawler.storage.mysql import MySQLStorage  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = REPO_ROOT / "crawler-service" / "sql" / "mysql_schema.sql"
TABLE = "log_record"


def _ddl() -> str:
    """从 schema 文件里抠出建表语句（唯一真源，不在这里重抄一份 DDL）。"""
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
