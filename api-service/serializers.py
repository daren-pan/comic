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
    """章节行 → 契约。

    `isNew`：是否属于「最近一批入库」（详情页右上角角标）—— 由调用方先注入
    `row["is_new"]`（`services.chapters.mark_latest_batch`），与本模块的 `tags`
    同一约定：**读不到就当 False，不回退查库**。
    """
    return {
        "id": row["id"],
        "comicId": row["comic_id"],
        "title": row["title"],
        "orderNo": row["chapter_no"],
        "createdAt": row["sync_time"],
        "isNew": bool(row.get("is_new")),
    }


def to_admin_comic(row: dict) -> dict:
    """管理台「作品管理」行的契约：在 `to_comic` 之上补三个**治理字段**。

    `listed`（上架状态）/ `commentEnabled`（单作品评论开关）/ `sourceComicId`（源站作品 ID）
    **只给管理台** —— 前台契约（`to_comic`）不带它们：普通用户拿不到、也不需要知道哪部被下架了。
    `sourceComicId`：「补全章节」按 `(源, 源作品 ID)` 复用「按需导入」`POST /api/admin/import`
    精确补章（源站搜索可能重名，只有 ID 是精确的）。

    `to_comic` 需要调用方先注入 `tags`；管理台列表不显示标签，所以这里**不注入**
    （省一条批量查询），`tags` 出来是空数组。
    """
    out = to_comic(row)
    out["listed"] = bool(int(row.get("listed") or 0))
    out["commentEnabled"] = bool(int(row.get("comment_enabled") or 0))
    out["sourceComicId"] = str(row.get("source_comic_id") or "")
    return out


def to_comment(row: dict) -> dict:
    """评论行 → 前端契约。

    作者名取 `nickname`、空则退回 `username`；**两者都空 = 账号已被删**
    （读取侧是 `LEFT JOIN user`，没命中就是 NULL）→ 显示「已注销用户」。
    这句兜底**刻意写在后端**：三端（网页 / H5 / 小程序）拿到的是同一份文案，不必各写一遍。

    `createdAt` 给原始 DATETIME（与 `to_chapter.createdAt` 同一处理），前端自己格式化。
    """
    name = (row.get("nickname") or "").strip() or (row.get("username") or "").strip()
    return {
        "id": int(row["id"]),
        "content": row["content"],
        "author": name or "已注销用户",
        "authorId": str(row.get("user_id") or ""),
        "createdAt": row["created_at"],
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

