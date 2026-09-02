# -*- coding: utf-8 -*-
"""MySQL comic 库 → SQLite 数据同步工具（开发/发布共用）。

用途：
    采集服务与 API 默认存储可切换（COMIC_DB_TYPE=mysql|sqlite）。本工具把
    MySQL（127.0.0.1:3307 comic 库，env 可覆盖）中的权威数据同步为项目内
    的 SQLite 数据文件（crawler-service/comic_demo.db、comic-deploy/comic_demo.db），
    保证「无 MySQL 环境」也能一键跑发布版（comic-deploy）或开发版 API。

    MySQL 版表结构与 SQLite 版保持一致（见 storage.py _SCHEMA / api-service
    用户表），主键 id 原样保留 —— 与 image_store 目录结构（comic/{cid}/{chid}/xx.jpg）
    严格对应，切勿使用新 id。

用法：
    python tools/sync_mysql_to_sqlite.py                 # 同步两个默认 demo db
    python tools/sync_mysql_to_sqlite.py --db x.db       # 指定目标文件（可多次）
    COMIC_MYSQL_PORT=3307 python tools/sync_mysql_to_sqlite.py
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import pymysql

DSN = {
    "host": os.environ.get("COMIC_MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("COMIC_MYSQL_PORT", "3307")),
    "user": os.environ.get("COMIC_MYSQL_USER", "root"),
    "password": os.environ.get("COMIC_MYSQL_PASSWORD", "password"),
    "database": os.environ.get("COMIC_MYSQL_DB", "comic"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

# 与 crawler-service storage.py _SCHEMA + api-service 用户表一致
DDL = [
    """CREATE TABLE comic (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        cover_url TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT '连载',
        category TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        fingerprint TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL,
        source_comic_id TEXT NOT NULL,
        latest_chapter_title TEXT NOT NULL DEFAULT '',
        sync_time TEXT NOT NULL,
        UNIQUE (source, source_comic_id)
    )""",
    """CREATE TABLE chapter (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comic_id INTEGER NOT NULL REFERENCES comic(id),
        chapter_no INTEGER NOT NULL,
        title TEXT NOT NULL,
        source_chapter_id TEXT NOT NULL,
        sync_time TEXT NOT NULL,
        UNIQUE (comic_id, chapter_no)
    )""",
    """CREATE TABLE page (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id INTEGER NOT NULL REFERENCES chapter(id),
        page_no INTEGER NOT NULL,
        source_url TEXT NOT NULL,
        oss_url TEXT NOT NULL DEFAULT '',
        cached_status TEXT NOT NULL DEFAULT '未转存'
    )""",
    """CREATE TABLE sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        mode TEXT NOT NULL,
        total_seen INTEGER NOT NULL DEFAULT 0,
        new_comics INTEGER NOT NULL DEFAULT 0,
        updated_comics INTEGER NOT NULL DEFAULT 0,
        new_chapters INTEGER NOT NULL DEFAULT 0,
        failed INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL
    )""",
    """CREATE TABLE favorite (
        user_id TEXT NOT NULL,
        comic_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (user_id, comic_id)
    )""",
    """CREATE TABLE history (
        user_id TEXT NOT NULL,
        comic_id INTEGER NOT NULL,
        chapter_id INTEGER NOT NULL,
        page_no INTEGER NOT NULL DEFAULT 1,
        read_at TEXT NOT NULL,
        PRIMARY KEY (user_id, comic_id)
    )""",
]

TABLES = ["comic", "chapter", "page", "sync_log", "favorite", "history"]
# 有自增主键 id 的表读取时按 id 排序，保证入库顺序稳定
ID_ORDERED = {"comic", "chapter", "page", "sync_log"}


def fetch_all(conn) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    with conn.cursor() as cur:
        for t in TABLES:
            order = " ORDER BY id" if t in ID_ORDERED else ""
            cur.execute(f"SELECT * FROM `{t}`{order}")
            rows = cur.fetchall()
            out[t] = [{k: v for k, v in r.items()} for r in rows]
            print(f"  MySQL  {t:<10} {len(rows)} 行")
    return out


def rebuild_sqlite(db_path: Path, data: dict[str, list[dict]]) -> None:
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        for t in TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {t}")
        for ddl in DDL:
            cur.execute(ddl)
        for t in TABLES:
            rows = data[t]
            if not rows:
                continue
            cols = list(rows[0].keys())
            placeholders = ", ".join("?" for _ in cols)
            col_sql = ", ".join(f'"{c}"' for c in cols)
            cur.executemany(
                f"INSERT INTO {t} ({col_sql}) VALUES ({placeholders})",
                [[r.get(c) for c in cols] for r in rows],
            )
            print(f"  SQLite {t:<10} 写入 {len(rows)} 行")
        # 保持自增序列不落后于显式插入的 max(id)
        for t in ID_ORDERED:
            row = cur.execute(f"SELECT MAX(id) FROM {t}").fetchone()
            if row and row[0] is not None:
                cur.execute(
                    "UPDATE sqlite_sequence SET seq=? WHERE name=?",
                    (row[0], t),
                )
        con.commit()
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="MySQL comic 库 → SQLite 同步")
    ap.add_argument("--db", action="append", help="目标 SQLite 文件（可多次指定）")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    targets = (
        [Path(p) for p in args.db]
        if args.db
        else [root / "crawler-service" / "comic_demo.db",
              root / "comic-deploy" / "comic_demo.db"]
    )

    print(f"连接 MySQL {DSN['host']}:{DSN['port']}/{DSN['database']} ...")
    conn = pymysql.connect(**DSN)
    try:
        data = fetch_all(conn)
    finally:
        conn.close()

    for db in targets:
        print(f"重建 SQLite: {db}")
        rebuild_sqlite(db, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
