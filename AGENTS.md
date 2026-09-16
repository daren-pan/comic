# AGENTS.md —— 项目约定（comic 聚合平台）

> **给读这个仓库的 AI / 新人看的第一份文件。**
> 内容与 [`.workbuddy/memory/MEMORY.md`](.workbuddy/memory/MEMORY.md) **保持同步**（那份是 AI 协作助手自动加载的副本；**改任一份都要改另一份**）。
> 只放架构骨架 / 模块边界 / 常用命令 / 硬性约定；细节见各模块 README、`docs/` 或 `新增爬虫源` 技能。
> 每日工作日志写 `.workbuddy/memory/YYYY-MM-DD.md`。

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
- **按需导入 / 管理台**：逻辑集中 `api-service/services/ondemand.py`；管理台 `/api/admin/*`，前端 `/#/admin` 免登录。
- **标签**：写入侧归一（`taxonomy.py` + `data/tag_synonyms.json`），查询侧零翻译。
- **源归属**：同一部作品只记**首个收录源**，不记录第二个源（章节归属由 `comic.source` 推导，`chapter` 表无 source 列）。详见 `docs/architecture.md` §2.3。

## 常用命令
- **分工**：**本地开发 = 宿主直跑**（uvicorn + Vite，快、有热重载，见下）；**上线 = Docker Compose**（`deploy/`，见 `docs/deploy.md`）。
- **启动前**：确认 Docker Desktop 运行、`comic-mysql` Up（`docker ps`）—— 本地开发直连宿主 `127.0.0.1:3309`，连接参数由 `deploy/.env` 兜底提供，无需手工导出环境变量。
- **后端**：`cd api-service && ../crawler-service/.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 >> ../logs/api.log 2>&1`
- **前端**：`cd comic-web && npm run dev`（:5173，HMR；开发不 build，发布才 `npm run build` → `comic-web/dist`）
- **停止**：TaskStop / Ctrl+C。禁用 `taskkill //IM python.exe`。
- **自检（提交前必跑）**：`scripts/check.sh` 或 `check.bat` = crawler 单测 + api 分层守卫 + `tsc --noEmit`。
- **crawler 单测**：`.venv/Scripts/python.exe -m unittest discover -s tests -v`（纯逻辑不连库）。

## 硬性约定
- **架构单职责 / 分层**：新增接口进 `api-service/routers/*`、业务逻辑进 `services/`（勿让 `main.py` 重新变胖）；`crawler-service` 保持 L0/L1/L2（通用外层 → 契约 → 可扩展内层）。**新模块未归层会被分层守卫拦下**（`tests/test_layering.py`）。
- **性能**：面向**大数据量**访问设计，增 / 删 / 查 / 改都要走最优路径 —— 禁止逐条访问（「先拿一批 id 再取对象」必须用一次性批量方法，如 `get_comic_tags_bulk` / `get_comics_by_ids`）、禁止代价随数据量线性增长的写法（N+1、无索引全表扫、每次调用新建连接）。改 SQL / 存储层时按此自查。
