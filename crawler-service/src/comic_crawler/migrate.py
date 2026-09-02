"""SQLite → MySQL 数据迁移工具。

用法：
    PYTHONPATH=src python -m comic_crawler.migrate  [--sqlite comic_demo.db]

从 SQLite 库读取 comic/chapter/page/sync_log 全部数据，写入 MySQL comic 库，
显式保留原 id（保证外键引用一致）。用户中心表（favorite/history）为空表，跳过。
"""
from __future__ import annotations

import argparse
import sqlite3

import pymysql
from pymysql.cursors import DictCursor

DSN = {
    "host": "127.0.0.1", "port": 3307, "user": "root",
    "password": "password", "database": "comic", "charset": "utf8mb4",
    "cursorclass": DictCursor, "autocommit": True,
}


def migrate(sqlite_path: str) -> None:
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    dst = pymysql.connect(**DSN)

    def copy(table: str) -> int:
        rows = src.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            return 0
        cols = list(rows[0].keys())
        ph = ",".join(["%s"] * len(cols))
        sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})"
        with dst.cursor() as cur:
            cur.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
        return len(rows)

    with dst.cursor() as cur:
        # 外键约束：先删子表再删父表（page→chapter→comic，favorite/history 引用 comic）
        for t in ("page", "chapter", "favorite", "history", "comic", "sync_log"):
            cur.execute(f"DELETE FROM {t}")

    for t in ("comic", "chapter", "page", "sync_log"):
        n = copy(t)
        print(f"  {t:>10}: {n} 行")

    src.close()
    dst.close()
    print("迁移完成。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default="comic_demo.db")
    args = ap.parse_args()
    migrate(args.sqlite)
