# 漫阅 · 漫画聚合平台（comic-platform）

面向演示的漫画聚合平台：**多源采集 → 指纹去重入库 → REST API → 前端同源托管** 全链路代码。
存储唯一方案为 **MySQL**（`MySQLStorage` 单实现，`Storage` 抽象作为契约保留），图片统一为**图库内相对 key**。

> 仓库**不携带任何数据文件**（`*.db*` / `*.sqlite*` 已全局忽略）。数据需联网采集重建后使用。
> 参考：`cli run` 增量/全量采集（见 crawler-service/README.md）。

## 目录结构

```
comic/
├── docs/                     # 设计与原理文档（architecture / auth；各源站说明随代码放在 sources/<源名>/）
├── crawler-service/          # 采集服务（Python）：适配器/调度/指纹去重/图片懒转存
│   ├── src/comic_crawler/    #   核心包 L0/L1/L2 分层：sources/<源名>/ 自包含、storage/mysql/、images/、scheduling/
│   ├── sql/                  #   mysql_schema.sql（表结构，无数据快照）
│   ├── image_store/          #   图库：covers/{id}.jpg 封面、comic/{cid}/{chid}/{page}.jpg 分页图
│   ├── tests/                #   单元测试（含 test_layering.py 分层守卫；样例 HTML 随各源包 fixtures/）
├── api-service/              # FastAPI 业务服务（唯一存储：MySQL，同源托管前端）
│   ├── main.py               #   装配入口（建 app / 挂路由 / 托管 dist）
│   ├── core/ services/       #   基础设施（config·db·security·responses）与业务动作（images·tasks·sources）
│   ├── routers/              #   HTTP 接口分层：public / auth / users / admin
│   └── schemas.py serializers.py  # 请求体模型 / 领域对象序列化
├── comic-web/                # 前端（Vite + Vue3，dist 不随仓库分发，clone 后需先 npm run build）
├── tools/                    # 一次性运维脚本（标签回填/规范化等，见 tools/README.md）
├── scripts/                  # 一键脚本：初始化/启动/自检/打包（.bat + .sh 双份，见 scripts/README.md）
└── logs/                     # 运行时日志（api/vite，gitignore 不入库）
```

> 📦 **发布包不随仓库保存**：部署时用 `./scripts/package.sh`（或 `package.bat`）生成到 `build/deploy`，
> 避免像以前 `comic-deploy/` 那样维护手工双副本而漂移。

> 📖 **文档入口：`docs/`** —— [`architecture.md`](docs/architecture.md) 总体架构设计、
> [`auth.md`](docs/auth.md) 登录认证原理；各源站接口与限制见 `crawler-service/src/comic_crawler/sources/<源名>/README.md`。

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
PYTHONPATH=src python -m comic_crawler.cli inspect                  # 失效巡检（转存未转存页 + 全表校验已转存对象 + 恢复丢失）
```

> 采集与 API 均直连 MySQL（`COMIC_MYSQL_*` 配置）。
> 除 CLI 外，也可在站点 `/#/admin` **采集管理控制台**手动触发采集/懒转存/失效巡检（按源开关；采集支持 `mode`/`since`/`limit`，转存支持 `since`/`until` 且**把窗口内所有未转存页全部转掉**；巡检是**全库单一入口**（页面顶部一块面板，不随源卡片复制），支持 `since`/`until`，并额外**全表校验**已转存对象是否还在、缺失则恢复；无需登录）。
> 转存完成后会自动顺带执行**封面自愈**（`scheduling.heal.heal_covers`，无独立入口）。

图片约定（务必遵守）：

- DB 内 `cover_url` / `oss_url` **只存图库相对 key**（如 `covers/26.jpg`、`comic/26/34/001.jpg`），不存外链/绝对路径；
- 图库根**唯一真源** `images.store.default_store_root()`：`COMIC_IMAGE_ROOT` → 仓库根 `image_store/`；**读写两端共用同一函数，不随进程 cwd 漂移**（曾因两端各自解析、优先级相反，导致 DB 有 `oss_url`、文件也落了盘，接口却读不到而全站返回占位图）；
- 封面落盘由调度同步自动执行（`ensure_cover_local` 幂等自愈），新增适配器无需自行处理封面外链。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `COMIC_IMAGE_ROOT` | 自动 | 图库根目录覆盖（读写端统一经 `default_store_root()` 定位）。**须为绝对路径**；空值 / `none`·`false`·`0` 等哨兵值 / 相对路径会被**忽略并告警**，回落到默认根 |
| `COMIC_MYSQL_HOST` | `127.0.0.1` | MySQL 主机 |
| `COMIC_MYSQL_PORT` | `3307` | MySQL 端口（Docker ruoyi-mysql 映射） |
| `COMIC_MYSQL_USER` | `root` | MySQL 用户 |
| `COMIC_MYSQL_PASSWORD` | `password` | MySQL 密码 |
| `COMIC_MYSQL_DB` | `comic` | MySQL 库名 |

## 服务清单（启动后）

| 地址 | 说明 |
|---|---|
| http://127.0.0.1:8000/ | 前端站点（同源托管） |
| http://127.0.0.1:8000/#/admin | 采集管理控制台（手动触发采集/懒转存、按源开关、`since`/`until` 控制转存范围；无需登录） |
| http://127.0.0.1:8000/docs | FastAPI Swagger 文档 |
| `GET /api/health` | 健康检查 + 库内统计 |
| `GET /api/comics?category=&keyword=&sort=&page=` | 作品列表 |
| `GET /api/comics/{id}` · `/chapters` | 详情 / 章节 |
| `GET /api/chapters/{id}/pages` | 分页图 |
| `GET /api/covers/{id}` · `/api/images/{cid}/{chid}/{pno}` | 封面 / 分页图（真实文件优先，缺失 SVG 占位） |
| `GET/PUT/DELETE /api/users/{uid}/favorites[/{cid}]` · `history` | 收藏 / 历史（匿名 userId，跨浏览器续读） |

## 合规说明

- 仓库内 `image_store/` 不入库（gitignore），图库内容为**本机受控抓取的少量章节页**（在漫画等源站公开免费内容，仅供个人学习演示，不对外分发、不绕过付费/VIP）；
- 采集适配器仅用于接口演示，请尊重源站 robots 与版权，控制频率；
- 若需公开此仓库，请先移除演示抓取的版权图片（清空 `image_store` 并用 `cli run` 重建可授权数据）。
