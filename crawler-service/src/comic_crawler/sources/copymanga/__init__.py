"""拷贝漫画（copy4000.com）—— 公开 JSON API 站点，学习用途受控源。

接口路径 / 请求头 / 分页 / 限流 / 已知坑：见同目录 `README.md`。
"""
from ...config import SourceConfig
from .adapter import CopymangaAdapter

SOURCES = [
    SourceConfig(
        name="copymanga",
        base_url="https://copy4000.com",
        priority="backup",
        # 学习用途受控源：低频 + 受限样本（列表单次只扫 MAX_PAGE=1 页 = 20 部）
        crawl_interval_seconds=3600,
    ),
]

__all__ = ["CopymangaAdapter", "SOURCES"]
