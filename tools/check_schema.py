"""体检：库里的表是否与 DDL 真源一致（上线最常漏的就是"新表没建"）。

为什么需要单独一个脚本：`up.sh --migrate` 里的迁移脚本都是**按需**干活的 ——
表已存在时它们只打印一句「已存在，未改动」就退出，**看不出来到底建上了没有**；
而漏表的后果是运行期才炸（管理台任务列表 / 消息中心直接报错）。本脚本**只读不写**：
把 schema 里 `CREATE TABLE` 的表名与库里的实际表名对一遍，缺谁一目了然。

用法（在 comic 仓库根目录）：
    cd crawler-service && .venv/Scripts/python.exe ../tools/check_schema.py

容器里（`up.sh --migrate` 与自检就是这么调的）：
    docker compose -f deploy/docker-compose.yml run --rm \\
        -v ../tools:/app/tools:ro -v ../comic-core/sql:/app/comic-core/sql:ro \\
        comic-app python tools/check_schema.py

退出码：`0` = 表齐全；`1` = 缺表（并打印怎么补）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "comic-core", "src"))

from comic_core.storage.mysql import MySQLStorage  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
# ⚠️ 运行时读取的真实路径（容器里跑必须把 comic-core/sql 挂进来，见文件头）
SCHEMA_FILE = REPO_ROOT / "comic-core" / "sql" / "mysql_schema.sql"

#: 从 schema 里抠"应存在的表" —— 唯一真源，不在这里手抄一份表名清单（抄了就会漂移）
TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+`?(\w+)`?", re.IGNORECASE)


def _schema_text() -> str:
    if not SCHEMA_FILE.exists():
        raise SystemExit(
            f"[错误] 找不到 {SCHEMA_FILE}\n"
            "   DDL 唯一真源是 comic-core/sql/mysql_schema.sql；容器里跑要把它挂进去：\n"
            "     -v ../tools:/app/tools:ro -v ../comic-core/sql:/app/comic-core/sql:ro\n"
            "   （up.sh --migrate 已带这两个挂载）"
        )
    return SCHEMA_FILE.read_text(encoding="utf-8")


def expected_tables() -> list[str]:
    """schema 里声明的表（顺序即建表顺序）。"""
    return TABLE_RE.findall(_schema_text())


def actual_tables(store: MySQLStorage) -> set[str]:
    """库里实际存在的表。"""
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT TABLE_NAME AS t FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA = DATABASE()"""
            )
            return {str(r["t"]) for r in cur.fetchall()}


def main() -> int:
    want = expected_tables()
    have = actual_tables(MySQLStorage())
    missing = [t for t in want if t not in have]

    print(f"  DDL 真源 {SCHEMA_FILE.name}：{len(want)} 张表 ｜ 库里 {len(have)} 张")
    extra = sorted(have - set(want))
    if extra:
        print(f"  · 库里多出（历史遗留，不影响运行）：{', '.join(extra)}")
    if not missing:
        print(f"  [OK] 表齐全：{', '.join(want)}")
        return 0

    print(f"  [缺表] 缺 {len(missing)} 张表：{', '.join(missing)}")
    print("     补表（幂等，可重复跑）——")
    print("       容器/上线：bash deploy/up.sh --migrate")
    print("       本地直跑：cd crawler-service && .venv/Scripts/python.exe ../tools/add_admin_task_table.py")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
