"""连载状态归一 —— 把各源五花八门的写法映射到项目规范值。

## 为什么要它（2026-10-13）

状态是跨源枚举，但四个源**各写一套转换**，输出用词互不相同：

| 源 | 实现 | 输出值域 |
|---|---|---|
| `weebcentral` | `STATUS_MAP`（英文→中文） | 连载 / 完结 / 休载 / 已取消 |
| `mangadex` | `_status_text`（同上，**独立一份**） | 连载 / 完结 / 休载 / 已取消 |
| `copymanga` | `_status_of`（按"完/結"字判定） | 连载 / 完结 |
| `zaimanhua` | 透传源站文本 | 连载中（源站原文） |
| `ComicBrief` 默认值 | —— | 连载 |

于是同一个概念在库里存成三种写法。生产库实测
`SELECT status, COUNT(*) FROM comic GROUP BY status` → `连载` 29 / `连载中` 23 / `完结` 2。

**更糟的是接口层曾用白名单静默兜底**：`api-service/serializers.py` 里
`status if status in ("连载中", "已完结") else "连载中"` —— 于是库中那 **2 部已完结的作品
被强制显示成"连载中"**（54 行里有 31 行的状态值不在白名单内，占 57%）。

本模块是**唯一**的归一入口：各源适配器与接口层都调它。

## 边界（刻意不做的事）

- **不压成两个值**：`休载`（暂停）与 `已取消`（下架）有各自的真实语义，
  压进"连载中/已完结"等于制造错误信息 —— 那正是上面那个白名单干过的坏事。
  规范值因此是**四个**。
- **未命中保留原文**（不吞、不猜）并记一条 warning：新增源引入新状态词时应当
  **显式登记**到 `_ALIASES`，而不是被静默改写。每个未知值只警告一次 ——
  这个函数在入库路径上会被高频调用，不能刷屏。
- **不做"读得到就覆盖"的判断**：拿不到状态（空值）时返回 `STATUS_ONGOING`，
  与 `ComicBrief.status` 的默认语义一致；调用方若要"保留旧值"，
  应自己判空后再调（见各源 adapter 的 `or comic.status` 写法）。
"""
from __future__ import annotations

import logging

_logger = logging.getLogger("comic.status")

#: 规范值 —— 接口契约、前端展示、库内存储统一用这四个
STATUS_ONGOING = "连载中"
STATUS_FINISHED = "已完结"
STATUS_HIATUS = "休载"
STATUS_CANCELLED = "已取消"

#: 全部规范值（前端类型与后续校验共用）
ALL_STATUSES: tuple[str, ...] = (STATUS_ONGOING, STATUS_FINISHED, STATUS_HIATUS, STATUS_CANCELLED)

#: 别名表：各源写法 → 规范值。查找前统一 `strip().lower()`，故键一律小写。
#: 含繁体（copymanga 是繁体站，实测 `連載中` / `已完結`）。
_ALIASES: dict[str, str] = {
    # 连载中
    "连载": STATUS_ONGOING,
    "連載": STATUS_ONGOING,
    "连载中": STATUS_ONGOING,
    "連載中": STATUS_ONGOING,
    "ongoing": STATUS_ONGOING,
    # 已完结
    "完结": STATUS_FINISHED,
    "完結": STATUS_FINISHED,
    "已完结": STATUS_FINISHED,
    "已完結": STATUS_FINISHED,
    "completed": STATUS_FINISHED,
    "complete": STATUS_FINISHED,
    # 休载
    "休载": STATUS_HIATUS,
    "休載": STATUS_HIATUS,
    "hiatus": STATUS_HIATUS,
    # 已取消
    "已取消": STATUS_CANCELLED,
    "cancelled": STATUS_CANCELLED,
    "canceled": STATUS_CANCELLED,
}

#: 已警告过的未知值（每个只报一次）
_warned: set[str] = set()


def normalize_status(raw: str | None) -> str:
    """源站状态 → 规范值。

    - **空值** → `STATUS_ONGOING`（拿不到就当在连载，与 `ComicBrief` 默认值一致）
    - **命中别名表** → 规范值
    - **未命中** → 原样返回 + 一条 warning（新增源请登记到 `_ALIASES`）
    """
    text = str(raw or "").strip()
    if not text:
        return STATUS_ONGOING
    hit = _ALIASES.get(text.lower())
    if hit:
        return hit
    if text not in _warned:
        _warned.add(text)
        _logger.warning(
            "未知的连载状态 %r —— 已原样保留；新增源请把写法登记到 comic_core.status._ALIASES",
            text,
        )
    return text


def is_known_status(raw: str | None) -> bool:
    """该状态是否已是规范值（迁移脚本与校验用）。"""
    return str(raw or "").strip() in ALL_STATUSES
