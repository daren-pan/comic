"""漫画聚合平台 HTTP API 服务（架构方案 §4：网关 + 微服务）—— 应用装配入口。

本文件只做三件事：**建 app → 挂路由 → 托管前端产物**。具体实现在：

| 位置 | 职责 |
|---|---|
| `core/` | 基础设施：`bootstrap` 路径引导（导入即注入 sys.path）、`config` 路径常量、`db` 存储句柄、`security` 认证、`pagination` 分页归一、`responses` 统一响应 |
| `schemas.py` | 请求体模型（Pydantic） |
| `serializers.py` | 领域对象 → 前端驼峰契约（**纯函数**，不碰存储） |
| `services/` | 业务动作：`images` 图片取数决策与占位图、`tags` 标签批量注入、`admin_jobs` 管理台任务体、`tasks` 后台任务、`sources` 数据源开关 |
| `routers/` | HTTP 接口：`public` 公开浏览、`auth` 认证、`users` 收藏/历史、`admin` 采集管理台、`admin_users` 授权页 |

约定：响应统一为 `{ code, message, data }`；图片端点优先返回已转存的真实文件，
缺失时回退生成 SVG 占位图（保证页面不裂图）。
门禁分两级：**管理台与日志**（`admin`）要 `require_admin`（超管或普通管理员），
**授权页**（`admin_users`）要 `require_superadmin`（仅超管）—— 未登录 401 / 权限不足 403。
角色三档见 `core/security.py` 与 `docs/auth.md` §8。

运行（本文件自动把 crawler-service/src 加入 sys.path，无需设 PYTHONPATH）：

    uvicorn main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core import bootstrap  # noqa: F401  —— 必须最先导入：导入即完成 sys.path 引导
from core.config import DIST_DIR
from core.logging_setup import setup as setup_logging
from routers import admin, admin_users, auth, messages, public, users
from services import tasks

# 日志：自家日志加时间戳 + 轮询/探活接口不进访问日志（见 core/logging_setup.py）
setup_logging()

#: 本进程启动时刻 —— 用它作界清理上一进程残留的 running 任务（见下面的 lifespan）
_STARTED_AT = datetime.now()
_log = logging.getLogger("comic.admin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时做一次**最好努力**的收尾：把上一进程没跑完的任务标成「服务重启，任务中断」。

    ⚠️ 这里**不起任何执行器** —— 管理台「定时任务」的采集在独立进程 `comic-scheduler` 里
    （2026-10-06 搬出，见其 README），本进程只做配置/展示；这里清理的是**手动触发**的后台
    任务（`admin_task` 表，那次改动把任务表从内存搬到了库）。
    ⚠️ 数据库不通**不拦启动**：`reap_stale` 内部已 try/except，只记日志。
    """
    reaped = tasks.reap_stale(_STARTED_AT)
    if reaped:
        _log.warning("已把 %d 个上次没跑完的任务标为「%s」", reaped, tasks.INTERRUPTED)
    yield

# ⚠️ lifespan 里**没有**任何常驻执行器：管理台「定时任务」的**采集**由独立进程
#    `comic-scheduler` 执行（2026-10-06 从 api 进程里搬出去，见 services/scheduler.py）——
#    所以 api 重启/重部署不会中断定时采集。上面那个 lifespan 只做一次性残留清理。
app = FastAPI(title="漫阅 Comic API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

app.include_router(public.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(admin_users.router)
app.include_router(messages.router)

# 托管前端构建产物（同源部署，免 CORS/代理）。挂载在最后，避免 "/" 抢走 API 路由。
if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="web")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
