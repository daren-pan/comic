"""作品标签的**批量**注入（列表接口用）。

标签存在 `comic_tag` 关联表里、不在 `comic` 行上，所以列表接口要单独取一次。
**批量**是硬要求：逐部 `db.get_comic_tags()` 时存储层每次调用都新建 MySQL 连接，
实测 `/api/comics` 12 条约 350ms、50 条约 1.29s，代价随条数线性增长；这里压成一条
`WHERE comic_id IN (...)`，N 次往返 → 1 次（见 AGENTS.md「硬性约定·性能」）。

⚠️ 为什么住在这里而不是 `serializers.py`（2026-09-24 调整）：序列化层应当**只做形状
转换** —— 它一旦 import `core.db`，任何导入它的模块都会连带加载真实存储句柄，单测就
再也做不到"纯逻辑不连库"（`services/logs.py` 曾为此把日志行映射**刻意**留在自己模块内）。
查库属于业务动作，归 `services/`。
"""
from __future__ import annotations

from core.db import db


def attach_tags(rows: list[dict]) -> list[dict]:
    """给一批作品行**批量**注入 `tags`，返回同一列表（原地写入，便于链式调用）。

    空列表直接返回、不发查询。按 `row["id"]` 对齐；无标签的作品得到 `[]`。
    """
    if not rows:
        return rows
    mapping = db.get_comic_tags_bulk([int(r["id"]) for r in rows])
    for r in rows:
        r["tags"] = mapping.get(int(r["id"]), [])
    return rows
