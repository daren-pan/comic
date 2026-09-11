"""漫画聚合平台 HTTP API 服务（架构方案 §4：网关 + 微服务）—— 应用装配入口。

本文件只做三件事：**建 app → 挂路由 → 托管前端产物**。具体实现在：

| 位置 | 职责 |
|---|---|
| `core/` | 基础设施：`config` 路径引导、`db` 存储句柄、`security` 认证、`responses` 统一响应 |
| `schemas.py` | 请求体模型（Pydantic） |
| `serializers.py` | 领域对象 → 前端驼峰契约 |
| `services/` | 业务动作：`images` 图片读写与占位图、`tasks` 后台任务、`sources` 数据源开关 |
| `routers/` | HTTP 接口：`public` 公开浏览、`auth` 认证、`users` 收藏/历史、`admin` 采集管理台 |

约定：响应统一为 `{ code, message, data }`；图片端点优先返回已转存的真实文件，
缺失时回退生成 SVG 占位图（保证页面不裂图）。

运行（本文件自动把 crawler-service/src 加入 sys.path，无需设 PYTHONPATH）：

    uvicorn main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import DIST_DIR  # 必须最先导入：内部完成 sys.path 引导
from routers import admin, auth, public, users

app = FastAPI(title="漫阅 Comic API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

app.include_router(public.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(admin.router)

# 托管前端构建产物（同源部署，免 CORS/代理）。挂载在最后，避免 "/" 抢走 API 路由。
if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="web")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
