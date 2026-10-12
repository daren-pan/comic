"""一次性迁移：把 mysql_schema.sql 里的**表注释 / 字段注释**刷到已有库。

背景：schema 文件里一直有说明文字，但都是 `--` 行内注释 —— 文件里看得到、**库里看不到**
（Navicat 等客户端的表/字段「注释」列全空）。本脚本把注释真正写进 MySQL 的 COMMENT 元数据，
让任何客户端直接可见。

注释文本与列定义**都从 `comic-core/sql/mysql_schema.sql` 抠出**（唯一真源，不重抄）：
- 表注释 → `ALTER TABLE t COMMENT = '<表注释>'`；
- 字段注释 → `ALTER TABLE t MODIFY COLUMN <schema 里的完整列定义>`（含 COMMENT，顺带把列定义
  对齐到 schema；⚠️ 只改**已存在**的列，缺列跳过并提示先跑对应的补列脚本）。

**幂等**：先对比 information_schema 里的现有注释，一致即跳过；可重复运行。
注释不影响数据，无需回滚 —— 想清空注释就把 schema 里的 COMMENT 去掉重跑。

用法（在 comic 仓库根目录）：
    cd crawler-service && .venv/Scripts/python.exe ../tools/add_table_comments.py
容器里跑要挂 `../tools` 与 `../comic-core/sql`（deploy/up.sh --migrate 已带这两个挂载）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "comic-core", "src"))

from comic_core.storage.mysql import MySQLStorage  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = REPO_ROOT / "comic-core" / "sql" / "mysql_schema.sql"

#: 建表块：`CREATE TABLE IF NOT EXISTS <名> ( ... ) ENGINE=InnoDB ... ;`
_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\) ENGINE=InnoDB[^;]*;", re.S)
#: 表注释（表选项段里的 `COMMENT='...'`；与字段的 `COMMENT '...'` 靠空格区分）
_TABLE_COMMENT_RE = re.compile(r"COMMENT='([^']*)'")
#: 字段注释（列定义里的 `COMMENT '...'`）
_COL_COMMENT_RE = re.compile(r"COMMENT\s+'([^']*)'")
#: 非列定义行（索引 / 约束）
_NON_COLUMN_RE = re.compile(r"^(KEY|UNIQUE|PRIMARY|CONSTRAINT|INDEX|FOREIGN)\b", re.I)
#: MODIFY COLUMN 不接受内联 PRIMARY KEY（主键是表级对象、列上已存在），生成语句时去掉
_PRIMARY_KEY_RE = re.compile(r"\s+PRIMARY\s+KEY\b", re.I)


def _parse_schema() -> dict[str, dict]:
    """→ {表名: {'comment': 表注释, 'columns': {列名: (完整列定义, 字段注释)}}}"""
    if not SCHEMA_FILE.exists():
        raise SystemExit(
            f"[错误] 找不到 {SCHEMA_FILE}\n"
            "   注释真源是 comic-core/sql/mysql_schema.sql；容器里跑要把它挂进去：\n"
            "     -v ../tools:/app/tools:ro -v ../comic-core/sql:/app/comic-core/sql:ro\n"
            "   （deploy/up.sh --migrate 已带这两个挂载）"
        )
    text = SCHEMA_FILE.read_text(encoding="utf-8")
    tables: dict[str, dict] = {}
    for m in _TABLE_RE.finditer(text):
        name, body, block = m.group(1), m.group(2), m.group(0)
        tc = _TABLE_COMMENT_RE.search(block)
        columns: dict[str, tuple[str, str]] = {}
        for line in body.splitlines():
            s = line.strip()
            if not s or s.startswith("--") or _NON_COLUMN_RE.match(s):
                continue
            # 去掉行尾逗号（只去一个，避免把注释文本里的逗号也误伤）
            defn = s[:-1] if s.endswith(",") else s
            col = defn.split(None, 1)[0]
            if not re.match(r"^[A-Za-z_]\w*$", col):
                continue
            cc = _COL_COMMENT_RE.search(defn)
            columns[col] = (defn, cc.group(1) if cc else "")
        tables[name] = {"comment": tc.group(1) if tc else "", "columns": columns}
    return tables


def _fetch(store: MySQLStorage) -> tuple[dict, dict]:
    """库中现状：{表: 表注释}、{(表, 列): 列注释}"""
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT TABLE_NAME AS t, TABLE_COMMENT AS c FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE()"
            )
            table_comments = {r["t"]: r["c"] for r in cur.fetchall()}
            cur.execute(
                "SELECT TABLE_NAME AS t, COLUMN_NAME AS c, COLUMN_COMMENT AS m "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
            )
            column_comments = {(r["t"], r["c"]): r["m"] for r in cur.fetchall()}
    return table_comments, column_comments


def _run(store: MySQLStorage, sql: str) -> None:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)


def main() -> int:
    spec = _parse_schema()
    print(f"从 {SCHEMA_FILE.name} 解析出 {len(spec)} 张表的注释")
    store = MySQLStorage()
    table_comments, column_comments = _fetch(store)

    n_table = n_col = n_missing = 0
    for table, info in spec.items():
        if table not in table_comments:
            print(f"  ! 库中无表 {table}（先跑对应的建表脚本），整表跳过")
            n_missing += 1
            continue

        if table_comments[table] != info["comment"]:
            _run(store, f"ALTER TABLE {table} COMMENT = '{info['comment']}'")
            print(f"  + {table}  表注释已写入")
            n_table += 1

        done = 0
        for col, (defn, comment) in info["columns"].items():
            if (table, col) not in column_comments:
                print(f"  ! {table}.{col} 库中不存在（先跑补列脚本），跳过")
                continue
            if column_comments[(table, col)] == comment:
                continue
            modify_def = _PRIMARY_KEY_RE.sub("", defn)  # MODIFY 不接受内联 PRIMARY KEY
            _run(store, f"ALTER TABLE {table} MODIFY COLUMN {modify_def}")
            done += 1
        if done:
            print(f"  + {table}  {done} 个字段注释已写入")
            n_col += done

    print()
    print(
        f"完成：表注释写入 {n_table} 张、字段注释写入 {n_col} 个"
        + (f"；⚠️ 缺表 {n_missing} 张（见上）" if n_missing else "")
        + "。重跑一次可确认全部「无变化」。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
