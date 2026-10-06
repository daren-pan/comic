# 上线部署（后端）

> 适用：把 `api-service` + `crawler-service` + 两个前端部署到一台**服务器**上对外提供服务。
> 后端是**纯 API**（`/api/*` + `/docs`）；两个前端各自一个镜像、各自带 nginx，端口分开（默认 85 / 86）。

## 0. 先选一种方式

| 方式 | 怎么做 | 适合 | 章节 |
|---|---|---|---|
| **A. Docker Compose**（推荐） | `deploy/` 下已备好整套编排（mysql + app + 两个前端入口，采集可选），一条 `up -d`。数据库是**本项目独占**的实例 | 长期跑、以后会换机器 | §1 |
| **B. 直接在仓库里跑** | 服务器上 `git clone` → 装依赖 → 起 uvicorn（`core/config.py` 原生支持这种布局） | 和开发同一台机器 / 图省事 | §2 |
| **C. 打包成单个目录再传** | `scripts/package.sh` 产出 `build/deploy`（挑好的子集，不含 `.git`/测试/文档） | 目标机器没有仓库、只想传一个目录 | §3 |

**A 和 B 都不需要打包脚本** —— 打包只是"挑文件"，不挑就是整棵树都带。

## 1. 方式 A：Docker Compose（推荐）

**分层设计：每个模块一个文件夹，产物和它的 Dockerfile 放在一起** —— 打开 `deploy/` 一眼看全。

```
deploy/
├── web/        Dockerfile + nginx.conf + dist/（网页端产物）  → comic-web:1.0.0    自带 nginx，宿主 85
├── front/      Dockerfile + nginx.conf + dist/（移动端产物）  → comic-front:1.0.0  自带 nginx，宿主 86
├── core/       dist/comic_core-*.whl                          → **无镜像**（纯库，只作命名构建上下文 `core`）
├── crawler/    Dockerfile + dist/comic_crawler-*.whl          → comic-crawler:1.0.0  采集层（可单独当 CLI 镜像）
├── api/        Dockerfile + dist/comic_api-*.whl              → comic-api:1.0.0      接口层（依赖 core + crawler 的 wheel，**纯 API**）
├── mysql/      Dockerfile + sql/（建库脚本产物）              → comic-mysql:1.0.0    本项目独占的库（FROM mysql:8.0）
├── build.sh / build.bat                                       生成产物 + 按序构建这些镜像
├── up.sh                                                      **一键**：前端 build（默认两个入口，可 --web/--front 选）+ 上面这些 + up -d + 自检
├── docker-compose.yml                                         编排：comic-mysql + comic-app + comic-web / comic-front
└── .env.example                                               配置模板（`deploy/.env` 已 gitignore）
```

**两个前端入口各自一个镜像、各自带 nginx**（静态产物 + 反代在同一个容器里）：

| 入口 | 镜像 | 产物来源 | 宿主端口 |
|---|---|---|---|
| 网页端 | `comic-web:1.0.0` | `comic-web/dist`（Vue3 SPA，已冻结、只作参考实现） | `WEB_PORT`（默认 85） |
| 移动端 | `comic-front:1.0.0` | `comic-front/dist/build/h5`（uni-app H5，**当前主用**） | `FRONT_PORT`（默认 86） |

- **两个可以同时跑**，互不影响；只想开一个就把服务名写在 `up -d` 后面
  （`docker compose -f deploy/docker-compose.yml up -d comic-front`），依赖链会自动带上 `comic-app` 与 `comic-mysql`。
- **共用同一份 nginx 站点配置**：`deploy/web/nginx.conf` 与 `deploy/front/nginx.conf` 必须**逐字节一致**
  （Docker 构建上下文不能跨目录 `COPY`，只能各放一份）。`build.sh` / `build.bat` 构建前会校验，不一致直接报错。
- 分流规则：`location ~ ^/(api/|docs|redoc|openapi\.json)` 反代到 `comic-app:8000`，其余本地静态文件。
  两个前端都是 **hash 路由 + 相对 base**，不需要 history 回退，末尾 `try_files` 纯容错。
- **后端是纯 API**：`main.py` 的静态挂载有 `if DIST_DIR.is_dir()` 守卫，容器里没有前端目录就自然退化，
  后端代码一行没改。

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
| `web` | `dist/` 静态文件 | `cd comic-web && npm run build` 后复制进来（前端不是 Python 包）；来源可用 `WEB_SRC=<目录>` 覆盖 |
| `front` | `dist/` 静态文件 | `cd comic-front && npm run build:h5` 后复制进来；来源可用 `FRONT_SRC=<目录>` 覆盖 |

wheel 里只有包本身与依赖声明：**测试、文档、样例夹具自动被排除**（例如 crawler 的
`sources/*/README.md`、`guazi/fixtures/*.html` 都不在包里），依赖清单也只写一份（`pyproject.toml`）。

```bash
# 一条命令干完下面几步（含代码更新、前置检查与自检）：
./deploy/up.sh                  # 一键：git pull + 前端 build + 镜像 build + 起服务 + 自检
#   ./deploy/up.sh --web         只起网页端（comic-web，宿主 85）
#   ./deploy/up.sh --front       只起移动端（comic-front，宿主 86）
#   ./deploy/up.sh --skip-web    前端没改 → 跳过 npm build（快很多）
#   ./deploy/up.sh --skip-pull   不更新代码 → 直接按当前工作区构建
#   ./deploy/up.sh --collect     【已废弃】定时执行器 comic-scheduler 现在默认启动（加了只是兼容旧脚本）
#   ./deploy/up.sh --migrate     ★ 服务器上**已有旧库**时加上它（跑幂等迁移脚本，见 §5）

cp deploy/.env.example deploy/.env      # 至少改 MYSQL_ROOT_PASSWORD 与 COMIC_JWT_SECRET
./deploy/build.sh                       # 构建 wheel/dist + 按序构建镜像（Windows: deploy\build.bat）
docker compose -f deploy/docker-compose.yml up -d
```

> 前端选择：**不带参数 = 两个入口都起**；带 `--web` / `--front` 就是只起选中的那个
> （两个都给也等价于不带参数）。
>
> **只重建某一个前端**：`./deploy/build.sh --web` / `--front`（不带参数 = 两个都构建）。
> `up.sh` 会把所选前端交给 `build.sh` 的 `--web` / `--front`，并用 `WEB_SRC` / `FRONT_SRC` 指产物目录。
> `build.sh` 复制前会清空目标目录，所以不会出现两套 hash 产物混在一起。

> `up.sh` 就是把这几步串起来的**幂等**一键脚本：**`git pull` 更新代码** → 前置检查 → 所选前端 build →
> `build.sh` → `up -d <所选入口>` → 自检（mysql healthy → 容器内 `/api/health` → 数据目录可写 →
> 各入口 HTTP 码 + 前端身份）。重复跑只是更新代码 + 重新构建 + `up -d`，**不会清数据**。
>
> ⚠️ 开头的 `git pull` 只做**快进**（`--ff-only`），并把「更新了哪几条提交」打出来；
> 不是 git 工作区（方式 C 的发布包）/ 断网 / 本地有冲突时不中止，**按当前工作区继续构建**，
> 所以看到那几条 `⚠️` 就要留意：它意味着这次可能不是最新代码。想跳过更新用 `--skip-pull`。
> 顺带：若本次更新动了 `deploy/up.sh` 或 `build.sh` 本身，脚本会提示「再跑一次」——
> 当前进程跑的仍是旧脚本。
>
> ⚠️ **老环境升级**（服务器上已经有漫画库）请用 `./deploy/up.sh --migrate`：
> 本次"跨源不再合并"改造去掉了 `comic.fingerprint` 的唯一约束（见 §5），
> 旧库若不带这个迁移，第二个源的同名作品会因 `Duplicate entry` 插不进去。

> 构建 wheel 需要一个带 `pip` 的 Python 3.10+（默认取 PATH 里的 `python3/python`，
> 找不到或那个解释器没有 pip 时**自动回落项目自带的 `crawler-service/.venv`**；
> 也可用 `PYTHON=/path/to/python` 显式指定）。
> 它会临时拉 `setuptools` 做构建隔离，首次构建需要网络。

**模块之间没有镜像依赖**：`api` 不再 `FROM comic-crawler:1.0.0`，而是在 `api-service/pyproject.toml`
的 `dependencies` 里声明 `comic-core>=1.0.0` 与 `comic-crawler>=1.0.0`（**方向单向：api → crawler → core**），
构建时 pip 按这些声明解析安装；上游两层的 **wheel 产物**经 BuildKit 命名上下文 `core` / `crawler`
喂进 api 的构建上下文（`build.sh` 的 `--build-context`、compose 的 `additional_contexts`）。
**`scheduler` 层同理**（`comic-scheduler/pyproject.toml` 声明同样两个上游），与 `api` 平级而非衍生。
所以**不必先有 crawler 镜像**，只要那两个 wheel 已生成（步骤 1 已保证）；顺序
`mysql → web → crawler → api → scheduler → front` 仍固定在 `build.sh` 里。⚠️ `core` 上下文**三个消费方都要挂**
（crawler / api / scheduler 层）—— 漏了它 pip 会去 PyPI 找 `comic-core`（并不存在，实测 404）而直接报错。
顺序里放哪都行。两个前端镜像**反向不依赖后端**（nginx.conf 里的 `upstream comic-app:8000` 构建期不解析、
运行期才需要）。只在个别层改动时，也可以单独 `docker compose build comic-app`。

要点：

- **构造上下文就是模块文件夹本身**（`context: ./api`）—— 里面只有产物和 Dockerfile，
  不需要 `.dockerignore`，也不会把 `.git` / `.venv` / `node_modules` 送进构建；
- **wheel 装进 site-packages，相对路径推导随之失效** —— 所以镜像里显式给了环境变量：
  `COMIC_IMAGE_ROOT=/data/image_store`（图库根）、`COMIC_STATE_FILE=/data/source_state.json`（开关状态）。
  **这是 wheel 方案的固有代价**，也是为什么 `paths.py` 那套"从包位置向上推"在容器里不再作数
  （前端产物不再烘进后端镜像，`COMIC_DIST_DIR` 已随之删除）；
- **接口层与采集层只靠依赖声明相连**：Python 版本、基础镜像、非 root 用户（uid 10001）、`/data`
  数据目录在**各自的 Dockerfile** 里定义（两边都写一遍，换来的是两个模块可以独立构建）；
  `comic_crawler` 在容器里来自 pip 装的依赖（site-packages），`core/config.py` 那套相对路径候选
  在 wheel 态自然全部落空、直接可导入；
- **数据分两处**：`mysql_data` 卷 → 数据库（`down` 不删卷）；**图库与源开关状态在宿主目录**
  （bind 到容器 `/data`，默认 `../crawler-service/data`，可用 `COMIC_DATA_HOST` 改）——
  与本地直跑是**同一份**，见 §12。备份 = `mysqldump` + 那个数据目录；
- **容器名固定**为 `comic-app` / `comic-web` / `comic-front`（+ `comic-scheduler`），两个前端入口的宿主端口由 `.env` 的 `WEB_PORT`（默认 85）/ `FRONT_PORT`（默认 86）控制；
- **app 单进程**（不加 `--workers`），原因见 §8；
- **管理台 / 日志 / 授权页要管理员角色**（`/api/admin/*` 全挂鉴权）：管理台与日志要 `require_admin`
  （超管 + 普通管理员），**授权页要 `require_superadmin`（仅超管）** —— 分开是硬要求，
  否则被授权的普通管理员反手就能把超管降级。未登录 401、权限不足 403。
  全新库**首个注册用户自动成为超管**；老库升级跑 `up.sh --migrate`（`add_user_role.py` 会把**最早的特权用户**
  提升为超管，否则升级后没人能授权）。给他人授权用管理台「授权」页
  （comic-web 是 `/#/admin/users`，comic-front 是 `/#/pages/admin/users`）；
- **定时采集：一条路，两个进程**。管理台「定时任务」栏是**唯一的配置入口**，真正跑采集的是
  **独立服务 `comic-scheduler`**（2026-10-06 从 api 进程里搬出来，**默认随栈启动**，不再藏在
  `--profile collect` 后面）：
  1. 页面（`comic-front` 的 `/#/pages/admin/schedule`、`comic-web` 的 `/#/admin/schedule`）写配置 →
     api 落盘到运行时数据目录的 `schedule.json`；
  2. `comic-scheduler` 每 5s 看一次表（cron 表达式，如 `0 3 * * *` = 每天 03:00、`*/15 * * * *` = 每 15 分钟），
     到点按配置的 `action` 跑一轮：`sync`（默认）= 对选中的数据源各跑一次采集，
     `inspect` = 失效巡检（转存未转存页 + 全表校验 + 恢复丢失，**不含**手动巡检那步全库封面自愈）；
     跑完把运行态写回 `schedule_state.json`、并把这一轮记进任务表 `admin_task`（见下条）；
  3. 「立即执行一次」也是走这两个进程：api 写一个 `schedule_run_now.json`（**带上点按钮的人**），
     执行器**读到即删**并跳一轮。

  ⚠️ 三个文件**各只有一个写者**（配置 api 写 / 状态执行器写 / 触发 api 写执行器删）——
  两个进程同时写同一个 JSON 会互相截断，这是这套设计唯一的硬约束。
  ⚠️ 采集语义与管理台「触发采集」**构造上一致**（都调采集层的 `sync_source`）；准入是**参数即准入** ——
  **不看**数据源开关，留空 = 全部默认启用的源（要采 `mangadex` 这类默认关闭的源须显式点名）。
  到点时执行器没在跑（或已过 300s 宽限窗口）就跳过该轮（**错过不补**，要补点「立即执行一次」）。
  ⚠️ 页面会显示「执行器：在线/离线」（靠心跳判定）—— 执行器没起来时配置照样存得下，但**不会有人跑**。
  ⚠️ **定时轮次也会发消息**（消息中心，收件范围 = 管理员及以上）：手动触发与定时轮次跑完都往
  `message` 表发一条（`kind` = 任务类型），归属显示「系统（定时）」或点按钮的人；
  跑的过程中还会以"进行中"条目出现在列表里。管理台顶栏铃铛 → 消息中心就是任务历史的入口
  （原来采集管理页底部那块「最近任务」2026-10-06 已并入这里）。
  ⚠️ **消息中心**：一轮跑完，执行器会往 `POST /api/messages` 发一条消息（管理台顶栏铃铛与消息页）。
  它是**另一个容器**，所以需要 `COMIC_API_BASE`（compose 的 `x-app-env` 默认 `http://comic-app:8000`）
  与 **`X-Service-Token`**（HMAC，密钥复用 `COMIC_JWT_SECRET`，见 `comic_core/notify.py`）。
  发消息失败**只是记一条 warning**，不影响这一轮采集 —— 消息是可观测性，不是采集的前置条件。
  cron 语法见 `crawler-service/src/comic_crawler/scheduling/cron.py`；
  三个文件与两个进程的分工见 `comic-scheduler/README.md`。
  （采集中枢只有这一处：**没有** CLI 采集命令 —— `cli run` / `cli serve` 已于 2026-10-06 删除。）
- **采集层可单独用**（不经过接口层 —— 但注意：**采集本身只能由管理台或 `comic-scheduler` 触发**，
  这里能单独跑的是运维命令）：
  ```bash
  docker run --rm -e COMIC_MYSQL_HOST=... comic-crawler:1.0.0 python -m comic_crawler.cli inspect   # 失效巡检
  docker run --rm comic-crawler:1.0.0 python -m comic_crawler.cli list                             # 看已注册源
  ```
- **现有库升级**（不是全新初始化）时，新表/索引/去约束用 `tools/` 里的迁移脚本补。镜像里**不带**
  `tools/`（全新部署由 `mysql_schema.sql` 建全表，用不到它们），需要在容器里跑就把目录挂进去。
  这些脚本都是**幂等**的，可以照抄（注意 `-f` 后面的路径按你的实际位置写）：
  ```bash
  cd deploy    # 相对挂载路径按 compose 文件所在目录解析，服务器与 Git Bash 都成立
  # ⚠️ 两个挂载缺一不可：tools = 脚本本体；comic-core/sql = 脚本抠 DDL 的唯一真源
  #    （api 镜像只装了 wheel，里面没有 comic-core/sql —— 少了它，真要建表/加列时会直接失败）
  M='-v ../tools:/app/tools:ro -v ../comic-core/sql:/app/comic-core/sql:ro'
  docker compose -f docker-compose.yml run --rm $M comic-app python tools/add_log_table.py
  docker compose -f docker-compose.yml run --rm $M comic-app python tools/add_perf_indexes.py
  docker compose -f docker-compose.yml run --rm $M comic-app python tools/drop_fingerprint_unique.py
  docker compose -f docker-compose.yml run --rm $M comic-app python tools/add_user_role.py
  docker compose -f docker-compose.yml run --rm $M comic-app python tools/add_admin_task_table.py
  docker compose -f docker-compose.yml run --rm $M comic-app python tools/add_message_table.py
  docker compose -f docker-compose.yml run --rm $M comic-app python tools/check_schema.py   # 体检：表齐不齐
  ```
  懒得逐条敲就 **`bash deploy/up.sh --migrate`** —— 起完服务自动把上面这些跑一遍，最后体检、缺表就报错。

> ⚠️ 两个前提：① **已有数据卷不会重跑 mysql 的初始化脚本**（MySQL 的规矩）—— 新表只能靠这一步补；
> ② 迁移脚本的 DDL 是**从 `comic-core/sql/mysql_schema.sql` 抠出来的**（唯一真源，不重抄一份），
> 而 api 镜像只装了 wheel、里面没有 `comic-core/sql` —— 所以容器里跑要把它一起挂上（见上面的 `$M`）。
> 不挂的话"真要建表/加列"时会在容器里读不到文件直接失败；而表已存在时脚本早退，平时看不出来。

## 2. 方式 B：直接在仓库里跑（**本地开发用这个**）

> **分工**：本地开发就走这条路（宿主直跑，起得快、有热重载）；**上线走 §1 的 Docker Compose**。
> 本节同时说明了 `core/bootstrap.py` 的路径注入机制 —— 它把 `<repo>/comic-core/src` 与
> `<repo>/crawler-service/src` 加进 `sys.path`，所以仓库本身就是可运行形态，**不需要设 `PYTHONPATH`**。

`core/bootstrap.py` 的候选路径列表里，**开发态两条排在最前**（`comic-core/src`、`crawler-service/src`），
`DIST_DIR` 也会回落到 `comic-web/dist` —— 所以仓库本身就是一个可运行的部署形态：

```bash
pip install -r comic-core/requirements.txt -r crawler-service/requirements.txt -r api-service/requirements.txt
cd comic-web && npm run build          # 前端产物（改过前端才需重跑）
cd api-service && python -m uvicorn main:app --host 0.0.0.0 --port 8000
# 定时采集要单独起执行器（管理台配的 cron 靠它跑；不起它 = 配了也没人跑）
cd ../comic-scheduler && PYTHONPATH=../crawler-service/src:../comic-core/src python -m comic_scheduler
```

> 三个 `requirements.txt` **只列第三方依赖** —— `comic_core` / `comic_crawler` 是仓库内本地包
> （PyPI 上不存在），靠 `api-service/core/bootstrap.py` 在导入时把两个 `src` 目录注入 `sys.path`
> 来定位（**导入即生效、幂等，不需要手工设 `PYTHONPATH`**；wheel 态它们已在 site-packages，候选目录不存在、自然跳过）。
> ⚠️ `comic-scheduler` **没有** bootstrap 那一层（它是个独立进程、不在 api 的导入链里），
> 所以本机直跑要显式给 `PYTHONPATH`；容器里则是 pip 装好的 wheel（见 `deploy/scheduler/Dockerfile`）。

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
| `main.py` · `core/` · `routers/` · `services/` · `schemas.py` · `serializers.py` | HTTP 服务（api-service 分层代码）。⚠️ 这里的 `core/` 是 api 的 HTTP 分层包，与 `src/comic_core/` 无关 |
| `src/comic_core/` | 公共内核（领域模型 / 存储契约与 MySQL 实现 / 图库读写 / 标签归一），**含词表数据 `data/`** |
| `src/comic_crawler/` | 采集服务包（适配器 / 存储 / 调度 / CLI） |
| `dist/` | 前端产物（同源托管） |
| `sql/mysql_schema.sql` | 建库脚本（10 张表，含 `log_record`） |
| `requirements.txt` | core + crawler + api 依赖**合并去重**（`sort -u` 生成） |
| `README-DEPLOY.md` | 一页运行说明（脚本自动生成） |

**为什么两个包都放在 `src/` 下、而不是直接放 `<out>/`**：
`data` 目录（图库 + 源开关状态）的默认根由包位置推出来 —— 放 `src/` 下才能与开发态同构，
运行时数据正好落在 `<out>/data/`。`api-service/core/bootstrap.py` 的候选路径里就有一条
`<bundle>/src`，正是为这件事准备的（所以运行时**不需要**手工设 `PYTHONPATH`）。

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

> 管理台**日志查询页的时间列**已固定按北京时间出参（`services/logs.to_beijing`）：容器时区配对了
> 是恒等变换，漏配/没重建就自动补 8 小时 —— 页面不再依赖这一项是否改对；但**筛选**的时间窗
> 仍按存储侧时区比较，对不上时还是先查 `docker exec comic-app date`。

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
mysql -h <host> -P <port> -u root -p < comic-core/sql/mysql_schema.sql
# 若用的是 §3 的发布包（包内有 sql/ 目录）：
#   mysql -h <host> -P <port> -u root -p < sql/mysql_schema.sql
```

> ⚠️ 手工这条路**只建表、不建库**：`mysql_schema.sql` 是纯 DDL，里面没有 `CREATE DATABASE`
> （设计上依赖"库由 `MYSQL_DATABASE` 创建并选中"）。若目标库还不存在，会直接报
> `ERROR 1049 Unknown database`，得先 `CREATE DATABASE comic DEFAULT CHARACTER SET utf8mb4` 再执行。

- 脚本是 `CREATE TABLE IF NOT EXISTS` + 带 `UNIQUE KEY`，**幂等可重跑**，且**不含任何 `DROP`**；
- 新库会自动带上 `log_record` 表、性能索引，且 `comic.fingerprint` 是**普通索引**；
  **已有库**（老环境升级）对应补这几个脚本：`add_log_table.py`（补表）、`add_perf_indexes.py`（补索引）、
`add_admin_task_table.py`（补 `admin_task` 表）、`add_message_table.py`（补 `message` / `message_read`
两张表与 `message` 的新列）、
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

### 停进程（按 PID，别按镜像名批量杀）

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object -ExpandProperty OwningProcess
Stop-Process -Id <pid> -Force
```

- **后端是父子两个 python 进程，两个都要停** —— 只停父进程会留下子进程继续占着 8000。
- ⚠️ **禁用 `taskkill /IM python.exe`**：本机还跑着其它 Python 服务（如 MCP 进程），
  按镜像名批量杀会误伤。

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

API 进程里还有**一处进程内状态**，多 worker 会直接出错：

| 位置 | 状态 | 多 worker 的后果 |
|---|---|---|
| `services/sources.py` | `_state` 是内存缓存（落盘文件 `source_state.json`） | **开关不同步**：在 A 关闭的源，B 仍按旧状态执行 |

> ✅ **任务表已经不再是阻塞项**（2026-10-06）：后台任务从进程内 dict 搬到了 MySQL 的
> `admin_task` 表（`services/tasks.py` + `comic_core.storage.mysql.task_store`）——
> 任务与触发账号一起落库，api 重启不丢、也能看出是谁点的。启动时 `tasks.reap_stale()`
> 会按**本进程启动时刻**为界，把上一进程没跑完的 `running` 标成「服务重启，任务中断」，
> 所以将来 A worker 的启动不会误伤 B 正在跑的任务。

> 附带一条：**连接池也是每进程一份**（crawler-service 的 `storage/mysql/_pool.py`，上限 20）——
> 多 worker 会把 MySQL 连接数成倍放大，而 `my.cnf` 的 `max_connections = 200` 是硬顶。
> 这也是暂不扩 worker 的附带理由（主因还是上表那处开关状态）。

**要扩到多进程，现在只剩一件半事**：数据源开关每次读文件/库（或加缓存失效）；
另外 `services/tasks.py` 里"执行仍在 api 进程内的后台线程"这一点要一并想清楚 ——
线程随进程走，多 worker 下任务落在哪个 worker 都行（状态在库里），但**同一个任务不能跨 worker 续跑**。

另外两条与 worker 数无关但需要知道的：

- **调度循环都不在 API 进程里**：手动触发是 api 进程内的后台线程（短任务，人等着看结果），
  定时执行在**独立服务 `comic-scheduler`** —— 所以"多 worker 会不会重复采集"这件事
  **不存在**（真要担心的是"起两份 `comic-scheduler`"，那是双进程问题，与 worker 数无关）；
- 日志落库的 Handler 是**每个进程各挂一个**（各自一条后台线程 + 批量写），多 worker 下是 N 份并行写，不会串。

## 9. 定时采集

生产里"定时采集"由**独立服务 `comic-scheduler`** 执行，配置入口是管理台「定时任务」栏
（两个进程如何交换配置/状态/触发请求，见 §5 的"定时采集：一条路，两个进程"）：

```bash
# 随栈启动（默认就起；--collect 已废弃）
bash deploy/up.sh
# 看它有没有在跑 / 有没有按点采集
docker compose -f deploy/docker-compose.yml logs -f comic-scheduler
```

页面上的「执行器：在线 / 离线」与心跳时间就是它的体检报告 —— "配了到底有没有人跑"一眼可辨。
定时任务的**动作**可选**采集**（逐源）或**失效巡检**（转存 + 全表校验 + 恢复丢失）：
后者让"每小时/每天巡检一次"重新有了归宿（旧的轮询调度删掉后曾一度只剩手动按钮）；
⚠️ 定时巡检**不含**手动巡检那步「全库封面自愈」—— 巡检频率高，不该每次都多打一轮源站请求。
每一轮的记录都会进**消息中心**（`message` 表，收件范围 = 管理员及以上：谁触发的、跑了多久、结果如何）。
也可以**完全不用定时**（只在管理台手动触发）。采集层剩下的命令都是**运维/排障**用的：

```bash
# 失效巡检（转存未转存页 + 全表校验 + 恢复丢失）
python -m comic_crawler.cli inspect [--source <name>]
# 懒转存未转存页 / 看库内数据 / 列已注册源
python -m comic_crawler.cli transfer-images | show | list
```

> 这些命令跑的是 `crawler-service` 的 CLI；在发布包里对应 `<out>/src/comic_crawler`，
> 加 `PYTHONPATH=<out>/src` 即可。
> ⚠️ **没有** `cli run` / `cli serve`（2026-10-06 删除）：采集只能由管理台「触发采集」
> 或 `comic-scheduler` 触发，避免出现第三个各管一摊的采集入口。

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

**Compose 方式（§1）也实测过**：`docker compose up -d` 起 `comic-mysql` + `comic-app` + `comic-web` +
`comic-front`（数据库是**本项目独占**的 8.0 实例，app 走编排内网连 `comic-mysql:3306`；两个前端各自带
nginx 反代到 `comic-app:8000`），首页与 `/assets` 分包均 200，`nginx -t` 通过。
apk 无关的镜像构建走 `PIP_INDEX`（见 `deploy/build.sh` 注释）可换国内源。

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
