"""领域对象序列化：数据库蛇形字段 → 前端驼峰契约。

这一层**只做形状转换、不碰存储**（2026-09-24 起）：模块**不导入 `core.db`**，
因此任何 import 它的地方都能保持"纯逻辑、不连库"，单测不必再装存储桩。

唯一需要外部数据的字段是作品标签（在 `comic_tag` 关联表里、不在 `comic` 行上）——
由调用方**先注入 `row["tags"]`** 再交给 `to_comic`：

- **列表接口**：`services.tags.attach_tags(rows)`（一条 SQL 批量注入，避免逐条查询）；
- **单条接口**（详情）：`services.tags.attach_tags([row])`，代价可忽略。

`to_comic` 读不到 `tags` 时按空数组处理、**不回退查库** —— 忘了注入会表现为
"标签为空"，新增调用点时请照抄上面两种写法。

⚠️ 作品**来源是单个**（`source`，不是数组）：一行只属于一个源。判重只看
`(source, source_comic_id)` —— 同一部作品在别的源收过**是另一行**（跨源不合并，
见 `storage/mysql/comic_store.upsert_comic`），所以同名作品可能在列表里出现两次，
各自带自己的来源与章节进度。
"""
from __future__ import annotations


def to_comic(row: dict) -> dict:
    status = row["status"] if row["status"] in ("连载中", "已完结") else "连载中"
    tags = list(row.get("tags") or [])     # 由调用方注入（见模块头）；未注入即空数组
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
        "source": row.get("source") or "unknown",      # 该行来自哪个源（一行=一个源）
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
    """用户对外视图（隐藏 password_hash）。

    `role` 必须给前端：顶栏「管理」入口、`/#/admin*` 路由守卫都靠它判断
    （服务端另有 `require_admin` 兜底，前端这层只是体验）。
    """
    return {
        "id": user["id"],
        "username": user["username"],
        "nickname": user["nickname"] or user["username"],
        "role": user.get("role") or "user",
        "createdAt": user["created_at"],
    }


def to_admin_user(row) -> dict:
    """授权页的用户行（管理台视角：含角色与注册时间，不含任何凭据）。"""
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "nickname": row["nickname"] or row["username"],
        "role": row.get("role") or "user",
        "createdAt": row["created_at"],
    }

