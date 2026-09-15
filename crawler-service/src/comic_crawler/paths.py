"""路径常量：服务根与运行产物位置（**跨模块复用的唯一真源**）。

⚠️ 为什么单独成文件：图库根此前由 `image_store.py` 里的 `__file__.parents[2]` 推导，
**文件往深放一层就会推错**（例如挪到 `images/store.py` 后 `parents[2]` 会指到
`comic_crawler/`）。把推导集中在这里一次定义，任何模块都从这里取，与自身位置无关。

目录形态（两种部署方式下解析结果一致）：
    开发态    <repo>/crawler-service/src/comic_crawler/paths.py
    打包态    <bundle>/src/comic_crawler/paths.py
    → SERVICE_ROOT 分别 = <repo>/crawler-service 、 <bundle>
"""
from __future__ import annotations

from pathlib import Path

# 本文件位于 <服务根>/src/comic_crawler/ 之下，故「上两级」即服务根
PKG_DIR = Path(__file__).resolve().parent        # .../comic_crawler
SRC_DIR = PKG_DIR.parent                         # .../src
SERVICE_ROOT = SRC_DIR.parent                   # crawler-service/ 或 <bundle>/

# 运行时数据根目录（**本地直跑与容器必须落在同一处** —— 见下），里面是"可变数据"：
#     data/image_store/        图库
#     data/source_state.json   管理台「数据源开关」状态（api 侧 COMIC_STATE_FILE 的默认值）
# 为什么要有这一层：容器部署时整个 /data 会 bind 到这个目录，于是"本地直跑"与"Docker 里跑"
# 读写的是**同一批文件**；否则同一台机器上会出现两份图库，本地转存的图容器读不到（反之亦然），
# 只能靠"记得同步"维持，而项目在数据库上已经吃过一次这种亏（见 AGENTS.md 硬性约定）。
DATA_ROOT = SERVICE_ROOT / "data"

# 图库（本地模拟 OSS）默认根目录；env COMIC_IMAGE_ROOT 可覆盖，见 images.store
IMAGE_STORE_ROOT = DATA_ROOT / "image_store"

# 管理台「数据源开关」状态文件的默认位置；api 侧 env COMIC_STATE_FILE 可覆盖
SOURCE_STATE_FILE = DATA_ROOT / "source_state.json"

# 仓库根（仅开发态有意义：用于定位 fixtures 等仓库内资源，打包态不依赖它）
REPO_ROOT = SERVICE_ROOT.parent
