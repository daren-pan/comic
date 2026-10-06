"""api-service 的路径常量（**纯常量，无副作用**）。

⚠️ 采集层的 `sys.path` 引导**不在本模块** —— 那是导入副作用，归 `core.bootstrap`
（需要 `import comic_crawler` 的模块先导入它）。本模块只算路径，import 它不会改任何
全局状态，单测可以放心只读常量。

⚠️ 「数据源开关」状态文件的路径**也不在这里**（2026-09-24 调整）：它描述的是采集源的
启停，属于采集域的运行时状态，读写与路径都归 `comic_crawler`（见 `sources/state.py`，
env `COMIC_STATE_FILE` 由那边解析）。api 侧只调门面的 `load_source_state` /
`save_source_state`，不再需要知道这个文件。
"""
from __future__ import annotations

import os
from pathlib import Path

# api-service/ 目录（本文件位于 api-service/core/ 下）；打包后即发布包根目录
APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent

# 前端构建产物（同源托管）：默认按相对位置找 —— 发布包内 dist → 开发态 comic-web/dist。
# 只服务「仓库直跑」与「发布包」两种形态：容器里**不再托管前端**（网页端/移动端各自一个带 nginx
# 的镜像，见 deploy/），wheel 态程序装进 site-packages、相对位置失去意义，也就不需要它 ——
# 所以 deploy/api/Dockerfile 不再设 COMIC_DIST_DIR，main.py 那层挂载靠 `is_dir()` 守卫自然跳过。
# 仍保留这个环境变量：需要把 dist 指到别处时显式覆盖（只接受绝对路径，否则忽略并回落默认，
# 与 COMIC_IMAGE_ROOT 同一原则）。
_DIST_ENV = os.environ.get("COMIC_DIST_DIR", "").strip()
DIST_DIR = (
    Path(_DIST_ENV)
    if os.path.isabs(_DIST_ENV)
    else (APP_DIR / "dist" if (APP_DIR / "dist").is_dir() else ROOT / "comic-web" / "dist")
)

# 说明：运行日志已改为**落库**（`log_record` 表，见 storage/mysql/log_handler.py），
# 管理台「日志查询」页查的是库、不再读文件；日志文件由启动命令的重定向决定（约定 `logs/api.log`），
# 代码里无需感知路径 —— 故此处不再保留 LOG_DIR 常量。
