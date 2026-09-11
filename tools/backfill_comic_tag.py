"""一次性迁移：把 comic.category 里的逗号分隔标签拆开，回填到「标签字典表 + 关联表」。

背景（规范化设计）：原来 comic_tag(comic_id, tag) 存的是冗余的 tag 字符串；现改为
tag(name) 字典表（每唯一标签一行） + comic_tag(comic_id, tag_id) 关联表（只存引用）。

本脚本按分隔符拆分 comic.category（如 "爱情, 美食" -> ['爱情','美食']），
先把标签 upsert 进 tag 字典表取回 id，再写入 comic_tag 关联表。
幂等：先清空该漫画旧的关联，再插入，避免重复。category 字段保持不变。

用法（在 comic 仓库根目录）：
    cd crawler-service && PYTHONPATH=src python ../tools/backfill_comic_tag.py
连接 MySQL（COMIC_MYSQL_* 环境变量控制连接参数）。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler-service", "src"))

from comic_crawler.storage.mysql import MySQLStorage  # noqa: E402


def split_tags(category: str) -> list[str]:
    tags = []
    for sep in (",", "，", "·", "、", "/", " "):
        if sep in category:
            tags = [s.strip() for s in category.split(sep) if s.strip()]
            break
    if not tags:
        tags = [category.strip()] if category.strip() else []
    seen: list[str] = []
    for t in tags:
        if t and t not in seen:
            seen.append(t)
    return seen


def backfill(db) -> int:
    total = 0
    with db._conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, category FROM comic")
            rows = cur.fetchall()
            for r in rows:
                cid = int(r["id"])
                tags = split_tags(r["category"] or "")
                if not tags:
                    continue
                cur.execute("DELETE FROM comic_tag WHERE comic_id = %s", (cid,))
                for t in tags:
                    # upsert 标签字典表：name 唯一，已存在则取回 id
                    cur.execute("INSERT IGNORE INTO tag (name) VALUES (%s)", (t,))
                    cur.execute("SELECT id FROM tag WHERE name = %s", (t,))
                    row = cur.fetchone()
                    if not row:
                        continue
                    cur.execute(
                        "INSERT IGNORE INTO comic_tag (comic_id, tag_id) VALUES (%s, %s)",
                        (cid, row["id"]),
                    )
                total += len(tags)
    return total


if __name__ == "__main__":
    db = MySQLStorage()
    n = backfill(db)
    print(f"回填完成：共写入 {n} 条标签关联。")
