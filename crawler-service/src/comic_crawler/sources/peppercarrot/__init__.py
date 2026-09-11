"""Pepper&Carrot —— CC-BY 4.0 开放授权源（英文，episode 即章节）。

接口路径 / 请求头 / 限流 / 已知坑：见同目录 `README.md`。
样例 HTML：`fixtures/`（本目录）。
"""
from ...config import SourceConfig
from .adapter import PepperCarrotAdapter

SOURCES = [
    SourceConfig(
        name="peppercarrot",
        priority="backup",
        crawl_interval_seconds=1800,  # 真实站点，放低频轮询
    ),
]

__all__ = ["PepperCarrotAdapter", "SOURCES"]
