"""adapter 包：源站适配器（CrawlerAdapter 接口 + 各源实现）。"""

from .base import CrawlerAdapter
from .registry import create_adapter, list_adapters, register

# 导入具体适配器以触发注册（保持 import 顺序稳定）
from . import demo_source, demo_source_b, guazi_source, pepper_source, zaimanhua_source  # noqa: E402,F401

__all__ = [
    "CrawlerAdapter",
    "create_adapter",
    "list_adapters",
    "register",
]
