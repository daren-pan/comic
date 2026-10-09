"""一次性迁移：加「作品上下架」与「评论区」所需的列 / 表（**幂等**）。

对应 2026-10-09 的两个需求：

1. **作品上下架** —— `comic.listed`（1=上架 / 0=下架）。
   下架后前台列表 / 搜索 / 收藏 / 历史都不出现、**详情页直接 404**（用户决策），
   但**不删数据**、采集照旧更新，重新上架即恢复。
2. **评论区** ——
   - `comic.comment_enabled`：**单作品**评论开关；
   - `comment` 表：评论正文（**只收登录用户**，作者昵称读取时 JOIN `user` 取当前值）；
   - `app_setting` 表：全站级键值配置，目前只放 `comment_enabled`（**全站总开关**）。
   有效值 = 总开关 AND 单作品开关（见 `storage/mysql/comment_store.effective_enabled`）。

DDL 真源是 `comic-core/sql/mysql_schema.sql`（全新库由它建全），本脚本只服务**已有库**：
mysql 官方镜像只在数据卷为空时跑初始化脚本，**已有数据卷不会重跑** —— 老环境升级必须跑一次这个。

### 幂等与回滚

- 幂等：列/索引存在则跳过；两张表用 `CREATE TABLE IF NOT EXISTS`。
- 回滚（**会丢评论数据**，仅限本地/测试）：
      DROP TABLE IF EXISTS comment;
      DROP TABLE IF EXISTS app_setting;
      ALTER TABLE comic DROP INDEX idx_comic_listed_sync;
      ALTER TABLE comic DROP COLUMN listed, DROP COLUMN comment_enabled;

用法（在 comic 仓库根目录）：
    cd crawler-service && .venv/Scripts/python.exe ../tools/add_comic_listing_and_comment.py
连接参数走 `COMIC_MYSQL_*` 环境变量 → 仓库根 `deploy/.env` → 默认值（与其它运维脚本同一套）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "comic-core", "src"))

from comic_core.storage.mysql import MySQLStorage  # noqa: E402

#: `comic` 表本次要补的列：(列名, DDL 片段, 说明)
COMIC_COLUMNS: tuple[tuple[str, str, str], ...] = (
    (
        "listed",
        "TINYINT NOT NULL DEFAULT 1 AFTER addtime",
        "上架/下架（1=上架）",
    ),
    (
        "comment_enabled",
        "TINYINT NOT NULL DEFAULT 1 AFTER listed",
        "该作品评论开关（1=开）",
    ),
)

#: 要补的索引：(索引名, `ALTER TABLE comic ADD ...` 的片段)
COMIC_INDEX = "idx_comic_listed_sync"
COMIC_INDEX_DDL = f"ALTER TABLE comic ADD INDEX {COMIC_INDEX} (listed, sync_time)"

#: 要补的表：表名 → 建表 DDL（与 `comic-core/sql/mysql_schema.sql` 逐字一致）
NEW_TABLES: dict[str, str] = {
    "comment": """
CREATE TABLE IF NOT EXISTS comment (
    id INT AUTO_INCREMENT PRIMARY KEY,
    comic_id INT NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    content VARCHAR(500) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_comment_comic (comic_id, id),
    KEY idx_comment_user (user_id, created_at),
    CONSTRAINT fk_comment_comic FOREIGN KEY (comic_id) REFERENCES comic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
""",
    "app_setting": """
CREATE TABLE IF NOT EXISTS app_setting (
    k VARCHAR(64) NOT NULL PRIMARY KEY,
    v VARCHAR(255) NOT NULL DEFAULT '',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
""",
}


def _query(store: MySQLStorage, sql: str, params: tuple = ()) -> list[dict]:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def _exec(store: MySQLStorage, sql: str, params: tuple = ()) -> int:
    with store._conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def _columns(store: MySQLStorage, table: str) -> list[str]:
    rows = _query(
        store,
        """SELECT COLUMN_NAME AS c FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
           ORDER BY ORDINAL_POSITION""",
        (table,),
    )
    return [str(r["c"]) for r in rows]


def _indexes(store: MySQLStorage, table: str) -> list[str]:
    rows = _query(
        store,
        """SELECT DISTINCT INDEX_NAME AS n FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
        (table,),
    )
    return [str(r["n"]) for r in rows]


def _tables(store: MySQLStorage) -> list[str]:
    rows = _query(store, "SHOW TABLES")
    return [str(next(iter(r.values()))) for r in rows]


def main() -> int:
    store = MySQLStorage()

    tables = _tables(store)
    if "comic" not in tables:
        print("  ❌ 库里没有 comic 表 —— 先建库（scripts/init_mysql.sh）或用全新库部署")
        return 1

    # ---- 1. comic 补列 ----
    cols = _columns(store, "comic")
    for name, ddl, desc in COMIC_COLUMNS:
        if name in cols:
            print(f"  = comic.{name} 已存在，跳过（{desc}）")
            continue
        _exec(store, f"ALTER TABLE comic ADD COLUMN {name} {ddl}")
        print(f"  + 已加列 comic.{name}（{desc}）")

    # ---- 2. comic 补索引 ----
    if COMIC_INDEX in _indexes(store, "comic"):
        print(f"  = 索引 {COMIC_INDEX} 已存在，跳过")
    else:
        _exec(store, COMIC_INDEX_DDL)
        print(f"  + 已加索引 {COMIC_INDEX}(listed, sync_time)")

    # ---- 3. 补表 ----
    for name, ddl in NEW_TABLES.items():
        if name in tables:
            print(f"  = 表 {name} 已存在，跳过")
        else:
            _exec(store, ddl)
            print(f"  + 已建表 {name}")

    # ---- 复查 ----
    print("\n复查：")
    print(f"  comic 列：{', '.join(_columns(store, 'comic'))}")
    comic_idx = [i for i in _indexes(store, "comic") if i.startswith("idx_comic")]
    print(f"  comic 业务索引：{', '.join(comic_idx)}")
    all_tables = _tables(store)
    for name in NEW_TABLES:
        n = int(_query(store, f"SELECT COUNT(*) AS n FROM {name}")[0]["n"])
        print(f"  {name} 行数：{n}")
    total = int(_query(store, "SELECT COUNT(*) AS n FROM comic")[0]["n"])
    offline = int(_query(store, "SELECT COUNT(*) AS n FROM comic WHERE listed = 0")[0]["n"])
    print(f"  comic 共 {total} 部（下架 {offline} 部）")
    print(f"  库内共 {len(all_tables)} 张表")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
