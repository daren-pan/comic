# api-service（FastAPI）

对外 REST API（**纯 API**；前端产物由 `deploy/web`、`deploy/front` 两个带 nginx 的镜像各自发，
不再同源托管）；读取 crawler-service 落库的数据（唯一存储：MySQL）。
装配入口 `main.py` **只做三件事**：建 app → `include_router` → （有前端 dist 时才）挂载。
依赖采集层的方式只有两处，且**方向单向**：① `pyproject.toml` 的 `dependencies` 里 `comic-crawler>=1.0.0`；
② 代码里**只 import `comic_crawler.facade`**（采集侧对外契约面，见 `crawler-service/README.md`）——
由 `tests/test_crawler_boundary.py` 断言守卫，穿透到任何子模块都会红。

## 模块架构

```
api-service/
├── main.py            # 仅装配：建 app → include_router → 有 dist 才挂载（挂载必须在最后，避免 "/" 抢走 API 路由）
├── core/              # 基础设施（无业务）
│   ├── bootstrap.py   #   路径引导：把 crawler-service/src 注入 sys.path（**导入即生效**；wheel 态靠 pip 依赖，自然跳过）
│   ├── config.py      #   纯常量（无副作用）：项目根 / 前端 dist 目录（路径注入归 bootstrap，源开关状态归采集层）
│   ├── db.py          #   两个进程级单例：db（MySQLStorage）· users（MySQLUserStore）
│   ├── security.py    #   bcrypt · JWT · get_current_user / get_optional_user · 两道门
│   ├── pagination.py  #   分页归一 + 单页上限 MAX_PAGE_SIZE（**接口侧**约束，与存储实现无关）
│   └── responses.py   #   统一响应信封
├── schemas.py         # 请求体模型（入参**形状**边界）
├── serializers.py     # 领域对象 → 前端驼峰契约（**纯函数、不 import core.db**：tags 由调用方注入）
├── services/          # 业务动作（不绑定路由，可被 router / 后台任务复用）
│   ├── images.py      #   图片读取（魔数判型）+ SVG 占位图 + admin_image_store()
│   ├── tags.py        #   作品标签批量注入（一条 IN 查询，避免逐条查库）
│   ├── tasks.py       #   后台任务注册表（内存 + threading + 前端轮询）
│   ├── sources.py     #   数据源开关状态（source_state.json）与元信息
│   ├── ondemand.py    #   源站搜索 / 按需导入 / 读时登记页清单 / 穿透取图
│   ├── logs.py        #   运行日志查询（log_record）
│   └── accounts.py    #   授权页：用户列表 + 设置角色
└── routers/           # HTTP 入口（只做 入参解析 → 调用 → 包封响应）
    ├── public.py      #   健康 / 分类 / 作品 / 章节 / 封面 / 正文图（免登录）
    ├── auth.py        #   注册 / 登录 / 当前用户
    ├── users.py       #   收藏（需登录）/ 阅读历史（登录→账号、游客→匿名）
    ├── admin.py       #   采集管理台 + 日志查询（`require_admin`）
    └── admin_users.py #   授权页（`require_superadmin`，仅超管）
```

**响应格式**：成功统一 `{ code, message, data }`（`code: 0`）；失败走 `HTTPException` → `{"detail": "..."}`
（Pydantic 校验失败是 `{"detail": [{loc, msg}]}`，故**带中文提示的策略校验写在 router**）。
**入参边界**：`max_length` / `ge` / `Literal` 这类形状约束放 `schemas.py`（越界 → **422**）。

## 接口一览

| 端点 | 作用 |
|---|---|
| `GET /api/health` | 服务状态 + 库内统计（comics/chapters/pages/views） |
| `GET /api/categories` | 分类与作品数（含「全部」） |
| `GET /api/comics?category=&keyword=&sort=updated\|views\|favorites&page=&page_size=` | 作品列表：分类 / 关键词 / 排序 / 分页（`sort=views` = 按热度倒序，同分再按最近更新倒序；`sort=favorites` = 按收藏数倒序，同数再按热度、更新时间） |
| `GET /api/comics/{id}` | 作品详情（**浏览次数 +1 落库**后返回，`heat` 含本次访问） |
| `GET /api/comics/{id}/chapters` | 章节列表（`chapter_no` 升序；**不含页数**，原因见 crawler-service README） |
| `GET /api/chapters/{id}/pages` | 分页图片列表；库内还没有页清单时**现场登记一次**（首次打开这一话才产生） |
| `GET /api/covers/{id}` | 封面（真实文件优先，缺失生成 SVG）；`Cache-Control: max-age=3600` + `ETag`，占位图 `no-store` |
| `GET /api/images/{comic_id}/{chapter_id}/{page_no}` | 分页图**三级兜底**：本地图库 → **穿透源站取这一张并顺手落盘** → SVG 占位。命中图库时 7 天长缓存 |
| `GET /api/sources/search?q=&source=&limit=` | 搜索**源站**（只读不写库），按源分组；带 `inLibrary`/`comicId`，供前端显示「已收录」或「导入并阅读」。单源失败静默跳过 |
| `GET/PUT/DELETE /api/users/{user_id}/favorites[/{comic_id}]` | 收藏查询 / 添加 / 取消（`PUT` 幂等）；**需登录**，归属以 token 为准 |
| `GET/PUT /api/users/{user_id}/history` · `DELETE .../history/{comic_id}` | 阅读历史：查询 / 写进度 / 删除。归属：带 token → 账号 id，否则匿名 id；写入先校验章节属于该作品（不匹配 404） |
| `GET /api/admin/sources` · `POST /api/admin/sources/{name}/toggle` | 数据源列表（启用态 / 库内数 / 上次同步）/ 切换采集开关（持久化，重启不丢） |
| `POST /api/admin/sync` | 触发采集，body `{source, mode, since?, limit?}`（`since` **优先于同步水位**），返回 `taskId` |
| `POST /api/admin/inspect` | 触发**全库**失效巡检（全库维护的唯一入口），body `{source?, since?, until?}`。三步：转存未转存页 + **全表**校验已转存对象（缺失恢复）+ 全库封面自愈 |
| `POST /api/admin/import` | **按需导入单部作品**，body `{source, keyword?\|ref?\|source_comic_id?}`（三选一定位）。收录榜单之外的作品、全量收目录、**不下载正文图** |
| `POST /api/admin/heal-covers` | **按作品强制封面自愈**，body `{keyword, source?}`（`keyword` 必填 = 名称或 ID，可多个）。跳过「文件在即健康」判断，专治**「封面文件在但内容是错的」** |
| `GET /api/admin/tasks[/{task_id}]` | 后台任务状态轮询（running / done / failed + 结果统计） |
| `GET /api/admin/logs` | 运行日志查询（`log_record`）：级别 / 源站 / 事件 / 任务 / 作品 / 关键字 / 时间窗 + 分页 |
| `GET /api/admin/logs/{id}` · `/options` · `POST /logs/purge?days=` | 单条日志（含堆栈全文）· 筛选候选值 · 删除 N 天前的日志 |
| `GET /api/admin/users` · `POST /api/admin/users/{id}/role` | 授权页：用户列表（关键字 + 分页）· 设置角色（`admin` / `user`；**改自己会被拒**） |

## 基础命令

```bash
# 起服务（本文件自动把 crawler-service/src 加入 sys.path，无需设 PYTHONPATH）
cd api-service
../crawler-service/.venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

# 单测（纯逻辑：不连库、不起 HTTP）
../crawler-service/.venv/Scripts/python.exe -m unittest discover -s tests -t tests
```

- 站点 http://127.0.0.1:8000/ ；接口文档 http://127.0.0.1:8000/docs
- 上线用 Docker Compose（见 `../docs/deploy.md`）；**必须单进程**，原因见 `docs/deploy.md` §8。

## 约定

- **分层**：新增接口进 `routers/*`、业务逻辑进 `services/`、入参模型进 `schemas.py`、跨层工具进 `core/`。
  **不要让 `main.py` 重新变胖**；新模块未归层会被 `tests/test_layering.py` 拦下。
- **存储复用 crawler 的实现**：`MySQLStorage` / `MySQLUserStore` 由契约面 `comic_crawler.facade` 导出，取连接走
  **共享连接池**（crawler-service 的 `storage/mysql/_pool.py`，每进程一份、上限 20）。
  改 SQL 时按「面向大数据量」自查：批量取对象用 `get_comics_by_ids` / `get_comic_tags_bulk`，禁止 N+1。
- **鉴权两道门**：管理台与日志挂 `require_admin`（超管 + 普通管理员），授权页挂 `require_superadmin`（**仅超管**）
  —— 未登录 401 / 权限不足 403；**角色不写进 token**（每请求查库，改完立刻生效）。详见 `docs/auth.md` §8。
- **收藏 vs 历史两套身份口径**：收藏必须登录、一律以 token 的 `user.id` 为准；历史对游客开放（带 token 时归属账号）。
  详见 `docs/auth.md` §9。
- **热度不落库**：公式 `1000 + 浏览×1 + 收藏×2`，权重唯一定义在采集侧 `storage/mysql/_util`（`HEAT_*` + `heat_sql()`）；
  库里只存真实计数。⚠️ 统计收藏数用 `COUNT(DISTINCT f.user_id)`，**不能用 `f.id`**。
- **图片**：DB 只存图库内相对 key；响应带缓存头（封面 1 小时 + `ETag`、正文页 7 天、**占位图 `no-store`**）；
  穿透取图的三道约束（并发 / 去重 / 负缓存）见 `crawler-service/README.md`。
  **决策与协议分离**：`services/images.py` 只算「给哪份字节 + 什么缓存头」，返回框架无关的 `ImagePayload`；
  组装 `Response` / 判 `304` 是 `routers/public.py` 的事 —— 故 services 层不出现任何 FastAPI 类型。
- **管理台后台任务**：路由只做**入参解析 + 派发**，任务体在 `services/admin_jobs.py`（同步 / 巡检 / 导入 / 封面自愈），
  都是**长任务**，用 `services/tasks.py` 的 `threading.Thread` + 内存任务表执行，
  触发后立即返回 `taskId`，前端轮询取结果。⚠️ **任务表在内存里 → 不能多进程**（见 `docs/deploy.md` §8）；
  ⚠️ 这些任务在 **api 进程内**直接调 `comic_crawler`，**改完 crawler-service 必须重启后端**。
- **测试纯逻辑**：不连库、不起 HTTP；需要存储时把 `core.db` 换成假存储。
  ⚠️ **假存储只有一份**（`tests/_stub_db.py`），用它的测试文件必须在**导入应用模块之前**调 `install_stub()`
  —— 所有测试跑在同一进程里，两份桩会互相污染。

---

> 修复过程与验证记录写在 `.workbuddy/memory/YYYY-MM-DD.md`，不进本文件。
