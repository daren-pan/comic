"""管理台「作品管理」接口：**上下架** + **评论开关** + **评论管理**（`require_admin`）。

挂在 `require_admin` 下 —— 超管与普通管理员都能过；未登录 401 / 无管理员权限 403
（与 `routers/admin.py` 同一道门；授权页那道 `require_superadmin` 是另一回事）。

| 接口 | 作用 |
|---|---|
| `GET  /api/admin/comics` | 作品列表（**含下架的**，可搜关键词、分页） |
| `POST /api/admin/comics/{id}/listing` | 上架 / 下架 |
| `POST /api/admin/comics/{id}/comment` | 单作品评论开关 |
| `GET  /api/admin/settings/comment` · `PUT` | **全站**评论总开关 |
| `GET  /api/admin/comics/{id}/comments` | 某部作品的评论（管理视角，**不看前台可见性**） |
| `DELETE /api/admin/comments/{id}` | 删一条评论 |

为什么单独一个 router 而不是并进 `routers/admin.py`：那边是**采集运维**
（跑同步 / 巡检 / 看日志），这边是**内容治理**（作品可见性 / 评论区），
操作者看的是管理台里两个不同的页面（「采集管理」vs「作品管理」）。

⚠️ 这里的作品列表**故意不过滤下架作品**（`list_comics(listed_only=False)`）——
管理台正是要看到它们才能重新上架。前台口径见 `services/catalog.py`。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.db import comments, db
from core.pagination import normalize
from core.responses import ok
from core.security import require_admin
from schemas import CommentSwitchBody, ComicListingBody
from serializers import to_admin_comic, to_comment
from services import comments as comments_svc

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin-comics"], dependencies=[Depends(require_admin)])

#: 管理台作品列表的默认页大小（前台列表是 18，这边行式布局、可以多给些）
ADMIN_PAGE_SIZE = 20


@router.get("/api/admin/comics")
def admin_comics(
    keyword: str = "", page: int = 1, page_size: int = ADMIN_PAGE_SIZE
):
    """作品列表（**含已下架**），按最近更新倒序；`keyword` 匹配 标题/作者/分类/标签。"""
    p, size = normalize(page, page_size, ADMIN_PAGE_SIZE)
    rows, total = db.list_comics(
        keyword=keyword or None, page=p, page_size=size, listed_only=False
    )
    # ⚠️ 不注入 tags：管理台列表不显示标签，注入要多一次批量查询（见 to_admin_comic）
    return ok({"items": [to_admin_comic(r) for r in rows], "total": total, "page": p, "pageSize": size})


@router.post("/api/admin/comics/{comic_id}/listing")
def admin_comic_listing(comic_id: int, body: ComicListingBody, user: dict = Depends(require_admin)):
    """上架 / 下架一部作品。

    下架**只改 `comic.listed`**、不删任何数据；前台立刻不可见（列表 / 搜索 / 收藏 / 历史 /
    详情页全部），重新上架即恢复。会写一条结构化日志（谁、哪部、上/下架）备查。
    """
    if not db.set_comic_listed(comic_id, body.listed):
        raise HTTPException(status_code=404, detail="comic not found")
    logger.info(
        "作品%s comic_id=%s by=%s",
        "上架" if body.listed else "下架", comic_id, user.get("username") or user.get("id"),
        extra={"log_fields": {
            "event": "comic.listing", "comic_id": comic_id,
            "reason": "listed" if body.listed else "unlisted",
        }},
    )
    return ok({"id": comic_id, "listed": body.listed})


@router.post("/api/admin/comics/{comic_id}/comment")
def admin_comic_comment(
    comic_id: int, body: CommentSwitchBody, user: dict = Depends(require_admin)
):
    """开关**单作品**的评论区（全站总开关在 `PUT /api/admin/settings/comment`）。

    ⚠️ 单作品打开**不等于**能评论 —— 全站总开关关着时照样拦（两者是 AND，见 `services.comments`）。
    """
    if not db.set_comic_comment_enabled(comic_id, body.enabled):
        raise HTTPException(status_code=404, detail="comic not found")
    logger.info(
        "作品评论开关 comic_id=%s enabled=%s by=%s", comic_id, body.enabled, user.get("username"),
        extra={"log_fields": {
            "event": "comic.comment_switch", "comic_id": comic_id,
            "reason": "on" if body.enabled else "off",
        }},
    )
    return ok({"id": comic_id, "commentEnabled": body.enabled})


@router.get("/api/admin/settings/comment")
def admin_get_comment_setting():
    """读**全站评论总开关**。"""
    return ok({"enabled": comments_svc.global_enabled()})


@router.put("/api/admin/settings/comment")
def admin_put_comment_setting(body: CommentSwitchBody, user: dict = Depends(require_admin)):
    """写**全站评论总开关**：关掉 = 所有作品的评论区一起停（单作品开关保持原样，不覆盖）。"""
    comments_svc.set_global_enabled(body.enabled)
    logger.info(
        "全站评论总开关 enabled=%s by=%s", body.enabled, user.get("username"),
        extra={"log_fields": {
            "event": "comment.global_switch",
            "reason": "on" if body.enabled else "off",
        }},
    )
    return ok({"enabled": body.enabled})


@router.get("/api/admin/comics/{comic_id}/comments")
def admin_comic_comments(
    comic_id: int, page: int = 1, page_size: int = comments_svc.DEFAULT_PAGE_SIZE
):
    """某部作品的评论（管理视角）。

    与公开接口的区别：**不查前台可见性** —— 下架的作品在这里照样能看到并清理它的评论
    （那正是下架之后仍需要做的治理动作）。作品本身不存在时仍 404。
    """
    if not db.get_comic(comic_id):
        raise HTTPException(status_code=404, detail="comic not found")
    p, size = normalize(page, page_size, comments_svc.DEFAULT_PAGE_SIZE)
    rows, total = comments.list_comments(comic_id, p, size)
    return ok({"items": [to_comment(r) for r in rows], "total": total, "page": p, "pageSize": size})


@router.delete("/api/admin/comments/{comment_id}")
def admin_delete_comment(comment_id: int, user: dict = Depends(require_admin)):
    """删除一条评论（**物理删除**，不可恢复 —— 与"下架"刻意不同：评论是用户内容，
    删掉就该消失，没有"重新上架"的语义）。"""
    if not comments.delete_comment(comment_id):
        raise HTTPException(status_code=404, detail="comment not found")
    logger.info(
        "删除评论 comment_id=%s by=%s", comment_id, user.get("username"),
        extra={"log_fields": {"event": "comment.delete", "reason": f"comment_id={comment_id}"}},
    )
    return ok(None, "comment deleted")
