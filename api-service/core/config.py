"""运行环境引导与路径常量。

⚠️ **本模块必须最先被导入**：它在导入时把采集服务包写入 `sys.path`，凡是需要
`import comic_crawler` 的模块（如 `core.db`、`services.*`）都要先导入本模块。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# api-service/ 目录（本文件位于 api-service/core/ 下）；打包后即发布包根目录
APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent

# comic_crawler 包的搜索路径，按部署形态依次尝试（下表为「可导入 comic_crawler 的父目录」）：
#   1) 开发态   <repo>/crawler-service/src
#   2) 打包态   <bundle>            （comic_crawler 与 main.py 同级）
#   3) 打包态   <bundle>/src        （与开发态同构，让图库根解析一致）
#   4) wheel 态 无需处理 —— comic_crawler 作为依赖被 pip 装进 site-packages 直接可导入，
#               下面三个候选目录都不存在时循环自然跳过（见 deploy/ 的镜像构建）
CRAWLER_SRC = ROOT / "crawler-service" / "src"
for _pkg_parent in (CRAWLER_SRC, APP_DIR, APP_DIR / "src"):
    if (_pkg_parent / "comic_crawler").is_dir() and str(_pkg_parent) not in sys.path:
        sys.path.insert(0, str(_pkg_parent))

# 前端构建产物（同源托管）：默认按相对位置找 —— 发布包内 dist → 开发态 comic-web/dist。
# 只服务「仓库直跑」与「发布包」两种形态：容器里**不再托管前端**（网页端/移动端各自一个带 nginx
# 的镜像，见 deploy/），wheel 态程序装进 site-packages、相对位置失去意义，也就不需要它 ——
# 所以 deploy/api/Dockerfile 不再设 COMIC_DIST_DIR，main.py 那层挂载靠 `is_dir()` 守卫自然跳过。
# 仍保留这个环境变量：需要把 dist 指到别处时显式覆盖（只接受绝对路径，否则忽略并回落默认，
# 与 COMIC_IMAGE_ROOT / COMIC_STATE_FILE 同一原则）。
_DIST_ENV = os.environ.get("COMIC_DIST_DIR", "").strip()
DIST_DIR = (
    Path(_DIST_ENV)
    if os.path.isabs(_DIST_ENV)
    else (APP_DIR / "dist" if (APP_DIR / "dist").is_dir() else ROOT / "comic-web" / "dist")
)

# 管理台「数据源开关」状态的持久化文件（重启不丢）。
# 默认值**复用采集层契约面导出的 `SOURCE_STATE_FILE`**（= `<data>/source_state.json`，与图库同一个
# 运行时数据目录）—— 刻意不再用 `api-service/source_state.json`：那位置在容器里会被镜像重建冲掉，
# 而且会和容器内的状态文件并存成两份（本项目真发生过两边开关不一致：一边 mangadex 开、一边关）。
# 容器部署时整个 /data 已 bind 到同一个宿主目录，故两侧默认值天然一致；要另指才用 COMIC_STATE_FILE。
# 与 COMIC_IMAGE_ROOT 同一原则：**只接受绝对路径**，否则忽略并回落默认值。
from comic_crawler.facade import SOURCE_STATE_FILE as _DEFAULT_STATE_FILE  # noqa: E402

_STATE_ENV = os.environ.get("COMIC_STATE_FILE", "").strip()
SOURCE_STATE_FILE = (
    Path(_STATE_ENV) if os.path.isabs(_STATE_ENV) else _DEFAULT_STATE_FILE
)

# 说明：运行日志已改为**落库**（`log_record` 表，见 storage/mysql/log_handler.py），
# 管理台「日志查询」页查的是库、不再读文件；日志文件由启动命令的重定向决定（约定 `logs/api.log`），
# 代码里无需感知路径 —— 故此处不再保留 LOG_DIR 常量。
