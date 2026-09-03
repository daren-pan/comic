# 漫阅 · 漫画聚合平台（comic-platform）

面向演示的漫画聚合平台：**多源采集 → 指纹去重入库 → REST API → 前端同源托管** 全链路代码。
含 MySQL / SQLite 双存储实现（`COMIC_DB_TYPE` 一行切换），图片统一为**图库内相对 key**。

> 仓库**不携带任何数据文件**（`*.db` / `*.sqlite*` 已全局忽略）。数据需联网采集重建，或按「方案 B」导入 MySQL 后同步。
> 参考：`cli run` 增量/全量采集（见 crawler-service/README.md），或 `python tools/sync_mysql_to_sqlite.py` 生成离线 SQLite。

## 目录结构

```
comic/
├── crawler-service/          # 采集服务（Python）：适配器/调度/指纹去重/图片懒转存
│   ├── src/comic_crawler/    #   核心包（adapter 注册源站、storage 双实现、cli）
│   ├── sql/                  #   mysql_schema.sql（表结构，无数据快照）
│   ├── image_store/          #   图库：covers/{id}.jpg 封面、comic/{cid}/{chid}/{page}.jpg 分页图
│   ├── fixtures/ tests/      #   模拟源站 HTML 与单元测试
├── api-service/              # FastAPI 业务服务（SQLite/MySQL 可切换，同源托管前端）
├── comic-deploy/             # 发布包：main.py + comic_crawler + dist（数据文件/图库不随仓库分发）
├── comic-web/                # 前端（Vite + React，dist 已构建并随仓库分发）
├── tools/                    # sync_mysql_to_sqlite.py：MySQL 权威数据 → SQLite 刷新工具
├── scripts/                  # 一键脚本：启动/初始化/数据刷新（.bat + .sh 双份）
└── 漫画聚合网站_架构设计方案.md
```

## 快速开始（异地 clone 后）

环境要求：**Python 3.10+**（可再选配 MySQL 5.7/8 与 Node.js 18+）。

### 方案 A：免 MySQL，SQLite 直跑（需先采集/导入数据）

仓库**不带数据文件**。首次运行前，先跑一次采集把数据写入 SQLite，或用 MySQL 完整版同步出离线文件：
```bash
cd crawler-service
PYTHONPATH=src python -m comic_crawler.cli run --source zaimanhua --mode full   # 联网采集（可换 --source）
# 采集后生成的 comic_demo.db 即可供 api-service / comic-deploy 读取
```

再启动站点（SQLite 模式）：
```bash
# Windows
python -m venv .venv && .venv\Scripts\pip install -r comic-deploy/requirements.txt
.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000   # 先 cd comic-deploy
# 或直接：scripts\start_release.bat

# macOS / Linux
python3 -m venv .venv && .venv/bin/pip install -r comic-deploy/requirements.txt
cd comic-deploy && ../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
# 或直接：scripts/start_release.sh
```

打开 http://127.0.0.1:8000 即可浏览全部漫画、看图、收藏、记录历史。

### 方案 B：MySQL 完整版（可跑采集同步、多机共用数据）

```bash
# 1. 初始化数据库结构（幂等；注意会 DROP 目标库同名表）
mysql -h127.0.0.1 -P3307 -uroot -ppassword --default-character-set=utf8mb4 < crawler-service/sql/mysql_schema.sql
# 或直接：scripts\init_mysql.bat / scripts/init_mysql.sh

# 2. 以 MySQL 模式启动 API（连接参数可用 COMIC_MYSQL_* 覆盖）
COMIC_DB_TYPE=mysql python -m uvicorn main:app --host 127.0.0.1 --port 8000   # 先 cd api-service
# 或直接：scripts\start_mysql.bat / scripts/start_mysql.sh
```

### （可选）重新构建前端

改完 `comic-web/src` 后：`cd comic-web && npm install && npm run build`，产物 `comic-web/dist`
（base 为相对路径）供 `api-service`/`comic-deploy` 同源托管。

## 数据更新与图片转存

```bash
# 采集最新章节（源站适配器见 crawler-service/README.md，真实源需联网）
cd crawler-service
PYTHONPATH=src python -m comic_crawler.cli run --source zaimanhua   # 增量同步某源
PYTHONPATH=src python -m comic_crawler.cli transfer-images          # 未转存图片懒转存
PYTHONPATH=src python -m comic_crawler.cli inspect                  # 失效巡检（封面自愈）

# 采集写入 MySQL 后，可刷新离线 SQLite（供 api-service/comic-deploy 的 SQLite 模式读取）
python tools/sync_mysql_to_sqlite.py
# 或直接：scripts\sync_sqlite.bat / scripts/sync_sqlite.sh
```

图片约定（务必遵守）：

- DB 内 `cover_url` / `oss_url` **只存图库相对 key**（如 `covers/26.jpg`、`comic/26/34/001.jpg`），不存外链/绝对路径；
- 读端自动定位图库根：`COMIC_IMAGE_ROOT` → main.py 同目录 → DB 同目录 → 开发结构 `crawler-service/image_store`；
- 封面落盘由调度同步自动执行（`ensure_cover_local` 幂等自愈），新增适配器无需自行处理封面外链。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `COMIC_DB_TYPE` | `sqlite` | `sqlite` / `mysql` 存储切换（api-service 启动时读取） |
| `COMIC_DB` | 自动 | SQLite 文件路径覆盖 |
| `COMIC_IMAGE_ROOT` | 自动 | 图库根目录覆盖 |
| `COMIC_MYSQL_HOST` | `127.0.0.1` | MySQL 主机 |
| `COMIC_MYSQL_PORT` | `3307` | MySQL 端口（Docker ruoyi-mysql 映射） |
| `COMIC_MYSQL_USER` | `root` | MySQL 用户 |
| `COMIC_MYSQL_PASSWORD` | `password` | MySQL 密码 |
| `COMIC_MYSQL_DB` | `comic` | MySQL 库名 |

## 服务清单（启动后）

| 地址 | 说明 |
|---|---|
| http://127.0.0.1:8000/ | 前端站点（同源托管） |
| http://127.0.0.1:8000/docs | FastAPI Swagger 文档 |
| `GET /api/health` | 健康检查 + 库内统计 |
| `GET /api/comics?category=&keyword=&sort=&page=` | 作品列表 |
| `GET /api/comics/{id}` · `/chapters` | 详情 / 章节 |
| `GET /api/chapters/{id}/pages` | 分页图 |
| `GET /api/covers/{id}` · `/api/images/{cid}/{chid}/{pno}` | 封面 / 分页图（真实文件优先，缺失 SVG 占位） |
| `GET/PUT/DELETE /api/users/{uid}/favorites[/{cid}]` · `history` | 收藏 / 历史（匿名 userId，跨浏览器续读） |

## 合规说明

- 仓库内真实图片仅包含 **CC-BY 4.0 开源授权**（Pepper & Carrot）与**本机受控演示抓取的少量章节页**（瓜子漫画/在漫画，均为站点公开免费内容，仅供个人学习演示，不对外分发、不绕过付费/VIP）；
- 采集适配器仅用于接口演示，请尊重源站 robots 与版权，控制频率；
- 若需公开此仓库，请先移除演示抓取的版权图片（清空 `image_store` 并用 `tools/sync_mysql_to_sqlite.py` 重建数据）。
