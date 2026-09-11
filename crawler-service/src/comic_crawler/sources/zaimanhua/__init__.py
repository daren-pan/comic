"""再漫画（zaimanhua）—— H5 匿名可读通道，低频受控样本。

接口路径 / 请求头 / 限流 / 已知坑：见同目录 `README.md`。
样例 HTML：`fixtures/`（本目录）。
"""
from ...config import SourceConfig
from .adapter import ZaimanhuaAdapter

# 本源配置：频率/启停只改这里（原集中式 config.SOURCES 已就近化）
SOURCES = [
    SourceConfig(
        name="zaimanhua",
        priority="primary",  # 主源（2026-09-11 起）
        crawl_interval_seconds=3600,  # 学习用途受控源（H5 通道）：低频 + 受限样本
    ),
]

__all__ = ["ZaimanhuaAdapter", "SOURCES"]
