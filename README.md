# 漫阅 · 漫画聚合平台（comic-platform）

面向演示的漫画聚合平台：**多源采集 → 指纹去重入库 → REST API → 前端同源托管** 全链路代码。
存储唯一方案为 **MySQL**（`MySQLStorage` 单实现，`Storage` 抽象作为契约保留），图片统一为**图库内相对 key**。

> 仓库**不携带任何数据文件**（`*.db*` / `*.sqlite*` 已全局忽略）。数据需联网采集重建后使用。
> 参考：`cli run` 增量/全量采集（见 crawler-service/README.md）。

## 目录结构

```
comic/
├── crawler-service/          # 采集服务（Python）：适配器/调度/指纹去重/图片懒转存
│   ├── src/comic_crawler/    #   核心包（adapter 注册源站、storage 契约 + MySQL 实现、cli）
│   ├── sql/                  #   mysql_schema.sql（表结构，无数据快照）
│   ├── image_store/          #   图库：covers/{id}.jpg 封面、comic/{cid}/{chid}/{page}.jpg 分页图
│   ├── fixtures/ tests/      #   模拟源站 HTML 与单元测试
├── api-service/              # FastAPI 业务服务（唯一存储：MySQL，同源托管前端）
├── comic-deploy/             # 发布包：main.py + comic_crawler（图库/dist 不随仓库分发）
├── comic-web/                # 前端（Vite + Vue3，dist 不随仓库分发，clone 后需先 npm run build）
├── tools/                    # 一次性运维脚本（标签回填/规范化等）
├── scripts/                  # 一键脚本：启动/初始化（.bat + .sh 双份）
└── 漫画聚合网站_架构设计方案.md
```

## 快速开始（异地 clone 后）

环境要求：**Python 3.10+**（可再选配 MySQL 5.7/8 与 Node.js 18+）。

> ⚠️ 仓库**不携带前端构建产物**（`dist/` 已 gitignore）。首次运行前需先构建前端：
> ```bash
> cd comic-web && npm install && npm run build   # 产物 comic-web/dist，供 api-service 同源托管
> ```
> 若只跑后端 API、不打开网页，可跳过此步。

### 方案：MySQL 完整版（项目唯一存储方案）

```bash
# 1. 初始化数据库结构（幂等；注意会 DROP 目标库同名表）
mysql -h127.0.0.1 -P3307 -uroot -ppassword --default-character-set=utf8mb4 < crawler-service/sql/mysql_schema.sql
# 或直接：scripts\init_mysql.bat / scripts/init_mysql.sh

# 2. 采集写库（首次需联网增量/全量）
cd crawler-service
PYTHONPATH=src python -m comic_crawler.cli run --source zaimanhua --mode full   # 可换 --source
PYTHONPATH=src python -m comic_crawler.cli transfer-images                       # 图片懒转存（可选）

# 3. 启动站点（连接参数可用 COMIC_MYSQL_* 覆盖）
python -m uvicorn main:app --host 127.0.0.1 --port 8000   # cd api-service 后
# 或直接：scripts\start_mysql.bat / scripts/start_mysql.sh
```

打开 http://127.0.0.1:8000 即可浏览全部漫画、看图、收藏、记录历史。

### （必做）构建前端

前端源码在 `comic-web/src`，仓库**不带 dist**。clone 后必须先构建一次（或每次改完 `src` 后重新构建）：
```bash
cd comic-web && npm install && npm run build   # 产物 comic-web/dist（base 为相对路径）
```
构建产物 `comic-web/dist` 供 `api-service` 同源托管；`dist` 不入库（已在 .gitignore）。

### 前端本地开发（可选）
```bash
cd comic-web && npm run dev   # Vite dev server（5173），/api 由 Vite 代理到 8000 后端
```

## 数据更新与图片转存

```bash
# 采集最新章节（源站适配器见 crawler-service/README.md，真实源需联网）
cd crawler-service
PYTHONPATH=src python -m comic_crawler.cli run --source zaimanhua   # 增量同步某源
PYTHONPATH=src python -m comic_crawler.cli transfer-images          # 未转存图片懒转存
PYTHONPATH=src python -m comic_crawler.cli inspect                  # 失效巡检（封面自愈）
```

> 采集与 API 均直连 MySQL（`COMIC_MYSQL_*` 配置）。
> 除 CLI 外，也可在站点 `/#/admin` **采集管理控制台**手动触发采集/懒转存（按源开关、`since`/`limit` 控制范围，无需登录）。

图片约定（务必遵守）：

- DB 内 `cover_url` / `oss_url` **只存图库相对 key**（如 `covers/26.jpg`、`comic/26/34/001.jpg`），不存外链/绝对路径；
- 读端自动定位图库根：`COMIC_IMAGE_ROOT` → main.py 同目录 → DB 同目录 → 开发结构 `crawler-service/image_store`；
- 封面落盘由调度同步自动执行（`ensure_cover_local` 幂等自愈），新增适配器无需自行处理封面外链。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `COMIC_IMAGE_ROOT` | 自动 | 图库根目录覆盖（读端 `_resolve_image_root` 自动定位） |
| `COMIC_MYSQL_HOST` | `127.0.0.1` | MySQL 主机 |
| `COMIC_MYSQL_PORT` | `3307` | MySQL 端口（Docker ruoyi-mysql 映射） |
| `COMIC_MYSQL_USER` | `root` | MySQL 用户 |
| `COMIC_MYSQL_PASSWORD` | `password` | MySQL 密码 |
| `COMIC_MYSQL_DB` | `comic` | MySQL 库名 |

## 服务清单（启动后）

| 地址 | 说明 |
|---|---|
| http://127.0.0.1:8000/ | 前端站点（同源托管） |
| http://127.0.0.1:8000/#/admin | 采集管理控制台（手动触发采集/懒转存、按源开关、since/limit 控制范围；无需登录） |
| http://127.0.0.1:8000/docs | FastAPI Swagger 文档 |
| `GET /api/health` | 健康检查 + 库内统计 |
| `GET /api/comics?category=&keyword=&sort=&page=` | 作品列表 |
| `GET /api/comics/{id}` · `/chapters` | 详情 / 章节 |
| `GET /api/chapters/{id}/pages` | 分页图 |
| `GET /api/covers/{id}` · `/api/images/{cid}/{chid}/{pno}` | 封面 / 分页图（真实文件优先，缺失 SVG 占位） |
| `GET/PUT/DELETE /api/users/{uid}/favorites[/{cid}]` · `history` | 收藏 / 历史（匿名 userId，跨浏览器续读） |

## 合规说明

- 仓库内真实图片仅包含 **CC-BY 4.0 开源授权**（Pepper & Carrot）与**本机受控演示抓取的少量章节页**（在漫画，均为站点公开免费内容，仅供个人学习演示，不对外分发、不绕过付费/VIP）；
- 采集适配器仅用于接口演示，请尊重源站 robots 与版权，控制频率；
- 若需公开此仓库，请先移除演示抓取的版权图片（清空 `image_store` 并用 `cli run` 重建可授权数据）。
