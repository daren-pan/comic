"""领域对象序列化：数据库蛇形字段 → 前端驼峰契约。

这一层**只做形状转换**，不查库（`comic` 的标签需实时 JOIN，故 `to_comic` 会读一次
`db.get_comic_tags`，这是唯一例外）。
"""
from __future__ import annotations

from core.db import db


def to_comic(row: dict) -> dict:
    status = row["status"] if row["status"] in ("连载中", "已完结") else "连载中"
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
        "tags": db.get_comic_tags(row["id"]),
    }


def to_chapter(row: dict) -> dict:
    return {
        "id": row["id"],
        "comicId": row["comic_id"],
        "title": row["title"],
        "pageCount": row.get("page_count", 0),
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
