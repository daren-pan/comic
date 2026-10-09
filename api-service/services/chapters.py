"""章节列表的派生标记：**最近一批入库**的章节（详情页右上角「NEW」角标用）。

章节是**批次式**入库的：采集与按需导入共用 `_upsert_detail`，而它只把「库内缺失的
章节」写给 `upsert_chapters`（一次写一批，见 crawler `scheduling/sync.py`）——
已存在的章节**不重写**。所以同一批的 `chapter.sync_time` 相同，且该列的含义就是
「这一章是什么时候新进来的」。

于是「本次同步更新过的章节」= `sync_time` **最大**的那一批：
- 与详情页 hero 区「更新 X月X日」（`comic.sync_time`）口径一致 —— 后者也是在来了
  新章节时前进（`sync._upsert_detail` 的 `touch_comic_sync_time`）；
- 不随下一轮同步消失（下一轮没有新章节时这一批不变），比「只看最近一轮 sync_log
  时间窗」更耐看。

⚠️ 纯计算、**不碰存储**：`get_chapters` 已经把行取回来了，这里只是在内存里比一遍
（`max()` 一次遍历），零额外查询。放 `services/` 而不是 `serializers.py` 的理由
同 `services/tags.py`：序列化层只做形状转换。
"""
from __future__ import annotations


def mark_latest_batch(rows: list[dict]) -> list[dict]:
    """给 `rows` 就地打 `is_new` 标记（`sync_time` 最大的那一批为 True）。

    空列表安全（返回原列表）。整本作品只有一批（首次收录，全部章节同批入库）时
    全部为 True —— 它们确实是"最近进来的"，按用户 2026-10-09 的决定不打折扣。
    """
    if not rows:
        return rows
    latest = max(r["sync_time"] for r in rows)
    for r in rows:
        r["is_new"] = r["sync_time"] == latest
    return rows
