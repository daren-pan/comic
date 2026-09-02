"""第二个演示源站：验证跨站去重合并与「源站可插拔」。

复用 DemoSourceAdapter 的解析逻辑（XPath 相同），仅替换：
- source_name: demo_source_b（写入 comic.source 溯源）
- LIST_FILE / DETAIL_PREFIX: 本源的 fixture 文件

关键演示点（架构方案 §2.3 跨站合并）：
源 B 收录了与源 A 同一部作品「海贼王（重置版）」，作者一致 →
build_fingerprint 命中 → 调度层判定为同一部漫画，不重复入库，
仅统计为 updated；源 B 独有的「鬼灭之刃」正常新增。
"""

from __future__ import annotations

from .demo_source import DemoSourceAdapter
from .registry import register


@register("demo_source_b")
class DemoSourceBAdapter(DemoSourceAdapter):
    source_name = "demo_source_b"
    LIST_FILE = "demo_list_b.html"
    DETAIL_PREFIX = "demo_detail_b_"
