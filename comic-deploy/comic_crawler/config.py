"""采集服务配置。

对应架构方案 §4.4：生产环境由配置中心下发（源站列表、频率、限速参数），
此处提供本地默认值，供命令行演示使用。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceConfig:
    """源站配置（与 source 表字段对应）。"""

    name: str
    base_url: str = ""
    priority: str = "primary"          # primary / backup
    crawl_interval_seconds: int = 900  # 增量轮询间隔（15 分钟）
    full_sync_cron: str = "0 3 * * *"  # 每日凌晨 3 点全量扫描
    enabled: bool = True


@dataclass(frozen=True)
class CrawlConfig:
    """抓取限速参数（见架构方案 §2.4）。"""

    min_delay: float = 0.5     # 请求间隔下限（秒）
    max_delay: float = 2.0     # 请求间隔上限（秒）
    max_retries: int = 3       # 失败重试次数（指数退避）
    timeout: float = 10.0


# 已接入的源站列表（新增源站：在此注册 + 实现 adapter）
SOURCES: list[SourceConfig] = [
    SourceConfig(
        name="demo_source",
        priority="primary",
        crawl_interval_seconds=900,
    ),
    SourceConfig(
        name="peppercarrot",
        priority="backup",
        crawl_interval_seconds=1800,  # 真实站点，放低频轮询
    ),
    SourceConfig(
        name="guazi",
        priority="backup",
        crawl_interval_seconds=3600,  # 学习用途受控源：仅本地演示，低频 + 受限样本
    ),
    SourceConfig(
        name="zaimanhua",
        priority="backup",
        crawl_interval_seconds=3600,  # 学习用途受控源（H5 通道）：低频 + 受限样本
    ),
]
