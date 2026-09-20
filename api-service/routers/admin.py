"""采集管理台接口（**仅超级管理员**）。

`router` 上挂了 `require_admin`（一处覆盖下面全部接口）：超管与**普通管理员都能过** —— **未登录 401 / 无管理员权限 403**。授权页在另一个 router，门槛更高（见 `routers/admin_users.py`）。
角色定义与判断见 `core/security.py`；给他人授权在 `routers/admin_users.py`（授权页）。

能力：列出数据源 / 开关采集 / 手动触发采集 / 手动触发懒转存（转存完成后自动封面自愈）
/ 手动触发**按作品**封面自愈（填漫画名称或 ID，强制回源重下覆盖）/ 手动触发失效巡检（转存 + 全表校验已转存对象、缺失则恢复）
/ 按需导入单部作品 / 查询运行日志（`log_record` 表，支持条件筛选与分页）。
采集 / 转存 / 巡检 / 导入耗时，统一交给 `services.tasks` 后台线程执行，返回 `taskId` 供前端轮询。
"""
from __future__ import annotations

import re
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from core.db import db  # noqa: F401  —— 先导入以完成 sys.path 引导
from core.responses import ok
from core.security import require_admin
from schemas import (
    AdminHealBody,
    AdminImportBody,
    AdminInspectBody,
    AdminSyncBody,
    AdminTransferBody,
)
from services import logs, ondemand, sources, tasks
from services.images import admin_image_store

from comic_crawler.storage.mysql import MySQLStorage

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/api/admin/sources")
def admin_sources():
    return ok(sources.meta())


@router.post("/api/admin/sources/{name}/toggle")
def admin_toggle_source(name: str):
    return ok({"name": name, "enabled": sources.toggle(name)})


@router.post("/api/admin/sync")
def admin_sync(body: AdminSyncBody):
    if not sources.is_enabled(body.source):
        raise HTTPException(status_code=400, detail=f"源 {body.source} 已关闭采集")
    from comic_crawler.sources import create_adapter
    from comic_crawler.scheduling import full_sync, incremental_sync

    def job():
        storage = MySQLStorage()
        adapter = create_adapter(body.source)
        if body.mode == "full":
            stats = full_sync(adapter, storage, limit=body.limit, since=body.since)
        else:
            stats = incremental_sync(adapter, storage, limit=body.limit, since=body.since)
        return {"stats": asdict(stats), "summary": stats.summary(), "db": storage.stats()}

    task_id = tasks.new_task_id("sync")
    tasks.run_task(task_id, "sync", job)
    return ok({"taskId": task_id})


@router.post("/api/admin/transfer")
def admin_transfer(body: AdminTransferBody):
    from comic_crawler.sources import create_adapter
    from comic_crawler.images.transfer import lazy_transfer
    from comic_crawler.scheduling import heal_covers

    def job():
        storage = MySQLStorage()
        store = admin_image_store()
        stats = lazy_transfer(
            storage, store,
            limit=body.limit, adapter_provider=create_adapter,
            since=body.since, until=body.until, source=body.source,
        )
        # 转存完成后自动封面自愈：修复外链未落盘 / 本地文件缺失的封面（无需单独按钮）。
        # 透传 body.source —— 让自愈与本次转存同源，避免"点了 A 源却改了 B 源封面"。
        cover = heal_covers(storage, store, adapter_provider=create_adapter, source=body.source)
        return {**stats, "coverHeal": cover, "pagesByStatus": storage.count_pages_by_status()}

    task_id = tasks.new_task_id("transfer")
    tasks.run_task(task_id, "transfer", job)
    return ok({"taskId": task_id})


@router.post("/api/admin/heal-covers")
def admin_heal_covers(body: AdminHealBody):
    """封面自愈（**按作品**）：填漫画名称或 ID（可多个），**强制**回源重抓封面并覆盖。

    用于修复「封面文件在、但内容是错的」—— 普通自愈只看文件在不在，永远修不到错图；
    这里 `force=True` 跳过「文件在即健康」的早返回，对命中作品重新下载覆盖。
    `keyword` **必填**：逗号 / 空格 / 换行分隔，每项是作品 ID 或名称（可混填，一次多部）。
    """
    from comic_crawler.sources import create_adapter
    from comic_crawler.scheduling import heal_covers

    # 拆成若干 token：纯数字 = 作品 ID，其余 = 名称子串（OR 命中，见 Storage.find_comics）
    tokens = [t for t in re.split(r"[,，、;；\s]+", body.keyword or "") if t]
    if not tokens:
        raise HTTPException(status_code=400, detail="请填写漫画名称或 ID（可多个，用逗号/空格/换行分隔）")
    comic_ids = [int(t) for t in tokens if t.isdigit()]
    title_like = [t for t in tokens if not t.isdigit()]

    def job():
        storage = MySQLStorage()
        store = admin_image_store()
        return heal_covers(
            storage, store, adapter_provider=create_adapter,
            source=body.source, force=True,
            comic_ids=comic_ids or None, title_like=title_like or None,
        )

    task_id = tasks.new_task_id("heal")
    tasks.run_task(task_id, "heal", job)
    return ok({"taskId": task_id})


@router.post("/api/admin/inspect")
def admin_inspect(body: AdminInspectBody):
    """失效巡检：把窗口内未转存页转存 + **全表**校验已转存对象是否还在（缺失则恢复）。

    与「转存」的区别：转存只做「未转存 → 转存」；巡检在此基础上再多做一步
    「已转存对象校验 + 丢失恢复」，因此能发现图库文件被误删/写错目录的情况。
    校验按 id 键集分页遍历全表，不会被固定条数截断。
    """
    from comic_crawler.sources import create_adapter
    from comic_crawler.scheduling import inspect_sync

    def job():
        storage = MySQLStorage()
        store = admin_image_store()
        stats = inspect_sync(
            storage,
            image_store=store,
            adapter_provider=create_adapter,
            source=body.source,
            since=body.since,
            until=body.until,
        )
        return {**stats, "pagesByStatus": storage.count_pages_by_status()}

    task_id = tasks.new_task_id("inspect")
    tasks.run_task(task_id, "inspect", job)
    return ok({"taskId": task_id})


@router.post("/api/admin/import")
def admin_import(body: AdminImportBody):
    """按需导入一部作品（后台线程执行，返回 `taskId` 供前端轮询）。

    与「采集」的区别：采集只能碰到源站「最近更新」榜上的作品；本接口按用户
    指定（关键词 / 作品链接 / 作品 ID）收录**榜单之外**的作品，并**全量收目录**
    （而不是只收最新 1 话）。导入**不下载正文图**：只写书目 + 全量章节 + 封面，
    正文图在用户阅读该话时按需取回并顺手落盘（见 services/ondemand）。

    失败原因（源站搜不到 / 付费锁定 / 源不支持搜索）会写进任务 message，
    前端消息中心直接显示，不需要额外错误通道。
    """

    def job():
        storage = MySQLStorage()
        result = ondemand.import_one(
            body.source,
            keyword=body.keyword,
            ref=body.ref,
            source_comic_id=body.source_comic_id,
            first_chapters=body.first_chapters,
        )
        # 导入不登记页清单（1~2 秒完成）；页清单与页数都留到用户打开某一话时按需产生。
        return {**result, "pagesByStatus": storage.count_pages_by_status()}

    task_id = tasks.new_task_id("import")
    tasks.run_task(task_id, "import", job)
    return ok({"taskId": task_id})


@router.get("/api/admin/tasks")
def admin_tasks():
    return ok(tasks.recent(30))


@router.get("/api/admin/tasks/{task_id}")
def admin_task(task_id: str):
    t = tasks.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="task not found")
    return ok(t)


@router.get("/api/admin/logs/options")
def admin_log_options():
    """日志查询页的筛选候选值（级别 / 事件类型）。"""
    return ok(logs.options())


@router.post("/api/admin/logs/purge")
def admin_logs_purge(days: int = 30):
    """删除 `days` 天前的日志（保留策略的手动入口；默认不做自动清理）。"""
    return ok({"deleted": logs.purge(days)})


@router.get("/api/admin/logs")
def admin_logs(
    level: str | None = None,
    source: str | None = None,
    event: str | None = None,
    task_id: str | None = None,
    comic_id: int | None = None,
    keyword: str | None = None,
    since: str | None = None,
    until: str | None = None,
    page: int = 1,
    page_size: int = 50,
    with_exc: bool = False,
):
    """运行日志查询（`log_record` 表）：级别 / 源站 / 事件 / 任务 / 作品 / 关键字 / 时间窗 + 分页。

    日志由 logging Handler 在打日志时自动落库（见 crawler 的 `log_handler`），
    所以这里查到的就是 api.log 里那些业务日志，只是**能按条件筛**、且不再需要前端轮询。
    """
    return ok(
        logs.query(
            level=level, source=source, event=event, task_id=task_id, comic_id=comic_id,
            keyword=keyword, since=since, until=until,
            page=page, page_size=page_size, with_exc=with_exc,
        )
    )


@router.get("/api/admin/logs/{log_id}")
def admin_log_detail(log_id: int):
    """单条日志（含异常堆栈全文）。"""
    row = logs.detail(log_id)
    if not row:
        raise HTTPException(status_code=404, detail="log not found")
    return ok(row)
