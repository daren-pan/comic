# 上线部署（后端）

> 适用：把 `api-service` + `crawler-service` 部署到一台**服务器**上对外提供服务。
> 前端不用在这里处理 —— `comic-web` 构建出的 `dist/` 会被后端**同源托管**。

## 0. 先选一种方式

| 方式 | 怎么做 | 适合 | 章节 |
|---|---|---|---|
| **A. Docker Compose**（推荐） | `deploy/` 下已备好整套编排（mysql + app + nginx，采集可选），一条 `up -d --build`。数据库是**本项目独占**的实例 | 长期跑、以后会换机器 | §1 |
| **B. 直接在仓库里跑** | 服务器上 `git clone` → 装依赖 → 起 uvicorn（`core/config.py` 原生支持这种布局） | 和开发同一台机器 / 图省事 | §2 |
| **C. 打包成单个目录再传** | `scripts/package.sh` 产出 `build/deploy`（挑好的子集，不含 `.git`/测试/文档） | 目标机器没有仓库、只想传一个目录 | §3 |

**A 和 B 都不需要打包脚本** —— 打包只是"挑文件"，不挑就是整棵树都带。

## 1. 方式 A：Docker Compose（推荐）

**分层设计：每个模块一个文件夹，产物和它的 Dockerfile 放在一起** —— 打开 `deploy/` 一眼看全。

```
deploy/
├── web/        Dockerfile + dist/（前端构建产物）        → comic-web:1.0.0      只装 dist
├── crawler/    Dockerfile + dist/comic_crawler-*.whl    → comic-crawler:1.0.0  采集层（可单独当 CLI 镜像）
├── api/        Dockerfile + dist/comic_api-*.whl        → comic-api:1.0.0      接口层（FROM 采集层）
├── nginx/      Dockerfile + nginx.conf                  → comic-nginx:1.0.0    反代（配置烘进镜像）
├── mysql/      Dockerfile + sql/（建库脚本产物）        → comic-mysql:1.0.0   本项目独占的库（FROM mysql:8.0）
├── build.sh / build.bat                                 生成产物 + 按序构建这 5 个镜像
├── up.sh                                                **一键**：前端 build + 上面这些 + up -d + 自检
├── docker-compose.yml                                   编排：comic-mysql + comic-app + comic-nginx
└── .env.example                                         配置模板（`deploy/.env` 已 gitignore）
```

**数据库：本项目独占一个实例**（`comic-mysql` 容器，**MySQL 8.0**），不与别的系统共用 —— 库、账号、
权限、备份策略都独立（曾与别的系统共用过实例，出现过"别人的表建进我们库"这类问题，独立实例最省心）。

- **首次启动自动建表**：建库脚本烘在 `deploy/mysql` 镜像里，数据卷为空时自动执行 →
  10 张表直接建好，**不需要手工跑任何 SQL**；
- 版本选 8.0 而非 5.7：5.7 已于 2023-10 EOL（不再有安全更新）。8.0 默认认证插件是
  `caching_sha2_password`，PyMySQL 需要 `cryptography` —— 已在 crawler/api 的依赖里声明，
  构建镜像时自动装上，**无需改代码**；`my.cnf` 里显式锁了 `utf8mb4_general_ci`
  （8.0 默认是 `utf8mb4_0900_ai_ci`，不锁会出现"同库不同连接排序结果不同"）；
- **comic-app 走编排内网**连 `comic-mysql:3306`，不经过宿主端口；宿主端口 **3309** 仅给
  Navicat / IDEA 从本机连用（避开 3307 上其它系统）；
- 数据在 `mysql_data` 卷里，`down` 不删卷；备份 = `mysqldump` + 卷快照；
- ⚠️ `MYSQL_ROOT_PASSWORD` **只对新建的卷生效**：库已建好后再改它不会同步，
  要改得 `down -v` 重置卷（会清库）或进容器 `ALTER USER`。

**产物形态**（`dist/` 都不入库，每次由 `deploy/build.sh` 重新生成）：

| 模块 | 产物 | 怎么来的 |
|---|---|---|
| `crawler` / `api` | **wheel**（`*.whl`） | 各自的 `pyproject.toml`（= 那个模块的 pom.xml）经 `pip wheel` 构建 |
| `web` | `dist/` 静态文件 | `cd comic-web && npm run build` 后复制进来（前端不是 Python 包） |

wheel 里只有包本身与依赖声明：**测试、文档、样例夹具自动被排除**（例如 crawler 的
`sources/*/README.md`、`guazi/fixtures/*.html` 都不在包里），依赖清单也只写一份（`pyproject.toml`）。

```bash
# 一条命令干完下面四步（含前置检查与自检）：
./deploy/up.sh                  # 一键：前端 build + 镜像 build + 起服务 + 自检
#   ./deploy/up.sh --skip-web    前端没改 → 跳过 npm build（快很多）
#   ./deploy/up.sh --collect     额外起定时采集 comic-scheduler
#   ./deploy/up.sh --migrate     ★ 服务器上**已有旧库**时加上它（跑幂等迁移脚本，见 §5）

cp deploy/.env.example deploy/.env      # 至少改 MYSQL_ROOT_PASSWORD 与 COMIC_JWT_SECRET
cd comic-web && npm run build           # 前端产物（build.sh 会把它复制进 deploy/web/dist）
./deploy/build.sh                       # 构建 wheel/dists + 按序构建 5 个镜像（Windows: deploy\build.bat）
docker compose -f deploy/docker-compose.yml up -d
```

> `up.sh` 就是把这四步串起来的**幂等**一键脚本：前置检查 → 前端 build →
> `build.sh` → `up -d` → 自检（mysql healthy → 容器内 `/api/health` → 数据目录可写 →
> 对外入口 HTTP 码）。重复跑只是重新构建 + `up -d`，**不会清数据**。
>
> ⚠️ **老环境升级**（服务器上已经有漫画库）请用 `./deploy/up.sh --migrate`：
> 本次"跨源不再合并"改造去掉了 `comic.fingerprint` 的唯一约束（见 §5），
> 旧库若不带这个迁移，第二个源的同名作品会因 `Duplicate entry` 插不进去。

> 构建 wheel 需要一个带 `pip` 的 Python 3.10+（默认取 PATH 里的 `python3/python`，
> 找不到或那个解释器没有 pip 时**自动回落项目自带的 `crawler-service/.venv`**；
> 也可用 `PYTHON=/path/to/python` 显式指定）。
> 它会临时拉 `setuptools` 做构建隔离，首次构建需要网络。

**为什么镜像要按顺序建**：`api` 的 Dockerfile 会 `FROM comic-crawler:1.0.0` 并
`COPY --from=comic-web:1.0.0`，所以必须先有那两个镜像。顺序是 `web → crawler → api → nginx`，
`build.sh` 已经固定好；只在个别层改动时，也可以单独 `docker compose build comic-app`。

要点：

- **构造上下文就是模块文件夹本身**（`context: ./api`）—— 里面只有产物和 Dockerfile，
  不需要 `.dockerignore`，也不会把 `.git` / `.venv` / `node_modules` 送进构建；
- **wheel 装进 site-packages，相对路径推导随之失效** —— 所以镜像里显式给了三个环境变量：
  `COMIC_IMAGE_ROOT=/data/image_store`（图库根）、`COMIC_DIST_DIR=/app/comic-web/dist`（前端产物）、
  `COMIC_STATE_FILE=/data/source_state.json`（开关状态）。**这是 wheel 方案的固有代价**，
  也是为什么 `paths.py` 那套"从包位置向上推"在容器里不再作数；
- **接口层镜像从采集层继承**：Python 版本、依赖、非 root 用户（uid 10001）、`/data` 数据目录都在采集层里定义一次；
- **数据分两处**：`mysql_data` 卷 → 数据库（`down` 不删卷）；**图库与源开关状态在宿主目录**
  （bind 到容器 `/data`，默认 `../crawler-service/data`，可用 `COMIC_DATA_HOST` 改）——
  与本地直跑是**同一份**，见 §12。备份 = `mysqldump` + 那个数据目录；
- **容器名固定**为 `comic-app` / `comic-nginx`（+ `comic-scheduler`），宿主端口由 `.env` 的 `HTTP_PORT` 控制（默认 80，被占用就改）；
- **app 单进程**（不加 `--workers`），原因见 §8；
- **管理台 / 日志 / 授权页要管理员角色**（`/api/admin/*` 全挂鉴权）：管理台与日志要 `require_admin`
  （超管 + 普通管理员），**授权页要 `require_superadmin`（仅超管）** —— 分开是硬要求，
  否则被授权的普通管理员反手就能把超管降级。未登录 401、权限不足 403。
  全新库**首个注册用户自动成为超管**；老库升级跑 `up.sh --migrate`（`add_user_role.py` 会把**最早的特权用户**
  提升为超管，否则升级后没人能授权）。给他人授权用管理台「授权」页（`/#/admin/users`）；
- **定时采集是可选服务**，默认不启动：`docker compose -f deploy/docker-compose.yml --profile collect up -d`。
  ⚠️ 调度器读的是**代码里的** `SOURCES[].enabled`，**不读**管理台那个开关文件 ——
  在管理台关掉的源，调度器仍会采集；不想采就手动触发或改代码默认值；
- **采集层可单独用**（不经过接口层）：
  ```bash
  docker run --rm -e COMIC_MYSQL_HOST=... comic-crawler:1.0.0 python -m comic_crawler.cli run --source zaimanhua --limit 1
  ```
- **现有库升级**（不是全新初始化）时，新表/索引/去约束用 `tools/` 里的迁移脚本补。镜像里**不带**
  `tools/`（全新部署由 `mysql_schema.sql` 建全表，用不到它们），需要在容器里跑就把目录挂进去。
  四个都是**幂等**的，可以照抄（注意 `-f` 后面的路径按你的实际位置写）：
  ```bash
  cd deploy    # 相对挂载路径按 compose 文件所在目录解析，服务器与 Git Bash 都成立
  docker compose -f docker-compose.yml run --rm -v ../tools:/app/tools:ro comic-app python tools/add_log_table.py
  docker compose -f docker-compose.yml run --rm -v ../tools:/app/tools:ro comic-app python tools/add_perf_indexes.py
  docker compose -f docker-compose.yml run --rm -v ../tools:/app/tools:ro comic-app python tools/drop_fingerprint_unique.py
  docker compose -f docker-compose.yml run --rm -v ../tools:/app/tools:ro comic-app python tools/add_user_role.py
  ```
  懒得逐条敲就 **`bash deploy/up.sh --migrate`** —— 起完服务自动把上面四个跑一遍
  （见 §1 的 up.sh 用法）。

## 2. 方式 B：直接在仓库里跑（**本地开发用这个**）

> **分工**：本地开发就走这条路（宿主直跑，起得快、有热重载）；**上线走 §1 的 Docker Compose**。
> 本节同时说明了 `core/config.py` 的路径回落机制 —— 开发态的 `crawler-service/src` 是候选路径里的第一个，
> 所以仓库本身就是一个可运行形态。

`core/config.py` 的候选路径里，**开发态是第一个**（`crawler-service/src`），`DIST_DIR` 也会回落到
`comic-web/dist` —— 所以仓库本身就是一个可运行的部署形态：

```bash
pip install -r api-service/requirements.txt -r crawler-service/requirements.txt
cd comic-web && npm run build          # 前端产物（改过前端才需重跑）
cd api-service && python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

环境变量与建库同 §4 / §5。用 systemd 托管时指向仓库里的 venv 即可（`ExecStart=<venv>/bin/python -m uvicorn ...`，
`Restart=always`、`WorkingDirectory=<repo>/api-service`、`EnvironmentFile=` 放密钥）。

## 3. 方式 C：打包成单目录（可选）

```bash
cd comic-web && npm install && npm run build    # 先构建前端 → comic-web/dist
./scripts/package.sh                            # Windows: scripts\package.bat
# → build/deploy
```

**脚本全程不做任何删除**（纯覆盖）—— 输出目录往往就是运行目录，里面还住着图库与开关状态，
删目录有误伤风险。代价是"上一版有、这一版没有"的文件会留在输出目录里，所以脚本末尾会做
**遗留检查**把它们列出来（只报告、不删除）；重构改名/挪位置后尤其要看一眼。

目标目录可用参数指定：`./scripts/package.sh /path/to/out`。

产出布局（`<out>/`）：

| 路径 | 内容 |
|---|---|
| `main.py` · `core/` · `routers/` · `services/` · `schemas.py` · `serializers.py` | HTTP 服务（api-service 分层代码） |
| `src/comic_crawler/` | 采集服务包（适配器 / 存储 / 调度 / 词表数据 `data/`），**含非 py 资源** |
| `dist/` | 前端产物（同源托管） |
| `sql/mysql_schema.sql` | 建库脚本（10 张表，含 `log_record`） |
| `requirements.txt` | api + crawler 依赖**合并去重**（`sort -u` 生成） |
| `README-DEPLOY.md` | 一页运行说明（脚本自动生成） |

**为什么是 `src/comic_crawler/` 这层而不是直接放 `comic_crawler/`**：
`data` 目录（图库 + 源开关状态）的默认根由 `comic_crawler` 包位置推出来（向上两级）——
放 `src/` 下才能与开发态同构，运行时数据正好落在 `<out>/data/`。
`core/config.py` 里三个候选路径就是为这件事准备的（开发态 / 打包态两种）。

## 4. 环境变量（都有默认值 —— 上线必须改的见 §7）

| 变量 | 默认值 | 上线要求 |
|---|---|---|
| `COMIC_MYSQL_HOST` | `127.0.0.1` | 指向真实库 |
| `COMIC_MYSQL_PORT` | `3309` | 本项目独占实例的**宿主端口**（容器内走编排内网 `comic-mysql:3306`） |
| `COMIC_MYSQL_USER` | `root` | 建议建专用账号，不要 root |
| `COMIC_MYSQL_PASSWORD` | **（无默认值）** | 刻意不给弱默认：不配就**连接失败报错**，而不是静默连上一个"碰巧能用"的库 |
| `COMIC_MYSQL_DB` | `comic` | — |
| `COMIC_JWT_SECRET` | `comic-demo-secret-change-me` | ⚠️ **必须换强随机值**，否则 token 可被伪造 |
| `COMIC_IMAGE_ROOT` | 空（= `<out>/data/image_store`） | 指向**持久盘**，且**必须绝对路径** |
| `COMIC_TZ` | `Asia/Shanghai` | 容器时区（compose 用，app/scheduler/mysql 共用）。**别删**：镜像默认 UTC，而日志与 `sync_time` 都按本机时间写库 → 不设会让管理台日志时间早 8 小时。改完要 `up -d` 重建容器 |

两条确定性行为（不是猜测，代码里写死了）：

- **连接参数在模块导入时读取一次** —— 环境变量要在启动进程前设好，改了必须重启；
- `COMIC_IMAGE_ROOT` 若是**相对路径**或 `none`/`0`/`-` 这类哨兵值，会被**告警忽略**并回落到
  默认根 —— 这是刻意的防御（相对路径会随进程 cwd 漂移，导致"写端落了盘、读端只返回占位图"）。

## 5. 建库

**默认形态（§1 的 compose，自带 `comic-mysql`）不需要这一步** —— 数据卷为空时容器会自动执行
烘在镜像里的 `sql/mysql_schema.sql`，10 张表直接建好。只有**连外部 MySQL**（不推荐：会与别的系统共库、
权限与备份互相牵连）时才需要手工建一次：

```bash
# 在仓库里：
mysql -h <host> -P <port> -u root -p < crawler-service/sql/mysql_schema.sql
# 若用的是 §3 的发布包（包内有 sql/ 目录）：
#   mysql -h <host> -P <port> -u root -p < sql/mysql_schema.sql
```

> ⚠️ 手工这条路**只建表、不建库**：`mysql_schema.sql` 是纯 DDL，里面没有 `CREATE DATABASE`
> （设计上依赖"库由 `MYSQL_DATABASE` 创建并选中"）。若目标库还不存在，会直接报
> `ERROR 1049 Unknown database`，得先 `CREATE DATABASE comic DEFAULT CHARACTER SET utf8mb4` 再执行。

- 脚本是 `CREATE TABLE IF NOT EXISTS` + 带 `UNIQUE KEY`，**幂等可重跑**，且**不含任何 `DROP`**；
- 新库会自动带上 `log_record` 表、性能索引，且 `comic.fingerprint` 是**普通索引**；
  **已有库**（老环境升级）对应补四个脚本：`add_log_table.py`（补表）、`add_perf_indexes.py`（补索引）、
  **`drop_fingerprint_unique.py`（把 fingerprint 的唯一约束改成普通索引）**、
  **`add_user_role.py`（补 `user.role` 列，并在库里没有超管时把最早的特权用户提升为 `superadmin`；
  另支持 `--superadmin <用户名>` 转移超管身份）** ——
  第三个是"跨源不再合并"改造所必需：不去掉唯一约束，第二个源的同名作品会插不进去（`Duplicate entry`）；
  第四个是"管理台要鉴权"改造所必需：不补列 `require_admin` 读不到 `role`，会把**所有人**都当普通用户
  （谁也进不去管理台）。四个都可重跑、都写了回滚方式（⚠️ 第三个的回滚受限制：库内可能已有同指纹多行）；
- `scripts/init_mysql.sh` / `.bat` 是上面这条路的脚本化：同样幂等、同样**不含 `DROP`**（不会清空数据），
  额外先来一步 `CREATE DATABASE IF NOT EXISTS`（库不存在也一步到位），口令自动读 `deploy/.env`。

## 6. 起进程

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

**当前必须单进程（不要加 `--workers N`）**，原因在 §8。

生产常用的两种托管方式：

| 场景 | 做法 |
|---|---|
| Linux | `systemd` 托管 uvicorn（推荐）；若用 gunicorn，需**另装 `uvicorn-worker`** 包 —— `uvicorn.workers` 模块已弃用（装上会打 DeprecationWarning） |
| Windows 服务 | 用 `nssm` 把 `python -m uvicorn ...` 注册为服务（会话结束不被回收） |

> 顺带一提：本地开发时后台起的进程会在会话结束时被回收，服务化之后就稳定了。

## 7. 上线前必做（按风险排序）

| # | 事项 | 现状 | 要做什么 |
|---|---|---|---|
| 1 | ~~管理台接口没有鉴权~~ ✅ **已处理（2026-09-18）** | `routers/admin.py` 12 个接口挂 `require_admin`（超管 + 普通管理员）；`routers/admin_users.py` 2 个接口挂 `require_superadmin`（**仅超管**）—— 未登录 401 / 权限不足 403；前端 `/#/admin*` 三条路由有对应守卫 | 无。⚠️ 老库升级要跑 `up.sh --migrate` 补 `user.role` 列 |
| 2 | **JWT 密钥是演示值** | 默认 `comic-demo-secret-change-me` | 注入强随机 `COMIC_JWT_SECRET` |
| 3 | **CORS 全开** | `allow_origins=["*"]` | 同源部署本不需要 CORS，收敛为实际域名或直接关掉 |
| 4 | **数据库口令是默认值** | `root/password` | 改口令 + 建最小权限账号 |
| 5 | **图库要持久盘** | 默认落在发布包目录内 | 用 `COMIC_IMAGE_ROOT` 指向独立数据盘，并纳入备份 |
| 6 | **`log_record` 会持续增长** | 每次转存/巡检都写几行 | 已有 `POST /api/admin/logs/purge?days=N`，接一个每日定时任务 |
| 7 | **合规** | 见 `architecture.md` §6.2：本项目定位学习/演示，**不公开发布** | 对外服务前必须移除未授权内容、回归授权源站策略 |

## 8. 为什么现在不能多进程（重要）

API 进程里有两处**进程内状态**，多 worker 会直接出错：

| 位置 | 状态 | 多 worker 的后果 |
|---|---|---|
| `services/tasks.py` | `_TASKS` 是内存字典、`_SEQ` 是内存计数器 | **任务查不到**：`POST /api/admin/sync` 落在 worker A，前端轮询 `GET /api/admin/tasks/{id}` 可能落到 worker B → 404，任务永远显示"进行中" |
| `services/sources.py` | `_state` 是内存缓存（落盘文件 `source_state.json`） | **开关不同步**：在 A 关闭的源，B 仍按旧状态执行 |

`tasks.py` 的 docstring 自己也写着"任务表存在内存里（进程重启即清空），对演示用途足够；生产可换 Redis/DB"。

**要扩到多进程，先做这两件事**：任务表落库（新表或 Redis）、数据源开关每次读文件/库（或加缓存失效）。

另外两条与 worker 数无关但需要知道的：

- **调度循环不在 API 进程里**（`SyncScheduler` 只被 `crawler-service` 的 CLI `serve` 用），
  所以"多 worker 会不会重复采集"这件事**不存在**；
- 日志落库的 Handler 是**每个进程各挂一个**（各自一条后台线程 + 批量写），多 worker 下是 N 份并行写，不会串。

## 9. 定时采集

生产里"定时采集"有两条路，都是现成的：

```bash
# 一次性同步（适合 cron / 计划任务）
python -m comic_crawler.cli run --source zaimanhua

# 常驻调度（按间隔循环跑，自己内置循环）
python -m comic_crawler.cli serve
```

> 这两条命令跑的是 `crawler-service` 的 CLI；在发布包里对应 `<out>/src/comic_crawler`，
> 加 `PYTHONPATH=<out>/src` 即可。也可以**不部署调度**，只在管理台手动触发。

## 10. 实测记录（2026-09-15）

按 §1 的布局在临时目录复现了发布包并**实际启动**，验证路径不会漏回开发目录：

| 检查项 | 结果 |
|---|---|
| `/api/health` | ✅ `comics 92 / chapters 650 / pages 6437 / categories 61` |
| `/`（前端静态托管） | ✅ HTTP 200 |
| 新页面分包 `/assets/LogsView-*.js` | ✅ HTTP 200 |
| `/api/admin/logs`（查 `log_record`） | ✅ 正常返回 |
| `APP_DIR` / `DIST_DIR` | ✅ 全部解析到发布包内，**未回落开发目录** |
| `comic_crawler` 导入来源 | ✅ `<out>/src/comic_crawler` |
| 运行时数据根 | ✅ `<out>/data/`（图库 `data/image_store` + 状态 `data/source_state.json`） |

**Compose 方式（§1）也实测过**：`docker compose up -d` 起 `comic-mysql` + `comic-app` + `comic-nginx`
（数据库是**本项目独占**的 8.0 实例，app 走编排内网连 `comic-mysql:3306`），首页与 `/assets` 分包均 200，
`nginx -t` 通过。apk 无关的镜像构建走 `PIP_INDEX`（见 `deploy/build.sh` 注释）可换国内源。

> 唯一没验证的是"真实跑一遍 `scripts/package.sh`"—— 它有 `rm -rf build/deploy`，需要人工确认后执行（现已改为零删除，但历史上需确认）。

## 11. 数据迁移记录（2026-09-15：共用 3307 → 本项目独占实例）

原先与别的系统共用宿主 3307，3307 上的 `comic` 库已**整体迁入独占实例并删除**：

| 步骤 | 结果 |
|---|---|
| 导出 | `mysqldump --single-transaction --add-drop-table` → `backup/comic_3307_20260915_142703.sql(.gz)`（1.5 MB / 338 KB） |
| 导入独占实例 | 10 张表**逐表精确行数一致**：comic 92 / chapter 650 / page 6437 / comic_tag 400 / tag 61 / user 11 / favorite 8 / history 15 / log_record 9 / sync_log 43 |
| 备份可用性 | 把 dump 恢复到临时库比对（差异仅来自导出后的新写入，已逐条核实）→ **可完整回滚** ✅ |
| 端到端接口 | **35 项全过**（列表/分页/排序/关键字/分类/详情/章节/分页图/封面/源站搜索/注册登录/鉴权 401/收藏/历史/管理台）。<br>2026-09-18 追加「三档角色鉴权」验证：匿名 401；**普通管理员**管理台/日志/任务 200 但**授权页 403**；普通用户全 403；超管全 200；授权与取消授权**即时生效**（同一 token 403→200→403，无需重新登录）；改自己 400 / 授予 superadmin 400 / 动超管 400 / 不存在用户 404 |
| 采集服务 | 容器内 `cli list` / `cli show` 正常读新库（源站、中文、章节号均正确） |
| 本地开发 | **零配置**跑通（不设任何 `COMIC_MYSQL_*`，自动读 `deploy/.env` 连 `127.0.0.1:3309`） |
| 旧库处置 | `DROP DATABASE comic`；同实例上 `ry-cloud`(27) / `ry-config`(13) / `ry-flowable`(47) **未受影响** |
| 图库 | 宿主 `crawler-service/image_store`（6457 文件 / 3.3 G）灌入 `comic_app_data` 卷 → 取图接口返回真图，**4 张抽样逐字节（MD5）一致** |

⚠️ **两个容易漏的点**（本次实测抓到）：

1. **图库不在库里**：只迁 DB 会导致 `oss_url` 有值、接口却全返回占位图 —— 图库是独立的数据目录，
   必须一起迁（当时的做法：`tar -C <image_store> -cf - . | docker exec -i comic-app tar -C /data/image_store -xf -`；
   ⚠️ 现已改为 bind 共用同一份宿主目录，**不再需要"灌卷"这一步**，见 §12）。
2. **MySQL 8.0 的认证插件**：默认 `caching_sha2_password`，宿主机上的老客户端（如 MySQL 5.7 的 `mysql`
   命令）可能连不上；PyMySQL 侧需要 `cryptography`（已在依赖里，本地 venv 也要装一次）。

## 12. 运行时数据目录（图库 / 源开关状态）——本地与容器**共用同一份**

**问题**：图库此前在两条路上是**两个不同的根** —— 本地直跑用 `<repo>/crawler-service/image_store`，
容器用命名卷 `app_data`（`/data`）。于是同一台机器上有两份图库，本地转存的图容器读不到（反之亦然）；
源开关状态更是**已经不一致过**（一边 `mangadex` 开、一边关）。

**现在的约定**：运行时数据（图库 + 源开关状态）只有**一个宿主目录**，两条路都指向它。

```
宿主目录（默认 crawler-service/data，可用 COMIC_DATA_HOST 改）
├── image_store/         ← 容器内 /data/image_store ；本地直跑同一目录
└── source_state.json    ← 容器内 /data/source_state.json ；本地直跑同一文件
```

| 谁 | 怎么定位 |
|---|---|
| 本地直跑 | 代码默认值 `comic_crawler.paths.DATA_ROOT`（api 侧 `COMIC_STATE_FILE` 的默认值也复用它）→ **零配置** |
| 容器 | `- ${COMIC_DATA_HOST:-../crawler-service/data}:/data`（bind）＋ `COMIC_IMAGE_ROOT=/data/image_store`、`COMIC_STATE_FILE=/data/source_state.json` |

**上线要点**：

```bash
# 用仓库外的独立盘（别放仓库里：重新 clone / 部署会丢），并保证容器内 uid 10001 可写
sudo mkdir -p /srv/comic/data && sudo chown -R 10001:10001 /srv/comic/data
# 然后在 deploy/.env 里：COMIC_DATA_HOST=/srv/comic/data
```

**备份**：`mysqldump`（数据库）+ 这一个数据目录（图库与源开关状态）。不再需要"灌卷"这类同步动作。
