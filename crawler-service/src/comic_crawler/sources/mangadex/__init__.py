"""MangaDex —— v5 开放 API，默认关闭（AUP 非商用），仅手动触发增量。

接口路径 / 请求头 / 限流 / 已知坑：见同目录 `README.md`。
"""
from ...config import SourceConfig
from .adapter import MangaDexAdapter

SOURCES = [
    SourceConfig(
        name="mangadex",
        priority="backup",
        crawl_interval_seconds=3600,
        # AUP 非商用：默认不启用，仅手动 run / 管理台触发
        enabled=False,
    ),
]

__all__ = ["MangaDexAdapter", "SOURCES"]
