"""采集管理台接口（运维用，免登录）。

能力：列出数据源 / 开关采集 / 手动触发采集 / 手动触发懒转存（转存完成后自动封面自愈）
/ 手动触发失效巡检（转存 + 全表校验已转存对象、缺失则恢复）。
采集 / 转存 / 巡检耗时，统一交给 `services.tasks` 后台线程执行，返回 `taskId` 供前端轮询。
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from core.db import db  # noqa: F401  —— 先导入以完成 sys.path 引导
from core.responses import ok
from schemas import AdminInspectBody, AdminSyncBody, AdminTransferBody
from services import sources, tasks
from services.images import admin_image_store

from comic_crawler.storage.mysql import MySQLStorage

router = APIRouter(tags=["admin"])


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
        # 转存完成后自动封面自愈：修复外链未落盘 / 本地文件缺失的封面（无需单独按钮）
        cover = heal_covers(storage, store, adapter_provider=create_adapter)
        return {**stats, "coverHeal": cover, "pagesByStatus": storage.count_pages_by_status()}

    task_id = tasks.new_task_id("transfer")
    tasks.run_task(task_id, "transfer", job)
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


@router.get("/api/admin/tasks")
def admin_tasks():
    return ok(tasks.recent(30))


@router.get("/api/admin/tasks/{task_id}")
def admin_task(task_id: str):
    t = tasks.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="task not found")
    return ok(t)
