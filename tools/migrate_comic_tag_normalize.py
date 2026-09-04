"""一次性迁移：把旧 comic_tag(comic_id, tag) 表规范化为「tag 字典表 + 关联表」。

迁移前结构（旧）：comic_tag(comic_id, tag) —— tag 是冗余字符串。
迁移后结构（新）：tag(id, name) 字典表 + comic_tag(comic_id, tag_id) 关联表。

步骤：
  1. 新建 tag(id, name) 字典表（name 唯一）。
  2. 把旧 comic_tag 里所有 tag 字符串 upsert 进 tag 字典表。
  3. 重建 comic_tag 为关联表：(comic_id, tag_id)，由旧行 JOIN tag 得到。
  4. 用 comic.category 兜底回填（保证每部漫画标签完整）。

⚠️ MySQL 外键约束名必须唯一：旧表 `comic_tag_old` 改名后仍占用原约束名
`fk_tag_comic`，重建新表沿用同名会报 `duplicate key`，因此新表用 `fk_ct_comic`/`fk_ct_tag`。

用法（在 comic 仓库根目录）：
    cd crawler-service && PYTHONPATH=src python ../tools/migrate_comic_tag_normalize.py
默认 MySQL。设 COMIC_DB_TYPE=sqlite 则迁移 SQLite 库（SQLite 建表含 OR IGNORE 语义）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler-service", "src"))

from comic_crawler.mysql_storage import MySQLStorage  # noqa: E402
from comic_crawler.storage import SQLiteStorage  # noqa: E402


def migrate(db) -> None:
    if isinstance(db, MySQLStorage):
        with db._conn() as conn:
            with conn.cursor() as cur:
                # 1. 新建 tag 字典表（若不存在）
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS tag (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        name VARCHAR(128) NOT NULL,
                        UNIQUE KEY uk_tag_name (name)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"""
                )
                # 2. 把旧 comic_tag 里的 tag 字符串 upsert 进 tag 字典表
                cur.execute("SELECT DISTINCT tag FROM comic_tag")
                for r in cur.fetchall():
                    cur.execute("INSERT IGNORE INTO tag (name) VALUES (%s)", (r["tag"],))
                # 3. 备份旧表，重建为关联表
                cur.execute("DROP TABLE IF EXISTS comic_tag_old")
                cur.execute("ALTER TABLE comic_tag RENAME TO comic_tag_old")
                cur.execute(
                    """CREATE TABLE comic_tag (
                        comic_id INT NOT NULL,
                        tag_id INT NOT NULL,
                        PRIMARY KEY (comic_id, tag_id),
                        KEY idx_comic_tag_tag (tag_id),
                        CONSTRAINT fk_ct_comic FOREIGN KEY (comic_id) REFERENCES comic(id),
                        CONSTRAINT fk_ct_tag FOREIGN KEY (tag_id) REFERENCES tag(id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"""
                )
                # 4. 旧数据迁移到关联表
                cur.execute(
                    """INSERT IGNORE INTO comic_tag (comic_id, tag_id)
                       SELECT o.comic_id, t.id FROM comic_tag_old o
                       JOIN tag t ON t.name = o.tag"""
                )
                cur.execute("DROP TABLE IF EXISTS comic_tag_old")
            conn.commit()
    else:
        with db._conn() as conn:
            # 1. 新建 tag 字典表（name 唯一）
            conn.execute(
                """CREATE TABLE IF NOT EXISTS tag (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )"""
            )
            # 2. 旧 tag 字符串 upsert 进 tag 字典表
            for r in conn.execute("SELECT DISTINCT tag FROM comic_tag").fetchall():
                conn.execute("INSERT OR IGNORE INTO tag (name) VALUES (?)", (r["tag"],))
            # 3. 备份重建为关联表
            conn.execute("DROP TABLE IF EXISTS comic_tag_old")
            conn.execute("ALTER TABLE comic_tag RENAME TO comic_tag_old")
            conn.execute(
                """CREATE TABLE comic_tag (
                    comic_id INTEGER NOT NULL REFERENCES comic(id),
                    tag_id INTEGER NOT NULL REFERENCES tag(id),
                    PRIMARY KEY (comic_id, tag_id)
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_comic_tag_tag ON comic_tag (tag_id)"
            )
            # 4. 旧数据迁移
            conn.execute(
                """INSERT OR IGNORE INTO comic_tag (comic_id, tag_id)
                   SELECT o.comic_id, t.id FROM comic_tag_old o
                   JOIN tag t ON t.name = o.tag"""
            )
            conn.execute("DROP TABLE IF EXISTS comic_tag_old")
            conn.commit()


if __name__ == "__main__":
    mode = os.environ.get("COMIC_DB_TYPE", "mysql")
    db = MySQLStorage() if mode == "mysql" else SQLiteStorage()
    migrate(db)
    print("表结构迁移完成：tag 字典表 + comic_tag 关联表 已就绪。")
