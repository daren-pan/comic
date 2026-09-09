"""adapter 包：源站适配器（CrawlerAdapter 接口 + 各源实现）。"""

from .base import CrawlerAdapter
from .registry import create_adapter, list_adapters, register

# 导入具体适配器以触发注册（保持 import 顺序稳定）
from . import (  # noqa: E402,F401
    demo_source,
    demo_source_b,
    mangadex_source,
    pepper_source,
    weebcentral_source,
    zaimanhua_source,
)

__all__ = [
    "CrawlerAdapter",
    "create_adapter",
    "list_adapters",
    "register",
]
