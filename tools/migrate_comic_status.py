"""一次性迁移：把 `comic.status` 的历史写法归一成规范值。

## 背景（2026-10-13）

四个源的适配器此前**各写一套**状态映射，输出用词互不相同：

| 源 | 输出 |
|---|---|
| `weebcentral` / `mangadex` | 连载 / 完结 / 休载 / 已取消 |
| `copymanga` | 连载 / 完结 |
| `zaimanhua` | 透传源站文本（连载中） |
| `ComicBrief` 默认值 | 连载 |

于是同一个概念在库里存成三种写法。**迁移前实测分布**：

    连载 29 / 连载中 23 / 完结 2

而 api-service 的接口层当时用白名单静默兜底、只认「连载中 / 已完结」——
**那 2 部已完结的作品一直被强制显示成"连载中"**（54 行里 31 行不在白名单内，占 57%）。

## 本次做什么

把历史数据对齐到 `comic_core.status` 的规范值：

    连载 → 连载中        完结 → 已完结

归一函数已统一到 `comic_core.status.normalize_status`（各源适配器 + 接口层都调它），
迁移完成后它对库里的值是**幂等**的。

## 用法（在 comic 仓库根目录）

    cd crawler-service && PYTHONPATH=src python ../tools/migrate_comic_status.py            # 只看报告（不改库）
    cd crawler-service && PYTHONPATH=src python ../tools/migrate_comic_status.py --apply    # 真改

连接参数由 `COMIC_MYSQL_*` 环境变量控制（见 comic_core.storage.mysql._pool）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "crawler-service", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "comic-core", "src"))

from comic_core.status import ALL_STATUSES, normalize_status  # noqa: E402
from comic_core.storage.mysql import MySQLStorage  # noqa: E402


def _distribution(cur) -> dict[str, int]:
    cur.execute("SELECT status, COUNT(*) AS n FROM comic GROUP BY status ORDER BY n DESC")
    return {str(r["status"]): int(r["n"]) for r in cur.fetchall()}


def migrate(db, apply: bool = False) -> int:
    """执行迁移；返回被更新的行数（dry-run 时恒为 0）。"""
    with db._conn() as conn:
        with conn.cursor() as cur:
            before = _distribution(cur)

    print("迁移前分布：")
    for raw, n in before.items():
        mark = "" if raw in ALL_STATUSES else "   ← 不在规范值内"
        print("    %-8s %3d 行%s" % (raw, n, mark))

    plan = [
        (raw, normalize_status(raw), n)
        for raw, n in before.items()
        if normalize_status(raw) != raw
    ]
    if not plan:
        print("\n无需迁移：所有状态值已是规范值 %s" % (ALL_STATUSES,))
        return 0

    print("\n迁移计划：")
    for raw, target, n in plan:
        print("    %s → %s    （%d 行）" % (raw, target, n))

    if not apply:
        print("\n[dry-run] 未改动数据库。确认真改请加 --apply")
        return 0

    changed = 0
    with db._conn() as conn:
        with conn.cursor() as cur:
            for raw, target, _n in plan:
                cur.execute("UPDATE comic SET status = %s WHERE status = %s", (target, raw))
                changed += cur.rowcount

    with db._conn() as conn:
        with conn.cursor() as cur:
            after = _distribution(cur)

    print("\n已更新 %d 行" % changed)
    print("迁移后分布：")
    for raw, n in after.items():
        print("    %-8s %3d 行" % (raw, n))
    leftover = [s for s in after if s not in ALL_STATUSES]
    if leftover:
        print("\n⚠️ 仍有非规范值残留（源站引入的新写法，未猜着改）：%s" % leftover)
    return changed


if __name__ == "__main__":
    migrate(MySQLStorage(), apply="--apply" in sys.argv)
