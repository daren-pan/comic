"""评论区公开接口：列表 + 发表（都挂在作品下）。

| 动作 | 鉴权 | 说明 |
|---|---|---|
| `GET /api/comics/{id}/comments` | 无（任何人可看） | 评论是内容的一部分；**关闭时也照样返回**，只是 `enabled=false`、列表为空 —— 详情页要能区分「还没有人评论」与「评论区已关闭」，所以这里不能 404 |
| `POST /api/comics/{id}/comments` | **登录**（`get_current_user` → 未登录 401） | 关闭时 403（中文原因）；内容空白 422 |

**删除**不在本模块：那是管理动作，走 `routers/admin_comics`（`require_admin`）。

下架的作品整块不可达 —— 两个接口都先过 `services.catalog.visible_comic`（不存在 / 已下架
一律 404，口径见 `services/catalog.py`）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.db import comments
from core.pagination import normalize
from core.responses import ok
from core.security import get_current_user
from schemas import CommentBody
from serializers import to_comment
from services import comments as comments_svc
from services.catalog import visible_comic

router = APIRouter(tags=["comments"])


@router.get("/api/comics/{comic_id}/comments")
def list_comments(
    comic_id: int, page: int = 1, page_size: int = comments_svc.DEFAULT_PAGE_SIZE
):
    """评论列表（**最新在前**）+ 总数 + 该作品的评论开关状态。"""
    comic = visible_comic(comic_id)
    p, size = normalize(page, page_size, comments_svc.DEFAULT_PAGE_SIZE)
    rows, total = comments.list_comments(comic_id, p, size)
    return ok(
        {
            "items": [to_comment(r) for r in rows],
            "total": total,
            "page": p,          # 归一后的值必须回报，否则"传 0 却报 20"会让人误判分页
            "pageSize": size,
            "enabled": comments_svc.enabled_for(comic),
        }
    )


@router.post("/api/comics/{comic_id}/comments")
def add_comment(comic_id: int, body: CommentBody, user: dict = Depends(get_current_user)):
    """发表一条评论（需登录 + 评论区开启）。

    返回新评论的 id —— 前端据此**重拉第一页**（评论最新在前，新那条自然出现在顶部），
    比在本地拼一条更稳：作者名等字段的兜底规则只有后端这一份。
    """
    comic = visible_comic(comic_id)
    if not comments_svc.enabled_for(comic):
        raise HTTPException(status_code=403, detail="评论区已关闭")
    content = body.content.strip()
    if not content:
        # `min_length=1` 挡不住"全是空格"，strip 后再判一次
        raise HTTPException(status_code=422, detail="评论内容不能为空")
    new_id = comments.add_comment(comic_id, str(user["id"]), content)
    return ok({"id": new_id}, "comment added")
