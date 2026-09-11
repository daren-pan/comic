"""图片层：存储契约 + 本地实现。

- `store.py`    —— `ImageStore` 契约（扩展点：OSS/COS/MinIO 只需实现该 ABC）、
                   `LocalImageStore` 本地实现、`default_store_root()` 图库根唯一真源；
- `transfer.py` —— `lazy_transfer` 懒转存、`ensure_cover_local` 封面落盘。

⚠️ **本文件刻意只导出 `store`，不 `import .transfer`**：`transfer` 依赖 `httpx`，
若在此急切导入，"只想用 `store`"的调用方（如 API 读端仅需 `default_store_root()`）
也会被连带要求 httpx —— 一旦 httpx 缺失，`import comic_crawler.images.store` 直接失败，
读端就可能静默退到错误目录（见 api-service 图库根事故）。

需要转存能力请显式导入：`from comic_crawler.images.transfer import lazy_transfer`。
"""
from .store import ImageStore, LocalImageStore, default_store_root

__all__ = [
    "ImageStore",
    "LocalImageStore",
    "default_store_root",
]
