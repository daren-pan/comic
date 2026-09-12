"""用户中心接口：收藏（需登录）与阅读历史（匿名 userId）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.db import db, users
from core.responses import ok
from core.security import get_current_user
from schemas import HistoryPut
from serializers import attach_tags, to_comic

router = APIRouter(tags=["users"])


# ---------------- 收藏（登录态；user_id 参数保留用于路由兼容，实际以 token 身份为准） ----------------

@router.get("/api/users/{user_id}/favorites")
def favorites(user_id: str, user: dict = Depends(get_current_user)):
    user_id = str(user["id"])
    rows = [db.get_comic(cid) for cid in users.list_favorites(user_id)]
    rows = [r for r in rows if r]
    attach_tags(rows)                     # 批量注入 tags（见 serializers.attach_tags）
    return ok([to_comic(r) for r in rows])


@router.get("/api/users/{user_id}/favorites/{comic_id}")
def favorite_state(user_id: str, comic_id: int, user: dict = Depends(get_current_user)):
    return ok({"favorited": users.is_favorite(str(user["id"]), comic_id)})


@router.put("/api/users/{user_id}/favorites/{comic_id}")
def add_favorite(user_id: str, comic_id: int, user: dict = Depends(get_current_user)):
    if not db.get_comic(comic_id):
        raise HTTPException(status_code=404, detail="comic not found")
    users.set_favorite(str(user["id"]), comic_id, True)
    return ok({"favorited": True})


@router.delete("/api/users/{user_id}/favorites/{comic_id}")
def remove_favorite(user_id: str, comic_id: int, user: dict = Depends(get_current_user)):
    users.set_favorite(str(user["id"]), comic_id, False)
    return ok({"favorited": False})


# ---------------- 阅读历史（匿名 userId） ----------------

@router.get("/api/users/{user_id}/history")
def history(user_id: str):
    entries: list[tuple[dict, dict]] = []
    comic_rows: list[dict] = []
    for r in users.list_history(user_id):
        comic = db.get_comic(r["comic_id"])
        if not comic:
            continue
        comic_rows.append(comic)
        entries.append((r, comic))
    attach_tags(comic_rows)               # 批量注入 tags（见 serializers.attach_tags）
    return ok([
        {
            "comicId": r["comic_id"],
            "chapterId": r["chapter_id"],
            "pageNo": r["page_no"],
            "readAt": r["read_at"],
            "chapterTitle": r["chapter_title"],
            "comic": to_comic(comic),
        }
        for r, comic in entries
    ])


@router.put("/api/users/{user_id}/history")
def put_history(user_id: str, body: HistoryPut):
    users.upsert_history(user_id, body.comicId, body.chapterId, body.pageNo)
    return ok(None, "history updated")


@router.delete("/api/users/{user_id}/history/{comic_id}")
def remove_history(user_id: str, comic_id: int):
    users.delete_history(user_id, comic_id)
    return ok(None, "history removed")
