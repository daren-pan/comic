"""作品**可见性**（上架 / 下架）的口径 —— 前台所有出口共用这一处。

下架口径（用户 2026-10-09 决策）：**列表 / 搜索 / 收藏 / 历史里都不出现，详情页直接 404**
（原话「无法搜索到该作品并进入详情页」）。所以：

- **列表类**：过滤在存储层 —— `list_comics()` / `get_comics_by_ids()` 的 `listed_only`
  **默认就是 True**（漏加过滤的后果是"下架作品照样出现在首页"，所以默认值取安全的那一侧）；
- **单条**：用本模块的 `visible_comic()` 取行，不存在与已下架**返回同一个 404** ——
  不告诉调用方"这部存在但被下架了"，免得下架状态被逐个 id 枚举出来。

⚠️ 这里抛 `HTTPException`（而不是返回 None 让路由自己抛）：这条规则要被
`routers/public` 与 `routers/comments` 两处共用，各写一遍必然会漂；`HTTPException`
本身只是个普通异常类，放在业务层不引入新的耦合。
"""
from __future__ import annotations

from fastapi import HTTPException

from core.db import db


def visible_comic(comic_id: int) -> dict:
    """取一部**已上架**的作品行；不存在 / 已下架 → 404（两种情况的响应完全一致）。"""
    row = db.get_comic(comic_id)
    if not row or not int(row.get("listed") or 0):
        raise HTTPException(status_code=404, detail="comic not found")
    return row


def is_visible(row: dict | None) -> bool:
    """行是否对前台可见（`listed = 1`）。给"已经拿到行"的调用方省一次查询。"""
    return bool(row) and bool(int(row.get("listed") or 0))
