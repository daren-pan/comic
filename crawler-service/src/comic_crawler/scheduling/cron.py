"""5 段 cron 表达式的解析与「下次/最近一次触发时刻」计算（**正则驱动**）。

标准 5 段：`分 时 日 月 周`

| 段 | 取值范围 |
|---|---|
| 分 | 0-59 |
| 时 | 0-23 |
| 日 | 1-31 |
| 月 | 1-12 |
| 周 | 0-7（**0 与 7 都是周日**） |

每段支持（用一条正则 `^(\\*|\\d+|\\d+-\\d+)(?:/(\\d+))?$` 解析单个列表项）：

| 写法 | 含义 |
|---|---|
| `*` | 该段任意值 |
| `*/N` | 从下界起每 N 个（如 `*/15` = 0,15,30,45） |
| `a` | 单值 |
| `a-b` | 闭区间 |
| `a-b/N` | 区间内每 N 个 |
| `a,b,c` | 列表（上述任意项组合，如 `0 9-18/2 * * 1,3,5`） |

⚠️ **日 与 周同时受限时按「或」匹配**（Vixie cron 的标准语义）：
`0 3 1 * 1` = 「每月 1 号**或**每周一」的 03:00，不是"且"。两者之一是 `*` 时就是普通的「且」。

## 为什么自己做而不引三方库（2026-10-06）

只用到 5 段里的一个子集，而三方 cron 库普遍捆着 DST／秒级／`@daily` 等这里用不到的语义；
本模块百来行、行为被单测钉死（`crawler-service/tests/test_cron.py`），比多一个依赖划算。
**不实现的**：秒级（第 6 段）、`@daily` 这类别名、`L`/`W`/`#` 等扩展（遇到就报错，不静默放行）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

#: 默认表达式：与旧的默认「每天 03:00」等价（改 cron 时保持默认行为不变）
DEFAULT_CRON = "0 3 * * *"

#: 单段里的单项：`*` / `a` / `a-b`，可选 `/N` 步长
_ITEM_RE = re.compile(r"^(\*|\d+|\d+-\d+)(?:/(\d+))?$")

#: 五段各自的取值范围与中文名（报错信息里带上，使用者才知道是哪段错）
_FIELDS: tuple[tuple[int, int, str], ...] = (
    (0, 59, "分"),
    (0, 23, "时"),
    (1, 31, "日"),
    (1, 12, "月"),
    (0, 7, "周"),
)

#: `next_after` 的搜索上界（天）：4 年足够覆盖 `0 0 29 2 *` 这类闰年表达式
MAX_SEARCH_DAYS = 366 * 4


def _parse_item(item: str, lo: int, hi: int, label: str) -> range:
    """解析一个列表项为 `range`（单值就是长度 1 的 range）。非法即抛 `ValueError`。"""
    m = _ITEM_RE.match(item)
    if not m:
        raise ValueError(f"{label} 段的 {item!r} 不是合法项（支持 * / N / a / a-b / a-b/N）")
    base, step_raw = m.group(1), m.group(2)
    if step_raw is not None and base != "*" and "-" not in base:
        raise ValueError(f"{label} 段的单值不能带步长：{item!r}")
    step = int(step_raw) if step_raw else 1
    if step < 1:
        raise ValueError(f"{label} 段的步长必须 ≥ 1：{item!r}")

    if base == "*":
        start, end = lo, hi
    elif "-" in base:
        a, b = base.split("-", 1)
        start, end = int(a), int(b)
    else:
        start = end = int(base)

    if start > end:
        raise ValueError(f"{label} 段的区间起止颠倒：{item!r}")
    if start < lo or end > hi:
        raise ValueError(f"{label} 段超出取值范围 {lo}-{hi}：{item!r}")
    return range(start, end + 1, step)


def _parse_field(text: str, lo: int, hi: int, label: str) -> set[int]:
    """解析一整段（逗号列表）为取值集合。"""
    out: set[int] = set()
    for raw in str(text).split(","):
        item = raw.strip()
        if not item:
            raise ValueError(f"{label} 段有空的列表项：{text!r}")
        out.update(_parse_item(item, lo, hi, label))
    if not out:
        raise ValueError(f"{label} 段没有可用取值：{text!r}")
    return out


@dataclass(frozen=True)
class CronSpec:
    """已解析的 cron 表达式（不可变，可安全缓存复用）。"""

    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    dom_restricted: bool
    dow_restricted: bool

    # ---- 判定 ----

    def matches_day(self, day: date) -> bool:
        """该日期是否命中（只看 日/月/周 三段）。"""
        if day.month not in self.months:
            return False
        dom_ok = day.day in self.days
        # Python 的 weekday(): 周一=0 … 周日=6；cron 的 0=周日
        dow = (day.weekday() + 1) % 7
        dow_ok = dow in self.weekdays
        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok     # 标准 cron：两者都受限 → 取"或"
        return dom_ok and dow_ok

    def matches(self, moment: datetime) -> bool:
        """该时刻（按**分钟**）是否命中整个表达式。"""
        return (
            moment.minute in self.minutes
            and moment.hour in self.hours
            and self.matches_day(moment.date())
        )

    # ---- 时刻计算 ----

    def next_after(self, now: datetime, max_days: int = MAX_SEARCH_DAYS) -> datetime | None:
        """`now` **之后**（严格大于）最近的一次命中时刻；4 年内无解返回 `None`。

        算法：先从"下一分钟"起按天找第一个命中的日期，再在该日期内取第一个不早于下界的
        时:分组合 —— 所以最坏也就几百次天循环，不做逐分钟扫描。
        """
        base = now.replace(second=0, microsecond=0)
        if base <= now:
            base += timedelta(minutes=1)
        slots = sorted((h, m) for h in self.hours for m in self.minutes)
        if not slots:
            return None
        for offset in range(max_days + 1):
            day = base.date() + timedelta(days=offset)
            if not self.matches_day(day):
                continue
            for hour, minute in slots:
                candidate = datetime.combine(day, time(hour=hour, minute=minute))
                if candidate >= base:
                    return candidate
        return None


def parse_cron(expression: str) -> CronSpec:
    """解析 5 段 cron 表达式；非法就抛 `ValueError`（消息里带段名与原因，可直接回给用户）。"""
    parts = str(expression or "").split()
    if len(parts) != 5:
        raise ValueError(f"cron 需要 5 段（分 时 日 月 周），当前 {len(parts)} 段：{expression!r}")

    parsed = [_parse_field(parts[i], lo, hi, label) for i, (lo, hi, label) in enumerate(_FIELDS)]
    minutes, hours, days, months, weekdays = parsed

    # 0 与 7 都是周日：统一收敛到 0，避免 `0 3 * * 7` 与 `0 3 * * 0` 判定不一致
    if 7 in weekdays:
        weekdays = (weekdays - {7}) | {0}

    return CronSpec(
        expression=" ".join(parts),
        minutes=frozenset(minutes),
        hours=frozenset(hours),
        days=frozenset(days),
        months=frozenset(months),
        weekdays=frozenset(weekdays),
        # 只有**字面 `*`** 才算"不受限"（`*/1` 视作受限，与常见实现一致）
        dom_restricted=parts[2].strip() != "*",
        dow_restricted=parts[4].strip() != "*",
    )
