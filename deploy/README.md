# deploy —— 生产部署（Linux / Docker Compose）

**每个模块一个文件夹**：产物与它的 Dockerfile 放在一起，打开这一层就能看清有几块、各是什么。

```
deploy/
├── web/       Dockerfile + nginx.conf + dist/（网页端产物）  → comic-web:1.0.0    自带 nginx，宿主 85
├── front/     Dockerfile + nginx.conf + dist/（移动端产物）  → comic-front:1.0.0  自带 nginx，宿主 86
├── crawler/   Dockerfile + dist/comic_crawler-*.whl          → comic-crawler:1.0.0  采集层（可单独当 CLI 镜像）
├── api/       Dockerfile + dist/comic_api-*.whl              → comic-api:1.0.0      接口层（依赖采集层 wheel，**纯 API**）
├── mysql/     Dockerfile + sql/（建库脚本产物）              → comic-mysql:1.0.0    本项目独占的库
├── build.sh / build.bat                                      生成产物 + 按序构建这些镜像
├── up.sh                                                     **一键**：前端 build（默认两个入口，可 --web/--front 选）+ 上面这些 + up -d + 自检
├── docker-compose.yml                                        编排：comic-mysql + comic-app + comic-web / comic-front
└── .env.example                                              配置模板（`deploy/.env` 已 gitignore）
```

> 命名统一带 `comic-` 前缀：**镜像名**、**容器名**、**compose 服务名**三者一致
> （服务名 = 容器名，所以 `docker compose ps` / `exec comic-app` 用的是同一个名字）。

## 两个前端入口：各自一个镜像、各自一个端口

前端不再烘进 `comic-api` 镜像，而是**两个独立的前端镜像**，各自**自带 nginx**（静态产物 + 反代在
同一个容器里）。好处是「只开移动端」时不会出现「反代活着但产物不在」的悬空状态，按需启动最省事。

| 入口 | 镜像 | 产物来源 | 宿主端口 |
|---|---|---|---|
| 网页端 | `comic-web:1.0.0` | `comic-web/dist`（Vue3 SPA，已冻结、只作参考实现） | `WEB_PORT`（默认 85） |
| 移动端 | `comic-front:1.0.0` | `comic-front/dist/build/h5`（uni-app H5，**当前主用**） | `FRONT_PORT`（默认 86） |

- **两个可以同时跑**，互不影响：`docker compose up -d` 会一起起来；只想开一个就把服务名写在后面
  （`docker compose -f deploy/docker-compose.yml up -d comic-front`），依赖链会自动带上 `comic-app` 与 `comic-mysql`。
- **共用同一份 nginx 站点配置**：`deploy/web/nginx.conf` 与 `deploy/front/nginx.conf` 内容必须**逐字节一致**
  （Docker 构建上下文不能跨目录 `COPY`，只能各放一份）。`build.sh` / `build.bat` 构建前会校验，不一致直接报错。
  改了一处记得同步另一处：`cp deploy/web/nginx.conf deploy/front/nginx.conf`。
- 分流规则：`location ~ ^/(api/|docs|redoc|openapi\.json)` 反代到 `comic-app:8000`，其余本地静态文件。
  两个前端都是 **hash 路由 + 相对 base**，所以不需要 history 回退，末尾 `try_files` 纯容错。
- **`comic-api` 是纯 API**：`main.py` 的静态挂载有 `if DIST_DIR.is_dir()` 守卫，容器里没有前端目录
  就自然退化，后端代码一行没改。

## 数据库：本项目独占一个实例

`comic-mysql`（**MySQL 8.0**）只服务本项目，不与别的系统共用 —— 库、账号、权限、备份策略都独立
（独立实例最省心：共用会让别处的表 / 库混进来，排查成本极高）。

> 原 `comic` 库在别的实例上，**已整体迁入本实例并删除**（迁移记录见
> [`../docs/deploy.md`](../docs/deploy.md) §11）—— 所以线上与本地都只认这一个库。

- **首次启动自动建表**：建库脚本烘在 `deploy/mysql` 镜像里，数据卷为空时自动执行 →
  10 张表直接建好，**不需要手工跑任何 SQL**；
- **comic-app 走编排内网**连 `comic-mysql:3306`，不经过宿主端口；
- 宿主端口 **3309** 仅给 Navicat / IDEA 从本机连用（避开 3307 上其它系统）；
- 数据在 `mysql_data` 卷里，`down` 不会删卷；备份 = `mysqldump` + 卷快照；
- ⚠️ `MYSQL_ROOT_PASSWORD` **只对新建的卷生效** —— 库已经建好之后再改它不会同步，
  要改得 `docker compose down -v` 重置卷（会清库）或进容器 `ALTER USER`；
- 单独重建数据库镜像：`docker build -t comic-mysql:1.0.0 deploy/mysql`
  （`deploy/build.sh` 会连它一起构建）。

各 `dist/` 都是**产物**（gitignore 不入库），每次由 `build.sh` 重新生成：

| 模块 | 产物 | 来源 |
|---|---|---|
| `crawler` / `api` | **wheel** | 各自的 `pyproject.toml`（= 那个模块的 pom.xml）经 `pip wheel` 构建 |
| `web` | `dist/` 静态文件 | `cd comic-web && npm run build` 后复制进来；来源可用 `WEB_SRC=<目录>` 覆盖 |
| `front` | `dist/` 静态文件 | `cd comic-front && npm run build:h5` 后复制进来；来源可用 `FRONT_SRC=<目录>` 覆盖 |
| `mysql` | `sql/mysql_schema.sql` | 从 `crawler-service/sql/` 复制（烘进镜像，供首次初始化） |

wheel 里只有包本身 + 依赖声明 —— 测试、文档、样例夹具（`guazi/fixtures/*.html` 等）**自动被排除**。

## 三步起来

```bash
cp deploy/.env.example deploy/.env      # 至少改 MYSQL_ROOT_PASSWORD 与 COMIC_JWT_SECRET
./deploy/build.sh                       # 构建 wheel/产物 + 按序构建镜像（Windows: deploy\build.bat）
docker compose -f deploy/docker-compose.yml up -d
```

**或者一条命令干完这一串**（含前置检查与自检）：

```bash
./deploy/up.sh                   # 两个入口都起（默认）：git pull + npm build + 镜像 build + 起服务 + 自检
./deploy/up.sh --web             # 只起网页端（comic-web，宿主 85）
./deploy/up.sh --front           # 只起移动端（comic-front，宿主 86）
./deploy/up.sh --skip-web        # 前端没改 → 跳过 npm build（快很多）
./deploy/up.sh --skip-pull       # 不更新代码 → 直接按当前工作区构建
./deploy/up.sh --collect         # 额外起定时采集 comic-scheduler
./deploy/up.sh --migrate         # 老环境升级：起完后跑一遍幂等迁移脚本（已有库才需要）
```

> 前端选择：**不带参数 = 两个入口都起**；带 `--web` / `--front` 就是只起选中的那个
> （也可以两个都给，等价于不带参数）。

`up` 依次做六步：**0)** `git pull`（只快进不合并，并把「更新了哪几条提交」打出来；
不是 git 工作区 / 断网 / 冲突时不中止，按当前工作区继续）→
**1)** 前置检查（docker / compose v2 / `.env` / 数据目录）→
**2)** 所选前端 `npm run build`（默认两个）→ **3)** 调 `build.sh`（生成产物 + 按序构建镜像）→
**4)** `compose up -d <所选入口>` → **5)** 自检（mysql healthy → 容器内 `/api/health` →
数据目录可写 → 各入口 HTTP 码 + **前端身份**）。**幂等**：重复跑就是更新代码 + 重新构建 + `up -d`，不会清数据。
加了 `--migrate` 就在 4 与 5 之间多跑一步"已有库迁移"（`add_log_table` / `add_perf_indexes` /
`drop_fingerprint_unique` / `add_user_role`，逐个挂 `../tools` 进容器执行，都是幂等的）。

### 只重建某一个前端

```bash
./deploy/build.sh --web            # 只构建 comic-web:1.0.0
./deploy/build.sh --front          # 只构建 comic-front:1.0.0
./deploy/build.sh                  # 不带参数 = 两个都构建
```

`up.sh` 会把所选前端交给 `build.sh` 的 `--web` / `--front`，并用 `WEB_SRC` / `FRONT_SRC`
把产物目录指过去。`build.sh` 复制前会**清空目标目录**，所以不会出现两套 hash 产物混在一起
（旧版 `up-front.sh` 因为共用 `deploy/web/dist` 才需要手工 `rm -rf`；现在两个前端各有自己的目录，这个问题不存在了）。

自检里会打一行**前端身份**（uni 的 `index.html` 带 `<!--app-html-->` 占位注释，comic-web 的是
`<div id="app"></div>`），便于一眼确认这个入口部署的是哪个前端；认错了会明确告警。

## 几个不显然的点

- **两个模块之间没有镜像依赖**：`api` 不再 `FROM comic-crawler:1.0.0`，而是在
  `api-service/pyproject.toml` 的 `dependencies` 里声明 `comic-crawler>=1.0.0`（方向单向：api → crawler），
  构建时 pip 按这条声明解析安装；采集层的 **wheel 产物**经 BuildKit 命名上下文 `crawler` 喂进 api 的
  构建上下文（`build.sh` 的 `--build-context crawler=./crawler` / compose 的 `additional_contexts`）。
  所以**不必先有 crawler 镜像**，只要它的 wheel 已生成（`build.sh` 步骤 1 已保证）；
  顺序 `mysql → web → crawler → api → front` 仍固定在 `build.sh` 里，只是不再是硬约束。
  两个前端镜像**反向不依赖后端**（nginx.conf 里的 `upstream comic-app:8000` 构建期不解析、运行期才需要）；
- **构建上下文就是模块文件夹**（`context: ./api`），里面只有产物 + Dockerfile，
  所以不需要 `.dockerignore`，也不会把 `.git`/`.venv`/`node_modules` 送进构建；
- **wheel 装进 site-packages 后相对路径推导失效**，所以镜像里显式给了
  `COMIC_IMAGE_ROOT` / `COMIC_STATE_FILE` 等环境变量（见 api 与 crawler 的 Dockerfile）；
- **容器里 `comic_crawler` 来自 pip 安装的依赖**（site-packages），不再靠镜像继承 ——
  `core/config.py` 那套相对路径候选在 wheel 态自然全部落空、直接可导入；
- **采集层能单独用**：`docker run --rm comic-crawler:1.0.0 python -m comic_crawler.cli list`；
- **`/data` 必须在镜像里建好**（采集层 Dockerfile 里做了 `mkdir + chown`）——
  命名卷首次创建会继承镜像中该路径的属主，否则以 uid 10001 运行的进程写不进去；
- **app 单进程**（不加 `--workers`）—— 内存任务表与内存开关状态尚未改造，多 worker 会导致"任务查不到"；
- **容器名固定**：`comic-mysql` / `comic-app` / `comic-web` / `comic-front`（+ `comic-scheduler`）——
  由 compose 的 `container_name` 指定，不用 compose 自动生成的 `xxx-1` 形式，运维时好叫；
- **宿主端口可配**：`.env` 的 `WEB_PORT`（默认 85）/ `FRONT_PORT`（默认 86）。端口被占用就改这里，
  容器内仍是 80；
- **数据分两处**：`mysql_data` 卷 → 数据库（`down` 不删卷）；**图库与源开关状态在宿主目录**
  （bind 到容器 `/data`，默认 `../crawler-service/data`，可用 `.env` 的 `COMIC_DATA_HOST` 改）——
  **与本地直跑共用同一份**，所以本地转存的图容器立刻能读（反之亦然）。服务器请指到仓库外的独立盘，
  并保证目录可写（`sudo chown -R 10001:10001 <dir>`，容器内进程 uid 10001）；
- **管理台 / 日志 / 授权页要管理员角色**：管理台与日志要 `require_admin`（超管 + 普通管理员），
  **授权页要 `require_superadmin`（仅超管）**；未登录 401 / 权限不足 403。
  全新库**首个注册用户自动成为超管**；老库升级加 `--migrate` 补 `user.role` 列；给他人授权在管理台「授权」页。
  管理台路由：comic-web 是 `/#/admin`，comic-front 是 `/#/pages/admin/index`；
- **时区由 `COMIC_TZ` 统一（默认 `Asia/Shanghai`），别删**：基础镜像没有 TZ 就是 UTC，
  而程序里所有"当前时间"（`log_record.created_at`、`comic/chapter.sync_time`、`logs/api.log`
  的时间戳）都按**本机时间**写入 —— 不设 TZ 服务器上会比北京时间早 8 小时。
  app / scheduler / mysql 三个服务共用它
  （mysql 的 `time_zone=SYSTEM` 跟随容器时区，决定 `NOW()`，影响日志保留策略的 30 天边界）。
  ⚠️ **改 `.env` 后要 `up -d` 重建容器才生效**；镜像自带 tzdata，无需额外装包。

完整说明（环境变量、上线前必做清单、迁移脚本怎么跑）见 [`../docs/deploy.md`](../docs/deploy.md)。
