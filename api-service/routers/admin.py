"""采集管理台接口（**仅超级管理员**）。

`router` 上挂了 `require_admin`（一处覆盖下面全部接口）：超管与**普通管理员都能过** —— **未登录 401 / 无管理员权限 403**。授权页在另一个 router，门槛更高（见 `routers/admin_users.py`）。
角色定义与判断见 `core/security.py`；给他人授权在 `routers/admin_users.py`（授权页）。

能力：列出数据源 / 开关采集 / 手动触发采集 / 手动触发**失效巡检**（转存未转存页 + 全表校验
已转存对象、缺失则恢复 + 全库封面自愈）/ 手动触发**按作品**封面自愈（填漫画名称或 ID，
强制回源重下覆盖）/ 按需导入单部作品 / 查询运行日志（`log_record` 表，支持条件筛选与分页）。

本层只做「校验入参 → 派发任务 → 返回 `taskId`」；任务的**实际动作**（采集编排、封面自愈、
巡检、按需导入）在 `services.admin_jobs`。耗时动作统一交给 `services.tasks` 后台线程执行，
前端轮询 `taskId` 取结果。

⚠️ **独立的「触发转存」入口已删除（2026-09-21）**：巡检第 1 步本就是 `lazy_transfer`
（转存未转存页），单独按钮是它的子集、无独立价值；原挂在转存上的「全库封面自愈」
已并入巡检任务。CLI 的 `transfer-images` 保留（脚本/运维用），`lazy_transfer` 函数保留。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.responses import ok
from core.security import require_admin
from schemas import (
    AdminHealBody,
    AdminImportBody,
    AdminInspectBody,
    AdminSyncBody,
)
from services import admin_jobs, logs, sources, tasks

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/api/admin/sources")
def admin_sources():
    return ok(sources.meta())


@router.post("/api/admin/sources/{name}/toggle")
def admin_toggle_source(name: str):
    return ok({"name": name, "enabled": sources.toggle(name)})


@router.post("/api/admin/sync")
def admin_sync(body: AdminSyncBody):
    """手动触发采集（后台线程执行，返回 `taskId` 供前端轮询）。动作见 `admin_jobs.sync_job`。"""
    if not sources.is_enabled(body.source):
        raise HTTPException(status_code=400, detail=f"源 {body.source} 已关闭采集")
    task_id = tasks.new_task_id("sync")
    tasks.run_task(
        task_id, "sync",
        lambda: admin_jobs.sync_job(body.source, body.mode, body.limit, body.since),
    )
    return ok({"taskId": task_id})


@router.post("/api/admin/heal-covers")
def admin_heal_covers(body: AdminHealBody):
    """封面自愈（**按作品**）：填漫画名称或 ID（可多个），**强制**回源重抓封面并覆盖。

    用于修复「封面文件在、但内容是错的」—— 普通自愈只看文件在不在，永远修不到错图；
    这里 `force=True` 跳过「文件在即健康」的早返回，对命中作品重新下载覆盖。
    `keyword` **必填**：逗号 / 空格 / 换行分隔，每项是作品 ID 或名称（可混填，一次多部）。
    解析与动作见 `services.admin_jobs.parse_heal_keyword` / `heal_covers_job`。
    """
    comic_ids, title_like = admin_jobs.parse_heal_keyword(body.keyword)
    if not comic_ids and not title_like:
        raise HTTPException(status_code=400, detail="请填写漫画名称或 ID（可多个，用逗号/空格/换行分隔）")
    task_id = tasks.new_task_id("heal")
    tasks.run_task(
        task_id, "heal",
        lambda: admin_jobs.heal_covers_job(body.source, comic_ids, title_like),
    )
    return ok({"taskId": task_id})


@router.post("/api/admin/inspect")
def admin_inspect(body: AdminInspectBody):
    """失效巡检（**全库维护的唯一入口**）：转存未转存页 + **全表**校验已转存对象 + 全库封面自愈。

    三步做什么、为什么定时巡检不含第 3 步，见 `services.admin_jobs.inspect_job`。
    """
    task_id = tasks.new_task_id("inspect")
    tasks.run_task(
        task_id, "inspect",
        lambda: admin_jobs.inspect_job(body.source, body.since, body.until),
    )
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
    task_id = tasks.new_task_id("import")
    tasks.run_task(
        task_id, "import",
        lambda: admin_jobs.import_job(
            body.source, body.keyword, body.ref, body.source_comic_id, body.first_chapters
        ),
    )
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
