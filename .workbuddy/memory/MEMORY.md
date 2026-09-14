# 项目长期备忘（comic 聚合平台）

> 只放架构骨架 / 模块边界 / 常用命令。细节见各模块 README、`docs/` 或 `新增爬虫源` 技能。日志写 `.workbuddy/memory/YYYY-MM-DD.md`。

## 架构总览
三层服务 + 单一 MySQL（Docker 容器 `ruoyi-mysql` :3307）。文件层级：

```
comic/
├── crawler-service/                      # 采集 · 存储 · 图床（Python）
│   └── src/comic_crawler/
│       ├── models · config · http · fingerprint · paths · cli · taxonomy   # L0 通用内核
│       ├── sources/                      # 源站层：契约在外、各源在里
│       │   ├── base.py · registry.py          # L1 契约（CrawlerAdapter ABC）
│       │   └── zaimanhua/ mangadex/ weebcentral/   # L2 每源一个自包含子包
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
- **源站接入**：`sources/{name}/` 4 件套自包含；新增源详见 `新增爬虫源` 技能。已接入 zaimanhua（主源）/ mangadex / weebcentral。
- **存储**：唯一 MySQL；增量 = 时间窗口。
- **图库**：唯一 `images.store.default_store_root()`，引用只存相对 key。
- **按需导入 / 管理台**：逻辑集中 `api-service/services/ondemand.py`；管理台 `/api/admin/*`，前端 `/#/admin` 免登录。
- **标签**：写入侧归一（`taxonomy.py` + `data/tag_synonyms.json`），查询侧零翻译。

## 常用命令
- **启动前**：确认 Docker Desktop 运行、`ruoyi-mysql` Up（`docker ps`）。
- **后端**：`cd api-service && ../crawler-service/.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 >> ../logs/api.log 2>&1`
- **前端**：`cd comic-web && npm run dev`（:5173，HMR；开发不 build，发布才 `npm run build` → `comic-web/dist`）
- **停止**：TaskStop / Ctrl+C。禁用 `taskkill //IM python.exe`。
- **自检（提交前必跑）**：`scripts/check.sh` 或 `check.bat` = crawler 单测 + api 分层守卫 + `tsc --noEmit`。
- **crawler 单测**：`.venv/Scripts/python.exe -m unittest discover -s tests -v`（纯逻辑不连库）。

## 硬性约定
