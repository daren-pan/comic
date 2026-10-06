"""路径常量：服务根与运行产物位置（**跨模块复用的唯一真源**）。

⚠️ 为什么单独成文件：图库根此前由 `image_store.py` 里的 `__file__.parents[2]` 推导，
**文件往深放一层就会推错**（例如挪到 `images/store.py` 后 `parents[2]` 会指到
`comic_crawler/`）。把推导集中在这里一次定义，任何模块都从这里取，与自身位置无关。

⚠️ **数据根不随本包位置走**：本包（`comic_core`）是采集端与接口端共用的内核，2026-09-24
从 `crawler-service/src/comic_crawler/` 抽出。若仍按「文件自身位置上溯两级」推导，开发态
会从 `<repo>/crawler-service/data` 漂到 `<repo>/comic-core/data` —— 而容器把 `/data` bind 的
正是前者（见 `deploy/docker-compose.yml`），一漂就破坏「本地直跑与 Docker 读写同一批文件」。
故这里显式判定：**开发态数据根寄居在兄弟目录 `crawler-service/data`**（历史位置，暂不迁移），
打包态仍是 `<bundle>/data`。

目录形态：
    开发态    <repo>/comic-core/src/comic_core/paths.py      → SERVICE_ROOT = <repo>/crawler-service
    打包态    <bundle>/src/comic_core/paths.py               → SERVICE_ROOT = <bundle>
"""
from __future__ import annotations

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent        # .../comic_core
SRC_DIR = PKG_DIR.parent                         # .../src
_PKG_ROOT = SRC_DIR.parent                       # 开发态 <repo>/comic-core ；打包态 <bundle>

# 开发态仓库布局里，运行时数据仍寄居在兄弟目录 crawler-service 下；打包态没有这个兄弟目录，
# 于是回落到 <bundle>（与旧行为一致）。容器/wheel 态由 env COMIC_IMAGE_ROOT / COMIC_STATE_FILE
# 覆盖，走不到这里的默认值。
_DEV_DATA_OWNER = _PKG_ROOT.parent / "crawler-service"
SERVICE_ROOT = _DEV_DATA_OWNER if (_DEV_DATA_OWNER / "src").is_dir() else _PKG_ROOT

# 运行时数据根目录（**本地直跑与容器必须落在同一处** —— 见下），里面是"可变数据"：
#     data/image_store/        图库
#     data/source_state.json   管理台「数据源开关」状态（读写见 sources/state.py，env COMIC_STATE_FILE 可覆盖）
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
