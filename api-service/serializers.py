"""领域对象序列化：数据库蛇形字段 → 前端驼峰契约。

这一层**只做形状转换**。唯一需要查库的地方是作品标签（走 `comic_tag` 关联表，
不在 `comic` 行里）：

- **列表接口**先调 `attach_tags(rows)` 批量注入 `row["tags"]`（一条 SQL 取全部），
  `to_comic` 直接读注入值 —— 否则逐部查询 + 逐次建连接会让接口随条数线性变慢；
- **单条接口**（详情）不注入，`to_comic` 回退到单次 `db.get_comic_tags()`（代价可忽略）。
"""
from __future__ import annotations

from core.db import db


def attach_tags(rows: list[dict]) -> list[dict]:
    """给一批作品行**批量**注入 `tags`，返回同一列表（原地写入，便于链式调用）。

    原实现对每部作品单独 `db.get_comic_tags()`，而存储层每次调用都新建 MySQL 连接：
    实测 `/api/comics` 12 条约 350ms、50 条约 1.29s，随条数线性增长。这里压成一条
    `WHERE comic_id IN (...)`，N 次往返 → 1 次。
    """
    if not rows:
        return rows
    mapping = db.get_comic_tags_bulk([int(r["id"]) for r in rows])
    for r in rows:
        r["tags"] = mapping.get(int(r["id"]), [])
    return rows


def to_comic(row: dict) -> dict:
    status = row["status"] if row["status"] in ("连载中", "已完结") else "连载中"
    tags = row.get("tags")
    if tags is None:                      # 未被 attach_tags 注入（单条接口）→ 回退单次查询
        tags = db.get_comic_tags(row["id"])
    return {
        "id": row["id"],
        "title": row["title"],
        "author": row["author"],
        "category": row["category"],
        "status": status,
        "description": row["description"],
        "cover": f"/api/covers/{row['id']}",
        "latestChapterTitle": row["latest_chapter_title"],
        "chapterCount": row.get("chapter_count", 0),
        "views": int(row.get("views") or 0),            # 累计浏览次数（原始计数）
        "favoriteCount": int(row.get("favorite_count") or 0),
        "heat": int(row["heat"]),                       # 热度分：1000 + 浏览 + 2×收藏
        "updatedAt": row["sync_time"],
        "sources": [s for s in (row.get("source") or "").split(",") if s] or ["unknown"],
        "tags": tags,
    }


def to_chapter(row: dict) -> dict:
    return {
        "id": row["id"],
        "comicId": row["comic_id"],
        "title": row["title"],
        "orderNo": row["chapter_no"],
        "createdAt": row["sync_time"],
    }


def to_page(row: dict, comic_id: int, chapter_id: int) -> dict:
    return {
        "pageNo": row["page_no"],
        "imageUrl": f"/api/images/{comic_id}/{chapter_id}/{row['page_no']}",
        "width": 720,
        "height": 1020,
    }


def user_out(user) -> dict:
    """用户对外视图（隐藏 password_hash）。"""
    return {
        "id": user["id"],
        "username": user["username"],
        "nickname": user["nickname"] or user["username"],
        "createdAt": user["created_at"],
    }
