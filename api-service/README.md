# api-service HTTP API 服务（FastAPI）

漫画聚合平台的**业务服务层**（架构方案 §4「网关 + 微服务」的落地示例）：
读取采集服务（crawler-service）落库的数据（唯一存储：MySQL），对外暴露 RESTful 接口，并**同源托管前端构建产物**。

## 运行

```bash
# 依赖（复用 crawler-service 的 Python venv）
python -m pip install -r requirements.txt

# 前置：先构建前端（仓库不带 dist，clone 后请先 cd comic-web && npm install && npm run build）
#       本机 MySQL 需可用（默认 127.0.0.1:3307 / root / password，连接参数见 crawler-service/README.md「存储」），
#       仓库不带数据文件，请先在 crawler-service 目录执行 cli run 采集入库
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

启动后：
- **API 文档**：http://127.0.0.1:8000/docs （FastAPI 自动生成 Swagger）
- **站点**：http://127.0.0.1:8000/ （前端 dist，底部标注"已连接采集服务"）

## 代码结构（分层，2026-09-11 拆分）

`main.py` 只做**应用装配**（建 app → 挂路由 → 托管静态产物），其余按层归位：

```
api-service/
├── main.py             # 装配入口：FastAPI 实例 + CORS + include_router + 静态托管
├── core/               # 基础设施层（无业务逻辑）
│   ├── config.py       #   路径常量 + sys.path 引导（必须最先导入）
│   ├── db.py           #   存储句柄单例：db（漫画侧）/ users（用户中心）
│   ├── security.py     #   认证：bcrypt + JWT + get_current_user 依赖
│   └── responses.py    #   统一响应 ok() = {code, message, data}
├── schemas.py          # 请求体模型（Pydantic）
├── serializers.py      # 领域对象 → 前端驼峰契约（to_comic/to_chapter/to_page/user_out）
├── services/           # 业务动作层（不绑定路由，可被 router / 任务复用）
│   ├── images.py       #   图片读取（魔数判型）+ SVG 占位图 + admin_image_store()
│   ├── tasks.py        #   后台任务注册表（采集/转存走线程 + 轮询）
│   └── sources.py      #   数据源开关状态（source_state.json）与元信息
└── routers/            # HTTP 接口层（只做 入参解析 → 调用 → 包封响应）
    ├── public.py       #   健康/分类/作品/章节/封面/正文图（免登录）
    ├── auth.py         #   注册/登录/当前用户
    ├── users.py        #   收藏（需登录）/ 阅读历史（匿名 userId）
    └── admin.py        #   采集管理台（免登录，运维用）
```

> 新增接口：写进对应域的 `routers/*.py`；逻辑放 `services/`；入参模型放 `schemas.py`；
> 跨层工具放 `core/`。**不要让 `main.py` 重新变胖。**

## 接口一览（统一响应格式 `{ code, message, data }`）

| 端点 | 说明 | 对应架构方案 |
|---|---|---|
| `GET /api/health` | 服务状态 + 库内统计（comics/chapters/pages/views） | 网关健康检查 |
| `GET /api/categories` | 分类与作品数（含"全部"） | 浏览服务 |
| `GET /api/comics?category=&keyword=&sort=updated\|views&page=&page_size=` | 作品列表：分类/关键词/排序/分页（`sort=views` = 按热度倒序，**同分再按最近更新时间倒序**） | `GET /api/comics` |
| `GET /api/comics/{id}` | 作品详情（**浏览次数 +1 落库**后返回，返回的 `heat` 含本次访问） | `GET /api/comics/{id}` |
| `GET /api/comics/{id}/chapters` | 章节列表（orderNo 升序 + 页数） | `GET /api/comics/{id}/chapters` |
| `GET /api/chapters/{id}/pages` | 分页图片（返回本服务图片 URL） | `GET /api/chapters/{id}/pages` |
| `GET /api/covers/{id}` | 封面（真实文件优先，缺失生成 SVG） | 图片服务 |
| `GET /api/images/{comic_id}/{chapter_id}/{page_no}` | 分页图（OSS 文件优先，缺失生成 SVG 占位） | 图片服务 |
| `GET/PUT/DELETE /api/users/{user_id}/favorites[/{comic_id}]` | 收藏查询/添加/取消（`PUT` 幂等） | 用户中心 |
| `GET/PUT /api/users/{user_id}/history` · `DELETE /api/users/{user_id}/history/{comic_id}` | 阅读历史：查询（含作品+章节信息）/写入进度/删除 | 用户中心 |
| `GET /api/admin/sources` · `POST /api/admin/sources/{name}/toggle` | 数据源列表（enabled/库内数/上次同步）/ 开关采集（持久化 `source_state.json`） | 采集管理控制台 |
| `POST /api/admin/sync` | 手动触发采集，body `{source, mode, since, limit}`，返回 `taskId`（后台线程执行） | 采集管理控制台 |
| `POST /api/admin/transfer` | 手动触发懒转存，body `{source, since, until, limit?}`（`limit` 留空=窗口内全部），返回 `taskId` | 采集管理控制台 |
| `POST /api/admin/inspect` | 手动触发**全库**失效巡检，body `{source?, since, until}`（`source` 可选，管理台不传 = 全库），返回 `taskId` | 采集管理控制台 |
| `GET /api/admin/tasks[/{task_id}]` | 后台任务状态轮询（running/done/failed + 结果统计） | 采集管理控制台 |

> 匿名用户模型：前端首次访问生成 `userId`（localStorage 持久化），收藏与历史按用户隔离；
> 服务端历史支持**跨浏览器续读**（换设备/浏览器登录同一 userId 即可继续上次阅读）。

## 关键设计

- **热度（`heat`）为实时计算，不落库**：公式 `1000（起底） + 浏览次数×1 + 收藏数×2`，
  权重唯一定义在 `comic_crawler.storage.mysql`（`_util.py`）（`HEAT_BASE` / `HEAT_PER_VIEW` /
  `HEAT_PER_FAVORITE` + `heat_sql()`）。库里只存真实计数 `comic.views` 与 `favorite` 关系，
  因此**调整权重无需回填历史数据**，收藏/取消也天然即时反映。详情端点每次访问
  `UPDATE comic SET views = views + 1`（落库，进程重启不丢）。⚠️ 统计收藏数用
  `COUNT(DISTINCT f.user_id)`（`favorite` 一行 = 一对用户/漫画；`f.id` 是自增代理主键，
  按它计数会把同一部漫画的多条收藏算成多个）。
- **复用 Storage 抽象**：`main.py` 自动把 `crawler-service/src` 加入 `sys.path`，
  使用 `MySQLStorage` 的只读查询（`list_comics/get_comic/get_chapters/get_pages`），
  与采集服务共用一套存储接口（`Storage` 抽象作为契约）；
- **同源部署**：`app.mount("/", StaticFiles(comic-web/dist))`，前端与 API 同一端口，
  无 CORS / 代理问题；开发模式前端走 Vite proxy（见 comic-web/vite.config.ts）。
  注意：`comic-web/dist` **不随仓库分发**，clone 后需先构建前端，否则 `/` 无内容；
- **图片回退链**：已转存 OSS 文件（真实图片字节）→ 本地生成 SVG 占位图。
  接真实源站后转存文件即为真实漫画图，占位逻辑自动失效；
- **视图计数**：内存计数器（演示版），生产换 Redis 计数器。

## 采集管理控制台（`/api/admin/*`）

面向本机运维的采集控制台（前端 `/#/admin`，无需登录）。采集/懒转存耗时，故用**后台线程执行 + 前端轮询**（`_run_admin_task`），触发后立即返回 `taskId`，再轮询 `GET /api/admin/tasks/{id}` 取结果。

- **按源开关**：`POST /api/admin/sources/{name}/toggle` 切换某源采集启用状态，持久化到 `api-service/source_state.json`（默认读 `config.SOURCES.enabled`）；关闭的源拒绝触发采集（400）。
- **触发采集**：`POST /api/admin/sync`，`since`（ISO，起始日期）**优先于上次同步水位**——留空按水位、填了按填的日期回补/前移；`limit` 限制本次收录数量（受控样本）。
- **触发懒转存**：`POST /api/admin/transfer`，`source` 只转存指定源、`since/until` 按章节 `sync_time`（DATETIME）窗口过滤——**语义是把窗口内所有未转存页全部转存**；边界**双端含**（`until` 只给日期时**含当天全天**）；`limit` 为可选兜底阀门（留空/≤0 = 不限制）。**转存完成后自动附带封面自愈**（无需单独按钮，见下）。
- **触发失效巡检**：`POST /api/admin/inspect`，body `{source, since, until}`。与「转存」的区别：转存只做「未转存 → 转存」；巡检在此基础上**再多做一步「已转存对象校验 + 丢失恢复」**，因此能发现图库文件被误删/写错目录的情况。校验按 `id` **键集分页遍历全表**（每次 1000 条 + 游标推进，**不会被固定条数截断**），`source` 同时限定校验范围；结果摘要为 `校验 N | 转存 N | 恢复 N | 失效 N`。**管理台只提供「全库」一个入口**（页面顶部一块面板，不随源卡片复制）；`source` 是可选参数，供 CLI / 脚本做单源巡检。
- **封面自愈（自动）**：转存任务内接着跑 `scheduling.heal.heal_covers` —— 外链未落盘的封面重下落盘；本地 key 但图库文件缺失的按 `source_comic_id` 回源重抓 `cover_url` 再落盘；结果并入转存任务 `result.coverHeal`。
- 数据层支撑（crawler-service）：`incremental_sync/full_sync` 增加 `since` 参数；`lazy_transfer`/`list_uncached_pages` 增加 `source` 按源过滤；新增 `heal_covers` 封面自愈。

> 采集任务结果以 `{stats, summary, db}` 存入 `result`；转存任务为 `{checked, transferred, failed, pagesByStatus, coverHeal}`（`coverHeal` = `{checked, healed, failed, skipped}`）。

## 数据流闭环

```
crawler-service（采集/去重/入库）→ MySQL → api-service（RESTful API）
                                                     ↓ 同源
                                    comic-web（前端 dist，读 /api 真实数据；dist 不随仓库分发）
```

在 `crawler-service` 目录执行 `cli run` 后，刷新前端即可看到新入库内容 ——
这就是架构方案「源站一更新，本站几分钟内可见」的最小闭环。

已接入真实源站（需联网采集，见 crawler-service/README.md）：**再漫画 zaimanhua（主源，H5 通道，
学习用受控样本）**、**MangaDex（v5 API，学习用受控样本，config 中 `enabled=False`，
仅手动 `run --source mangadex`）**、**WeebCentral（学习用受控样本）**。图片经懒转存后，
`/api/covers/{id}`、`/api/images/{cid}/{chid}/{pno}` 即返回**真实图片字节**（非 SVG 占位）。
