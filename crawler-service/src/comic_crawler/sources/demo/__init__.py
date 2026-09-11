"""演示源（demo）—— 离线可跑的样例适配器，含两个变体。

- `adapter.py`   —— `DemoSourceAdapter`（源名 `demo_source`）：解析 `fixtures/*.html`
- `adapter_b.py` —— `DemoSourceBAdapter`（源名 `demo_source_b`）：继承 A，只换 fixture 与
  前缀，用来验证「同一套解析逻辑复用到第二个源」与跨源指纹合并

只有 `demo_source` 进了轮询清单（`SOURCES`）；`demo_source_b` 用于测试与手动触发。
样例 HTML 见同目录 `fixtures/`。
"""
from ...config import SourceConfig
from .adapter import DemoSourceAdapter
from .adapter_b import DemoSourceBAdapter

SOURCES = [
    SourceConfig(
        name="demo_source",
        priority="primary",
        crawl_interval_seconds=900,
    ),
]

__all__ = ["DemoSourceAdapter", "DemoSourceBAdapter", "SOURCES"]
