# 项目长期备忘（comic 聚合平台）

> 只放架构骨架 / 模块边界 / 常用命令 / 硬性约定。细节见各模块 README、`docs/` 或 `新增爬虫源` 技能。日志写 `.workbuddy/memory/YYYY-MM-DD.md`。
> **与仓库根 [`AGENTS.md`](../AGENTS.md) 保持同步**（那份给读代码的 AI / 新人看，本文件是 AI 协作助手自动加载的副本；**改任一份都要改另一份**）。

## 架构总览
三层服务 + 单一 MySQL（**本项目独占的 MySQL 8.0 实例**，Docker 容器 `comic-mysql`：宿主 `127.0.0.1:3309` / 编排内网 `comic-mysql:3306`）。文件层级：

```
comic/
├── crawler-service/                      # 采集 · 存储 · 图床（Python）
│   └── src/comic_crawler/
│       ├── models · config · http · fingerprint · paths · cli · taxonomy   # L0 通用内核
│       ├── sources/                      # 源站层：契约在外、各源在里
│       │   ├── base.py · registry.py          # L1 契约（CrawlerAdapter ABC）
│       │   └── zaimanhua/ mangadex/ weebcentral/ copymanga/   # L2 每源一个自包含子包
│       ├── storage/                      # L1 base.py + L2 mysql/
│       ├── images/                       # L1 store.py + L2 transfer.py
│       └── scheduling/                   # 采集 / 巡检调度
├── api-service/                          # 对外 API（FastAPI :8000）
│   ├── main.py                           # 仅装配：建 app → include_router → 托管 dist
│   ├── core/                             # config / db / security / responses（无业务）
│   ├── schemas.py · serializers.py       # 出参结构 + 序列化
│   ├── services/                         # images / tasks / sources / ondemand（业务）
│   └── routers/                          # public / auth / users / admin（HTTP 入口）
├── comic-web/                            # 前端（Vue3 + Vite :5173）
│   └── src/  App.vue · api/ · components/ · stores/ · views/ · router.ts · types.ts
├── docs/ · scripts/ · tools/             # 文档 · 启动自检脚本 · 一次性迁移
└── logs/ · build/ · backup/ · .workbuddy/   # 日志 · 打包产物 · 备份 · AI 配置（非架构）
```

## 模块边界
- **源站接入**：`sources/{name}/` 4 件套自包含；新增源详见 `新增爬虫源` 技能。已接入 zaimanhua（主源）/ mangadex / weebcentral / copymanga。
- **存储**：唯一 MySQL —— **本项目独占一个实例**（`comic-mysql`，8.0），不与别的系统共库；增量 = 时间窗口。连接参数取值顺序：环境变量 → `deploy/.env` → 默认值（本地开发免配，读的就是 compose 那份同一个文件）。
- **图库 / 运行时数据**：唯一真源 `comic_crawler.paths.DATA_ROOT`（= `<服务根>/data`，默认 `crawler-service/data`），
  里面是 `data/image_store`（图库，引用只存相对 key）与 `data/source_state.json`（管理台源开关状态）。
  **容器把整个 `/data` bind 到同一个宿主目录**，所以本地直跑与 Docker 读写的是同一批文件（不会出现两份图库互相看不见）。
- **按需导入 / 管理台**：逻辑集中 `api-service/services/ondemand.py`；管理台 `/api/admin/*`，前端 `/#/admin`。**角色三档**（未登录 401 / 权限不足 403，见 `docs/auth.md` §8）：`superadmin` 超管＝管理台+日志+**授权页**（**全库唯一**，库里没有任何特权用户时首个注册用户自动获得；转移用 `tools/add_user_role.py --superadmin <用户名>`）、`admin` 普通管理员＝管理台+日志但**进不了授权页**、`user` 默认无权限。两道门：管理台与日志 `require_admin`、授权页 `require_superadmin` —— 分开是硬要求，否则普通管理员能把超管降级。**全库维护只有「触发巡检」一个入口**（`inspect_sync`：转存未转存页 + 全表校验恢复，随后 `heal_covers` 封面自愈）；独立的「触发转存」入口 **2026-09-21 已删**（它是巡检第 1 步 `lazy_transfer` 的子集）。⚠️ **定时巡检不含封面自愈**（避免每小时打源站），只有管理台手动触发才做。
- **标签**：写入侧归一（`taxonomy.py` + `data/tag_synonyms.json`），查询侧零翻译。
- **日志落库**：业务日志由挂在 root 的 `MySQLLogHandler`（`storage/mysql/log_handler.py`）批量写 `log_record`（队列 + 50 条/2s 刷）。**三路来源**：通用字段（level/logger/message）、任务字段（`logctx` 的 `task_id`/`task_type`，`services/tasks._runner` 用 `bind_task` 绑到本线程，**ContextVar 不跨线程**）、业务字段（`extra={"log_fields": {...}}` 拍平成 `event/source/comic_id/endpoint/reason/…`）。两道门槛：logger 前缀白名单 `LOG_SOURCES` + 级别 `INFO_LOGGERS`。⚠️ 所以封面日志是**「真下载」的流水，不是封面状态快照** —— 文件已在本地时 `ensure_cover_local` 静默返回，一条都不写。同理，采集 / 普通自愈都**跳过「文件已存在」的封面**（**错图也照样跳过**）—— 要修「文件在、但内容错」的封面，用管理台「**封面自愈 · 指定作品**」（填名称/ID、可多个；`POST /api/admin/heal-covers` 传 `keyword`）走 `force=True` **强制回源重下覆盖**（`heal_covers` / `ensure_cover_local` 均已支持 `force`，筛选走 `Storage.find_comics`）。- **判重**：只看 `(source, source_comic_id)`（同源幂等）。**跨源不合并**（用户 2026-09-16 决策）：同一部作品在别的源收过就是**另一行**，各记各自章节进度 —— 不同翻译版本（繁简/中日英）进度往往不同，合并会丢信息。`comic.fingerprint` 只写不判重（"可能重复"的观测标记）。一行=一个收录源，所以章节归属由 `comic.source` 推导始终确定（`chapter` 表无 source 列）。详见 `docs/architecture.md` §2.3。

## 常用命令
- **分工**：**本地开发 = 宿主直跑**（uvicorn + Vite，快、有热重载，见下）；**上线 = Docker Compose**（`deploy/`，见 `docs/deploy.md`）。
- **启动前**：确认 Docker Desktop 运行、`comic-mysql` Up（`docker ps`）—— 本地开发直连宿主 `127.0.0.1:3309`，连接参数由 `deploy/.env` 兜底提供，无需手工导出环境变量。
- **后端**：`cd api-service && ../crawler-service/.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 >> ../logs/api.log 2>&1`
- **⚠️ 改完 `crawler-service` 代码必须重启后端**：管理台「采集 / 巡检 / 封面自愈」都在 **api 进程内**执行（`POST /api/admin/*` → 后台线程直接调 `comic_crawler`），进程不重启就一直跑**启动时加载的旧代码**。2026-09-20 踩过：api 进程 09-18 10:31 启动，而 `f207672`（封面地址改回原样）是当天 17:10 才提交 —— 采集落盘的地址仍是旧规则。**改完爬虫代码后，用管理台触发前先重启 uvicorn。**
- **前端**：`cd comic-web && npm run dev`（:5173，HMR；开发不 build，发布才 `npm run build` → `comic-web/dist`）。若本机 `npm` 起不来（如撞 WSL 黑名单），直接跑 `node ./node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173`。
- **停止**：TaskStop / Ctrl+C。禁用 `taskkill //IM python.exe`。
- **改完代码自动重启前后端（2026-09-21 用户要求）**：AI 协作时**不必等用户提醒** —— 动过 `crawler-service` / `api-service` 就自动重启 uvicorn，动过 `comic-web` 就自动重启 Vite。停止**按 PID**（`Get-NetTCPConnection -LocalPort 8000,5173 -State Listen` 拿 PID；**后端是父子两个 python 进程，两个都要停**），**禁用 `taskkill //IM python.exe`**（机器上还跑着 MCP 服务进程，按镜像名批量杀会误伤）。

## 硬性约定
- **架构单职责 / 分层**：新增接口进 `api-service/routers/*`、业务逻辑进 `services/`（勿让 `main.py` 重新变胖）；`crawler-service` 保持 L0/L1/L2（通用外层 → 契约 → 可扩展内层）。**新模块未归层会被分层守卫拦下**（`tests/test_layering.py`）。
- **性能**：面向**大数据量**访问设计，增 / 删 / 查 / 改都要走最优路径 —— 禁止逐条访问（「先拿一批 id 再取对象」必须用一次性批量方法，如 `get_comic_tags_bulk` / `get_comics_by_ids`）、禁止代价随数据量线性增长的写法（N+1、无索引全表扫、每次调用新建连接）。改 SQL / 存储层时按此自查。
- **提交信息**：一律 Conventional Commits —— `<type>(<scope>): <中文主题>`。type 取 `feat` / `fix` / `refactor` / `perf` / `docs` / `chore` / `test` / `ci`；scope 取模块名（`crawler` / `api` / `web` / `db` / `deploy` / `tools`），跨模块或不限模块时可省。正文只写 2~3 行「改了什么、为什么」，不罗列文件 / 函数 / 实测数字。示例：`feat(crawler): 新增拷贝漫画源，失败日志带上漫画名`。
- **提交时机与粒度：原子拆分** **不在一轮改动做完就提交**；先攒着，等**多个需求都完成后**再**按主题拆成多个原子提交**（一个提交只做一件事，能单独看懂、单独回退）。提交前仍要查：无意外删除、无硬编码密钥。
