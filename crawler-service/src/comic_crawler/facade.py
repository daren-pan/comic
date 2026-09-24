"""对外契约面 —— api-service 依赖 `comic_crawler` 的**唯一入口**。

## 为什么有这个模块

api-service 此前**穿透到采集包的内部实现**：24 条 import 散在 10 个文件里，
直接摸到 `storage.mysql.comic_store` / `images.transfer` / `scheduling.sync`
这些实现细节。后果是「采集侧动内部结构」会直接波及接口侧 —— 换存储实现、
拆 `comic_store`、重排 `scheduling` 的模块，都得连带改 api。

本模块把 api 需要的能力**收成一份显式清单**（`__all__`）：

- **api 只允许 `from comic_crawler.facade import ...`**，不得 import 任何子模块
  （由 `api-service/tests/test_crawler_boundary.py` 断言守卫）；
- 采集侧内部随便重构 —— 换模块名、拆文件、改类名 —— 只要本模块的
  **符号名与签名不变**，api 零改动；
- 因此**改这里的签名 = 破坏性变更**，要当成对外接口对待。

## 与 `cli.py` 的关系

两者都是「允许依赖任意层」的入口（见 `tests/test_layering.py` 的 `_EXEMPT`）：
`cli.py` 面向运维命令行，本模块面向 api-service。

## 导出取舍

`images.transfer` 在本模块**急切导入**（连带 httpx），而 `images/__init__.py`
刻意不导入它。这是有意的：api-service 必装 httpx（FastAPI 生态 + 采集层依赖），
急切导入换来 `__all__` 静态可读与 IDE 补全；若将来出现「只想要 store 却不想装
httpx」的调用方，再把 `fetch_page_bytes` 改成模块级 `__getattr__` 惰性解析。
"""
from __future__ import annotations

from . import logctx
from .images.store import LocalImageStore, default_store_root
from .images.transfer import fetch_page_bytes
from .models import ChapterBrief, ComicDetail
from .paths import SOURCE_STATE_FILE
from .scheduling import (
    full_sync,
    heal_covers,
    import_comic,
    incremental_sync,
    inspect_sync,
)
from .sources import SOURCES, create_adapter
from .storage.mysql import MySQLLogStore, MySQLStorage, MySQLUserStore
from .storage.mysql.log_handler import install as install_log_handler

__all__ = [
    # L0 通用内核：领域模型 / 路径 / 日志上下文
    "logctx",
    "ChapterBrief",
    "ComicDetail",
    "SOURCE_STATE_FILE",
    # L2 源站 / 存储 / 图片
    "LocalImageStore",
    "default_store_root",
    "fetch_page_bytes",
    "SOURCES",
    "create_adapter",
    "MySQLLogStore",
    "MySQLStorage",
    "MySQLUserStore",
    "install_log_handler",
    # L3 编排：采集 / 巡检 / 按需导入
    "full_sync",
    "heal_covers",
    "import_comic",
    "incremental_sync",
    "inspect_sync",
]
