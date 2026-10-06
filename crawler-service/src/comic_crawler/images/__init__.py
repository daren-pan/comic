"""图片层（采集侧）：转存 / 穿透取图 / 封面落盘。

⚠️ 图库的**读写契约与本地实现**（`ImageStore` / `LocalImageStore` / `default_store_root()`）
已下沉到公共内核 `comic_core.images.store` —— 采集端与接口端共用同一份实现、
同一个图库根。本包只保留**需要联网**的部分（依赖 `httpx`）。

⚠️ **本文件刻意不做任何 re-export**：`transfer` 依赖 `httpx`，若在此急切导入，
"只想用图库根"的调用方也会被连带要求 httpx。需要转存能力请显式导入：

    from comic_crawler.images.transfer import lazy_transfer
"""
