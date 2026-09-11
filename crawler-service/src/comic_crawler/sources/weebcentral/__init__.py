"""Weeb Central —— SSR + htmx 站点，学习用途受控源。

接口路径 / 请求头 / 限流 / 已知坑：见同目录 `README.md`。
"""
from ...config import SourceConfig
from .adapter import WeebCentralAdapter

SOURCES = [
    SourceConfig(
        name="weebcentral",
        priority="backup",
        crawl_interval_seconds=3600,  # 学习用途受控源：低频 + 受限样本
    ),
]

__all__ = ["WeebCentralAdapter", "SOURCES"]
