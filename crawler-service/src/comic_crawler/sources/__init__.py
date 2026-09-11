"""源站层：**契约在外**（`base.py` / `registry.py`），**各源在里**（每个源一个子包）。

一个源子包固定 4 件套：

| 文件 | 作用 |
|---|---|
| `__init__.py` | 导出适配器类 + `SOURCES`（该源的频率/启停配置**就近维护**） |
| `adapter.py` | `CrawlerAdapter` 实现（解析列表 / 详情 / 章节图） |
| `README.md` | 接口路径 · 请求头 · 分页 · 限流 · 已知坑（改动同一提交内更新） |
| `fixtures/` | 该源的样例 HTML（离线测试用，可选） |

**新增一个源 = 复制一个子包 + 在下方 `_SOURCE_PACKAGES` 加一项**，
无需改动 `config.py` 或任何解析逻辑。契约变动只影响 `base.py`。

`guazi/` 目录暂无适配器（仅存样例 HTML 备用），故不参与聚合。
"""
from __future__ import annotations

from ..config import SourceConfig
from .base import CrawlerAdapter
from .registry import create_adapter, list_adapters, register

# 导入各源子包：既触发 @register 注册，也把各自的 SOURCES 配置带进来
from . import mangadex, weebcentral, zaimanhua  # noqa: E402,F401

# 轮询清单顺序 = 管理台展示顺序
_SOURCE_PACKAGES = (zaimanhua, mangadex, weebcentral)

SOURCES: list[SourceConfig] = [s for pkg in _SOURCE_PACKAGES for s in pkg.SOURCES]

__all__ = [
    "CrawlerAdapter",
    "create_adapter",
    "list_adapters",
    "register",
    "SOURCES",
]
