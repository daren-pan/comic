"""评论区的业务口径：**两级开关** + 发表前的准入判定。

开关是两级（用户 2026-10-09 决策「全局 + 单作品覆盖」）：

| 开关 | 存在哪 | 谁改 |
|---|---|---|
| 全站总开关 | `app_setting` 表，键 `comment_enabled` | 管理台「作品管理」页顶部 |
| 单作品开关 | `comic.comment_enabled` 列 | 管理台「作品管理」页每行 |

**有效值 = 两者都开**（`enabled_for`）。语义等价于「总闸 + 分闸」：
总闸拉掉时，单作品打开也不放行；总闸开着时，每部作品各按自己的开关走。
默认都开（`app_setting` 里**不播种**该键 → 读默认 True；`comic.comment_enabled` 列默认 1），
所以"不加任何配置"就是全站可评论。

⚠️ 权限（谁能发）**不在这里** —— 那是 HTTP 层的事（登录 401 / 非管理员 403），
在 `routers/comments` 与 `routers/admin_comics` 上。
"""
from __future__ import annotations

from comic_core.storage.mysql import KEY_COMMENT_ENABLED

from core.db import settings

#: 每页条数（列表接口的默认值与上限都由 `core.pagination.normalize` 收口）
DEFAULT_PAGE_SIZE = 20


def global_enabled() -> bool:
    """全站总开关（键不存在取默认 **True** —— 全新库不必预先播种）。"""
    return settings.get_bool(KEY_COMMENT_ENABLED, True)


def set_global_enabled(enabled: bool) -> None:
    settings.set_bool(KEY_COMMENT_ENABLED, enabled)


def enabled_for(comic_row: dict) -> bool:
    """该作品当前**能否评论** = 全站总开关 **AND** 该作品的开关。

    传的是**已经取到的作品行**（调用方为判可见性本来就要取一次），所以这里零额外查询 ——
    只多一次 `app_setting` 的主键读。
    """
    return global_enabled() and bool(int(comic_row.get("comment_enabled") or 0))
