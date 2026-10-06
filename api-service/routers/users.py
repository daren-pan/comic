"""用户中心接口：收藏（需登录）与阅读历史（**登录走账号，游客走匿名 id**）。

| 资源 | 归属 | 鉴权 |
|---|---|---|
| 收藏 | **一定**是登录账号（`user.id`，忽略路径里的 uid） | `get_current_user` → 未登录 401 |
| 阅读历史 | 登录了 = 账号 id；没登录 = 路径里的匿名 UUID | `get_optional_user` → 游客照常可用 |

⚠️ 历史的归属规则是 2026-09-21 改的：此前**无条件信任 URL 里的 uid**，于是"知道别人的
匿名 UUID"就等于"能读写删那个人的全部阅读历史"（IDOR）。而那个 UUID 是前端存在
localStorage 里、**明文拼在 URL 路径**上的，会随访问日志 / 浏览器历史 / Referer 外泄。
改法与收藏同一口径后，登录用户的历史不再能被他人用 ID 冒用。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from core.db import db, users
from core.responses import ok
from core.security import get_current_user, get_optional_user
from schemas import HistoryPut
from serializers import to_comic
from services.tags import attach_tags

router = APIRouter(tags=["users"])

# 路径里的用户标识（登录账号的数字 id 转字符串 / 游客的匿名 UUID）。
# 约束 = 「有界 + 无控制字符」，与 `favorite.user_id` / `history.user_id` 的 `VARCHAR(64)` 对齐。
# ⚠️ 没有这道约束时，超长 uid 会一路走到 INSERT 才撞列宽，返回 **500**（实测可复现）。
UserId = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")]


def _history_owner(user_id: str, user: dict | None) -> str:
    """阅读历史的归属：**登录了用账号 id，没登录才用路径里的匿名 id**（见模块头）。

    代价（已知并刻意接受）：登录**之前**攒下的匿名历史不会并入账号 —— 它属于那台浏览器的
    UUID。反过来做（把匿名历史迁移到账号）等于让任何登录用户凭一个 UUID 就能把别人的历史
    认领走，风险更大。README 里「跨浏览器续读」的语义本来也只有账号归属才成立。
    """
    return str(user["id"]) if user else user_id


# ---------------- 收藏（登录态；user_id 参数保留用于路由兼容，实际以 token 身份为准） ----------------

@router.get("/api/users/{user_id}/favorites")
def favorites(user_id: UserId, user: dict = Depends(get_current_user)):
    user_id = str(user["id"])
    ids = users.list_favorites(user_id)        # 已按收藏时间倒序
    # 一次取回全部作品行（投影同 get_comic）；逐条 get_comic 会让接口随收藏数线性变慢
    mapping = db.get_comics_by_ids(ids)
    rows = [mapping[i] for i in ids if i in mapping]   # 按收藏顺序；作品已不存在则跳过
    attach_tags(rows)                     # 批量注入 tags（见 services.tags.attach_tags）
    return ok([to_comic(r) for r in rows])


@router.get("/api/users/{user_id}/favorites/{comic_id}")
def favorite_state(user_id: UserId, comic_id: int, user: dict = Depends(get_current_user)):
    return ok({"favorited": users.is_favorite(str(user["id"]), comic_id)})


@router.put("/api/users/{user_id}/favorites/{comic_id}")
def add_favorite(user_id: UserId, comic_id: int, user: dict = Depends(get_current_user)):
    if not db.get_comic(comic_id):
        raise HTTPException(status_code=404, detail="comic not found")
    users.set_favorite(str(user["id"]), comic_id, True)
    return ok({"favorited": True})


@router.delete("/api/users/{user_id}/favorites/{comic_id}")
def remove_favorite(user_id: UserId, comic_id: int, user: dict = Depends(get_current_user)):
    users.set_favorite(str(user["id"]), comic_id, False)
    return ok({"favorited": False})


# ---------------- 阅读历史（登录走账号 / 游客走匿名 id，两者都不要求登录） ----------------

@router.get("/api/users/{user_id}/history")
def history(user_id: UserId, user: dict | None = Depends(get_optional_user)):
    # 历史记录本身已按阅读时间倒序；这里补上作品行 —— 一次批量取回，避免逐条 get_comic
    entries = users.list_history(_history_owner(user_id, user))
    mapping = db.get_comics_by_ids([r["comic_id"] for r in entries])
    entries = [r for r in entries if r["comic_id"] in mapping]   # 作品已不存在则跳过
    attach_tags([mapping[r["comic_id"]] for r in entries])       # 批量注入 tags
    return ok([
        {
            "comicId": r["comic_id"],
            "chapterId": r["chapter_id"],
            "pageNo": r["page_no"],
            "readAt": r["read_at"],
            "chapterTitle": r["chapter_title"],
            "comic": to_comic(mapping[r["comic_id"]]),
        }
        for r in entries
    ])


@router.put("/api/users/{user_id}/history")
def put_history(
    user_id: UserId, body: HistoryPut, user: dict | None = Depends(get_optional_user)
):
    """写入/更新阅读进度（翻页时自动调用，**每次都校验章节归属**）。

    ⚠️ 这条校验是 2026-09-21 补的：`history` 表对 `comic(id)` 有外键，但章节没有 ——
    传一个不存在的 comicId 会撞外键失败 → **500**；传"合法 comicId + 乱填 chapterId"
    则会静默写进一条脏进度（连不上章节，列表里标题是空的）。一次主键查询就能同时挡掉两种，
    返回 404 说明原因。
    """
    chapter = db.get_chapter(body.chapterId)
    if not chapter or int(chapter["comic_id"]) != body.comicId:
        raise HTTPException(status_code=404, detail="chapter not found")
    users.upsert_history(
        _history_owner(user_id, user), body.comicId, body.chapterId, body.pageNo
    )
    return ok(None, "history updated")


@router.delete("/api/users/{user_id}/history/{comic_id}")
def remove_history(
    user_id: UserId, comic_id: int, user: dict | None = Depends(get_optional_user)
):
    users.delete_history(_history_owner(user_id, user), comic_id)
    return ok(None, "history removed")
