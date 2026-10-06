# 项目长期备忘（comic 聚合平台）

> 只放 **整体架构 / 各模块简介 / 基础命令 / 硬性约定** —— 实现细节、参数、踩坑复盘写到对应模块 README 或 `docs/`，这里只留一行指针。日志写 `.workbuddy/memory/YYYY-MM-DD.md`。
> **与仓库根 [`AGENTS.md`](../AGENTS.md) 保持同步**（那份给读代码的 AI / 新人看，本文件是 AI 协作助手自动加载的副本；**改任一份都要改另一份**）。以下正文与 AGENTS.md 逐字一致，只有本头部不同。

## 整体架构

三层服务 + 单一 MySQL（本项目**独占**的 MySQL 8.0 实例，容器 `comic-mysql`：宿主 `127.0.0.1:3309`）。

```
comic/
├── comic-core/        # 共用内核：领域模型 · 路径 · 存储契约+MySQL 实现 · 图库（被下面两层共同依赖）
├── crawler-service/   # 采集 · 存储 · 图床（Python；L0 内核 / L1 契约 / L2 实现）
├── api-service/       # 对外 REST API（FastAPI :8000）—— Docker 里是**纯 API**（同源托管仅本地直跑时生效）
├── comic-web/         # 前端 · Web SPA（Vue3 + Vite :5173）—— 已冻结，只作参考实现
├── comic-front/       # 前端 · uni-app（H5 :5174 / 小程序 / App）—— **当前主用**
├── deploy/            # 生产编排（Docker Compose + 两个前端镜像各自带 nginx + 自带 MySQL 镜像）
├── docs/ · scripts/ · tools/                # 文档 · 启动自检 · 一次性迁移
└── logs/ · build/ · backup/ · .workbuddy/   # 运行时产物与 AI 配置（非架构）
```

## 模块简介

| 模块 | 职责 | 详情 |
|---|---|---|
| `comic-core/` | **共用内核**：领域模型 · 路径常量 · 标签归一 · 日志上下文 · 存储契约+MySQL 实现 · 图库读写 | `comic-core/README.md` |
| `crawler-service/` | 采集源站 → 判重入库 → 图片懒转存 / 巡检；提供 CLI，并被 api-service **在进程内**调用 | `crawler-service/README.md` ｜ 各源见 `sources/<源名>/README.md` |
| `api-service/` | 对外 REST API + 管理台后台任务；图片读取与占位图 | `api-service/README.md` |
| `comic-web/` | 原 Web SPA；**约定与逻辑一律不动**，作移植参考 | `comic-web/README.md` |
| `comic-front/` | uni-app 版（当前主用）；业务逻辑忠实移植，靠 `src/utils/{router,storage,event}.ts` 兼容层保持平台无关 | `comic-front/README.md` |
| `docs/` | 总体架构 / 认证 / 部署 | `docs/README.md` |
| `deploy/` · `scripts/` · `tools/` | 生产编排 · 启动自检 · 一次性迁移 | 各自 README |

**跨模块边界**（细节见上表 README）
- **模块间依赖（红线）**：`api-service` 只允许 `from comic_crawler.facade import ...` —— 采集侧内部随便重构，只要契约面符号名 / 签名不变，api 零改动；**不得穿透到任何子模块**（由 `api-service/tests/test_crawler_boundary.py` 断言守卫）。改契约面签名 = 破坏性变更。
- **共用内核（单向依赖）**：`comic-core` 是采集端与接口端共同依赖的底层（模型 / 路径 / 存储 / 图库），**它不依赖 `comic_crawler`，也不依赖任何 HTTP 框架**。存储层无法走 HTTP（接口侧 28 处调用、且要保留批量语义），所以做成共享包而非接口 —— 见 `comic-core/README.md`。改 `comic-core` 等于同时改两端。
- **存储**：唯一 MySQL，本项目独占实例（宿主 `127.0.0.1:3309`）。连接参数：环境变量 → `deploy/.env` → 默认值。
- **运行时数据**：唯一真源 `comic_core.paths.DATA_ROOT`（图库 + 源开关状态）；容器把整个 `/data` bind 到同一宿主目录，本地直跑与 Docker 读写同一批文件。⚠️ 数据根**不随包位置走**：开发态固定为 `crawler-service/data`（`paths.py` 里显式判定，别改成「上溯两级」）。
- **判重**：只看 `(source, source_comic_id)`，同源幂等；**跨源不合并** —— 一行 = 一个收录源。
- **源站接入**：`sources/{name}/` 自包含；新增源见 `新增爬虫源` 技能。已接入 zaimanhua（主源）/ mangadex / weebcentral / copymanga。
- **管理台 / 按需导入**：逻辑在 `api-service/services/ondemand.py`；接口 `/api/admin/*`，前端 `/#/admin`（角色三档 + 两道门 `require_admin` / `require_superadmin`）。
- **前端上线形态**：Docker 下是**两个独立镜像** —— `comic-web:1.0.0`（网页端，宿主 85）/ `comic-front:1.0.0`（移动端，宿主 86），**各自带 nginx** 反代 `/api/*` 到 `comic-app:8000`；`comic-api` 是纯 API。两个镜像共用同一份站点配置（`deploy/{web,front}/nginx.conf` 必须逐字节一致）。见 `deploy/README.md`。

## 基础命令

- **分工**：本地开发 = **宿主直跑**（uvicorn + Vite）；上线 = **Docker Compose**（`deploy/`，见 `docs/deploy.md`）。
- **启动前**：Docker Desktop 在跑、`comic-mysql` Up（`docker ps`）—— 本地直连宿主 `127.0.0.1:3309`，无需手工导出环境变量。
- **后端**：`cd api-service && ../crawler-service/.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 >> ../logs/api.log 2>&1`
- **前端 · comic-web**：`cd comic-web && npm run dev`（:5173）
- **前端 · comic-front**：`cd comic-front && npm run dev:h5`（:5174）；构建 `build:h5` / `dev:mp-weixin`（详见其 README）
- **上线一键**：`bash deploy/up.sh`（**不带参数 = 两个入口都起**，网页端 85 + 移动端 86）/ `--web`（只起网页端）/ `--front`（只起移动端）。只重建某一层：`bash deploy/build.sh --web|--front`。
- **停止**：**按 PID 停**（起停细节见 `docs/deploy.md` §6）；**禁用 `taskkill /IM python.exe`**（会误伤同机其它 Python 服务）。

## 硬性约定

- **改完代码自动重启**：AI 协作**不必等用户提醒** —— 动过 `comic-core` / `crawler-service` / `api-service` 就重启 uvicorn，动过 `comic-web` / `comic-front` 就重启对应 Vite。⚠️ **`comic-core` / `crawler-service` 改完必须重启后端**：管理台任务在 api 进程内直接调 `comic_crawler`，而存储 / 图库 / 模型都在 `comic_core`，不重启就一直跑旧代码。
- **架构单职责 / 分层**：新增接口进 `api-service/routers/*`、业务逻辑进 `services/`（勿让 `main.py` 变胖）；`crawler-service` 保持 L0/L1/L2（通用外层 → 契约 → 可扩展内层），**L0 里的存储 / 模型 / 路径已上移到 `comic-core`**（外部依赖，不在采集侧分层守卫的断言范围内）。**新模块未归层会被分层守卫拦下**（`tests/test_layering.py`）。
- **文档归属**：本文件只放骨架与规矩；**参数细节、踩坑复盘写到对应模块 README 或 `docs/`**。
- **性能**：面向**大数据量**设计 —— 禁止逐条访问（「先拿一批 id 再取对象」用 `get_comic_tags_bulk` / `get_comics_by_ids` 这类一次性批量方法）、禁止代价随数据量线性增长的写法（N+1、无索引全表扫、每次调用新建连接）。改 SQL / 存储层时按此自查。
- **前端（comic-front）**：模板只用 uni 组件、CSS 只写类选择器、自定义组件禁止 `v-model`（多端适配的红线，详见其 README 开发约定）。
- **前端问题先实跑取证**：页面出现**请求报错 / 样式错位 / 交互失效**时，**不必等用户要求**，先用 playwright MCP 在真浏览器里跑一遍再下结论 —— 报错看 `browser_console_messages`、请求看 `browser_network_requests`（单条详情 `browser_network_request`）、DOM 看 `browser_snapshot`。**禁止只读代码就断言"应该是 XX 问题"**。**MCP 不可用时先自检再补**：**先检测 playwright MCP 是否存在**（查工具索引 `mcp__playwright__*` / 连接器列表，**不要只看某个固定配置文件** —— 同一 MCP 可能由用户级、项目级或其他 agent 的配置提供）；确认**不存在**才写入标准配置并安装，再**显式提示用户去连接器管理页 Trust**；**已存在**（只是工具不在索引）→ 配置没坏，直接提示重新 Trust。**不得静默降级成"读代码猜"**。配置与用法见 `comic-front/README.md`。
- **提交信息**：一律 Conventional Commits —— `<type>(<scope>): <中文主题>`。type 取 `feat` / `fix` / `refactor` / `perf` / `docs` / `chore` / `test` / `ci`；scope 取模块名（`crawler` / `api` / `web` / `db` / `deploy` / `tools`），跨模块或不限模块时可省。正文只写 2~3 行「改了什么、为什么」，不罗列文件 / 函数 / 实测数字。示例：`feat(crawler): 新增拷贝漫画源，失败日志带上漫画名`。
- **提交时机与粒度：原子拆分** **不在一轮改动做完就提交**；先攒着，等**多个需求都完成后**再**按主题拆成多个原子提交**（一个提交只做一件事，能单独看懂、单独回退）。提交前仍要查：无意外删除、无硬编码密钥。
