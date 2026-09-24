"""采集管理台的**后台任务体**（从 `routers/admin.py` 下沉）。

路由层只做「校验 → 派发 → 返回 taskId」，任务的**实际动作**（建存储句柄、调采集层
契约面、组装返回值）集中在这里。好处有二：

- 路由回到"薄壳"，改采集编排不再动 HTTP 层；
- 任务体是普通函数，**可单独调用与测试** —— 原先写在路由闭包里，只能起线程 + 轮询
  才碰得到（见 `services.tasks`）。

任务体都跑在 `services.tasks` 的后台线程里，异常由那里统一兜住并写进任务状态
（`message`），因此这里不额外做错误包装。
"""
from __future__ import annotations

import re
from dataclasses import asdict

from core import bootstrap  # noqa: F401  —— 先完成 sys.path 引导（使 comic_crawler 可导入）
from services import ondemand
from services.images import admin_image_store

#: 「名称 / ID」串的分隔符：逗号（中英）、顿号、分号（中英）、任意空白
_TOKEN_SPLIT = re.compile(r"[,，、;；\s]+")


def sync_job(source: str, mode: str, limit: int | None = None, since=None) -> dict:
    """采集一个源（`mode` = full 全量 / 其它为增量），返回统计 + 库内总量。"""
    from comic_crawler.facade import MySQLStorage, create_adapter, full_sync, incremental_sync

    storage = MySQLStorage()
    adapter = create_adapter(source)
    if mode == "full":
        stats = full_sync(adapter, storage, limit=limit, since=since)
    else:
        stats = incremental_sync(adapter, storage, limit=limit, since=since)
    return {"stats": asdict(stats), "summary": stats.summary(), "db": storage.stats()}


def parse_heal_keyword(keyword: str | None) -> tuple[list[int], list[str]]:
    """把「漫画名称或 ID」串拆成 `(comic_ids, title_like)`。

    纯数字 = 作品 ID，其余 = 名称子串（OR 命中，见 `Storage.find_comics`）；
    两者可混填、一次多部。返回 `([], [])` 表示没填出有效内容（由路由回 400）。
    """
    tokens = [t for t in _TOKEN_SPLIT.split(keyword or "") if t]
    comic_ids = [int(t) for t in tokens if t.isdigit()]
    title_like = [t for t in tokens if not t.isdigit()]
    return comic_ids, title_like


def heal_covers_job(source: str | None, comic_ids: list[int], title_like: list[str]) -> dict:
    """封面自愈（**按作品**）：`force=True` 跳过「文件在即健康」的早返回，强制回源重下覆盖。

    用于修复「封面文件在、但内容是错的」—— 普通自愈只看文件在不在，永远修不到错图。
    """
    from comic_crawler.facade import MySQLStorage, create_adapter, heal_covers

    storage = MySQLStorage()
    store = admin_image_store()
    return heal_covers(
        storage, store, adapter_provider=create_adapter,
        source=source, force=True,
        comic_ids=comic_ids or None, title_like=title_like or None,
    )


def inspect_job(source: str | None, since=None, until=None) -> dict:
    """失效巡检（**全库维护的唯一入口**）：转存未转存页 + 全表校验 + 全库封面自愈。

    三步：
    1. 窗口内未转存页 → 转存（`inspect_sync` 内部调 `lazy_transfer`）；
    2. 已转存页 → **全表**校验图库对象是否还在，缺失则恢复（按 id 键集分页，不会截断）；
    3. 封面自愈（`heal_covers`）—— 外链未落盘 / 本地文件缺失的封面按状态修复。

    ⚠️ 第 3 步原挂在已删除的「触发转存」上（2026-09-21 并到这里）：这样「巡检」一个按钮
    就覆盖了原来「转存 + 校验 + 封面自愈」的全部能力。**注意定时巡检（`scheduler` 里的
    `inspect_sync`）不含第 3 步**（那是本任务额外调的），避免每小时多打源站请求。
    只修「文件在但内容错」的封面用「按作品封面自愈」（`heal_covers_job`，`force=True`）。
    """
    from comic_crawler.facade import MySQLStorage, create_adapter, heal_covers, inspect_sync

    storage = MySQLStorage()
    store = admin_image_store()
    stats = inspect_sync(
        storage,
        image_store=store,
        adapter_provider=create_adapter,
        source=source,
        since=since,
        until=until,
    )
    # 第 3 步：全库封面自愈（透传 source —— 让自愈与本次巡检同源）
    cover = heal_covers(storage, store, adapter_provider=create_adapter, source=source)
    return {**stats, "coverHeal": cover, "pagesByStatus": storage.count_pages_by_status()}


def import_job(
    source: str,
    keyword: str | None = None,
    ref: str | None = None,
    source_comic_id: str | None = None,
    first_chapters: int | None = None,
) -> dict:
    """按需导入一部作品（关键词 / 作品链接 / 作品 ID），**不下载正文图**。"""
    from comic_crawler.facade import MySQLStorage

    storage = MySQLStorage()
    result = ondemand.import_one(
        source,
        keyword=keyword,
        ref=ref,
        source_comic_id=source_comic_id,
        first_chapters=first_chapters,
    )
    # 导入不登记页清单（1~2 秒完成）；页清单与页数都留到用户打开某一话时按需产生。
    return {**result, "pagesByStatus": storage.count_pages_by_status()}
