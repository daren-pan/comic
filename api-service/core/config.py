"""运行环境引导与路径常量。

⚠️ **本模块必须最先被导入**：它在导入时把采集服务包写入 `sys.path`，凡是需要
`import comic_crawler` 的模块（如 `core.db`、`services.*`）都要先导入本模块。
"""
from __future__ import annotations

import sys
from pathlib import Path

# api-service/ 目录（本文件位于 api-service/core/ 下）；打包后即发布包根目录
APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent

# comic_crawler 包的搜索路径，按部署形态依次尝试（下表为「可导入 comic_crawler 的父目录」）：
#   1) 开发态   <repo>/crawler-service/src
#   2) 打包态   <bundle>            （comic_crawler 与 main.py 同级）
#   3) 打包态   <bundle>/src        （与开发态同构 —— 推荐，能让 image_store 根解析一致：
#                                     default_store_root() 取 `__file__.parents[2]`，
#                                     `<bundle>/src/comic_crawler/` → `<bundle>/image_store`）
CRAWLER_SRC = ROOT / "crawler-service" / "src"
for _pkg_parent in (CRAWLER_SRC, APP_DIR, APP_DIR / "src"):
    if (_pkg_parent / "comic_crawler").is_dir() and str(_pkg_parent) not in sys.path:
        sys.path.insert(0, str(_pkg_parent))

# 前端构建产物：优先发布包内 dist，其次开发态的 comic-web/dist（同源托管）
DIST_DIR = APP_DIR / "dist" if (APP_DIR / "dist").is_dir() else ROOT / "comic-web" / "dist"

# 管理台「数据源开关」状态的持久化文件（重启不丢）
SOURCE_STATE_FILE = APP_DIR / "source_state.json"
