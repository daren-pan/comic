"""采集服务配置：**各源的声明式配置数据结构**。

对应架构方案 §4.4：生产环境由配置中心下发（源站列表、频率）。

⚠️ **各源的配置不在这里**：`SourceConfig` 只是数据结构；具体清单（名称/频率/启停）
就近维护在各自的源包内（`comic_crawler.sources.<源名>.__init__.py`），
聚合结果见 `comic_crawler.sources.SOURCES`。这样"新增一个源"不用回来改本文件。

⚠️ **限速参数也不在这里**：请求间隔 / 重试 / 超时的**默认值**定义在
`comic_crawler.http`（`DEFAULT_MIN_DELAY` 等模块常量 + `HttpFetcher` 构造参数），
避免"配置类看起来能调、实际没人读"的假配置。（两者同属 L0 通用内核，
而分层守卫要求 L0 模块之间零内部依赖，故不在此处持有 `HttpFetcher` 的默认值。）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceConfig:
    """单个源站的配置（与 source 表字段对应）。"""

    name: str
    base_url: str = ""
    priority: str = "primary"          # primary / backup
    crawl_interval_seconds: int = 900  # 增量轮询间隔（15 分钟）
    full_sync_cron: str = "0 3 * * *"  # 每日凌晨 3 点全量扫描
    enabled: bool = True
