"""一次性迁移：补齐两个缺失索引，让大数据量下的查 / 改走最优路径。

背景（对应 `AGENTS.md`「硬性约定·性能」：面向大数据量访问设计，增删查改都要走最优路径）：
2026-09-14 核对现状时发现两处「无索引全表扫 / filesort」：

1. **`comic.sync_time` 无索引** —— 而它是列表默认排序键
   （`list_comics` 默认 `sort=updated` → `ORDER BY c.sync_time DESC`），
   量大时每次列表页都要 filesort；
2. **`page.cached_status` 无索引** —— 而转存 / 失效巡检每次都要按
   `cached_status = '未转存'` 筛（`list_uncached_pages`），而 `page` 是全库最大的表，
   等于每轮转存都全表扫。索引带上 `id` 是为了配合键集分页（`after_id=p.id`）。

DDL 已同步进 `crawler-service/sql/mysql_schema.sql`（新库建表即带上）；
本脚本用于**已有库**补齐。两个索引都**只读加速、不动任何数据**。

**幂等**：可重复运行 —— 已存在的索引会跳过。
**可回滚**（索引与数据无关，随时可删）：
    ALTER TABLE comic DROP INDEX idx_comic_sync;
    ALTER TABLE page  DROP INDEX idx_page_cached;

用法（在 comic 仓库根目录）：
    cd crawler-service && PYTHONPATH=src python ../tools/add_perf_indexes.py
连接参数用环境变量 `COMIC_MYSQL_*` 覆盖（默认兜底读仓库根 `deploy/.env`：宿主 `127.0.0.1:3309`）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler-service", "src"))

from comic_crawler.storage.mysql import MySQLStorage  # noqa: E402

# (表, 索引名, 列定义, 为什么需要)
INDEXES: list[tuple[str, str, str, str]] = [
    (
        "comic",
        "idx_comic_sync",
        "(sync_time)",
        "列表默认排序键（ORDER BY sync_time DESC），否则每次列表页 filesort",
    ),
    (
        "page",
        "idx_page_cached",
        "(cached_status, id)",
        "转存 / 巡检按 cached_status='未转存' 筛（表最大），否则全表扫",
    ),
]


def _index_names(store: MySQLStorage, table: str) -> set[str]:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT INDEX_NAME AS n FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
                (table,),
            )
            return {str(r["n"]) for r in cur.fetchall()}


def _row_count(store: MySQLStorage, table: str) -> int:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM {table}")  # noqa: S608（表名来自本地常量）
            return int(cur.fetchone()["c"])


def main() -> int:
    store = MySQLStorage()
    print("补齐索引：")
    created = 0
    for table, name, cols, why in INDEXES:
        if name in _index_names(store, table):
            print(f"  = {table}.{name} 已存在，跳过")
            continue
        rows = _row_count(store, table)
        with store._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"ALTER TABLE {table} ADD INDEX {name} {cols}")  # noqa: S608
        created += 1
        print(f"  + {table}.{name} {cols}（表内 {rows} 行）—— {why}")

    print(f"\n新建 {created} 个索引。复查：")
    for table, name, cols, _ in INDEXES:
        mark = "OK" if name in _index_names(store, table) else "缺失"
        print(f"  [{mark}] {table}.{name} {cols}")
    return 0 if created >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
