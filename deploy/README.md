# deploy —— 生产部署（Linux / Docker Compose）

**每个模块一个文件夹**：产物与它的 Dockerfile 放在一起，打开这一层就能看清有几块、各是什么。

```
deploy/
├── web/       Dockerfile + dist/（前端构建产物）      → comic-web:1.0.0      只装 dist
├── crawler/   Dockerfile + dist/comic_crawler-*.whl  → comic-crawler:1.0.0  采集层（可单独当 CLI 镜像）
├── api/       Dockerfile + dist/comic_api-*.whl      → comic-api:1.0.0      接口层（FROM 采集层）
├── nginx/     Dockerfile + nginx.conf                → comic-nginx:1.0.0    反代（配置烘进镜像）
├── mysql/     Dockerfile + sql/（建库脚本产物）      → comic-mysql:1.0.0    本项目独占的库
├── build.sh / build.bat                              生成产物 + 按序构建这 5 个镜像
├── up.sh                                              **一键**：前端 build + 上面这些 + up -d + 自检
├── docker-compose.yml                                编排：comic-mysql + comic-app + comic-nginx
└── .env.example                                      配置模板（`deploy/.env` 已 gitignore）
```

> 命名统一带 `comic-` 前缀：**镜像名**、**容器名**、**compose 服务名**三者一致
> （服务名 = 容器名，所以 `docker compose ps` / `exec comic-app` 用的是同一个名字）。

## 数据库：本项目独占一个实例

`comic-mysql`（**MySQL 8.0**）只服务本项目，不与别的系统共用 —— 库、账号、权限、备份策略都独立。
（本项目曾与别的系统共用过一个 MySQL 实例，出现过"别人的表建进我们库"这类问题，独立实例最省心。）

> 原 `comic` 库在别的系统那个 3307 实例上，**已整体迁入本实例并删除**（迁移记录见
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
| `web` | `dist/` 静态文件 | `cd comic-web && npm run build` 后复制进来 |
| `mysql` | `sql/mysql_schema.sql` | 从 `crawler-service/sql/` 复制（烘进镜像，供首次初始化） |

wheel 里只有包本身 + 依赖声明 —— 测试、文档、样例夹具（`guazi/fixtures/*.html` 等）**自动被排除**。

## 三步起来

```bash
cp deploy/.env.example deploy/.env      # 至少改 MYSQL_ROOT_PASSWORD 与 COMIC_JWT_SECRET
cd comic-web && npm run build           # 前端产物（build.sh 会把它复制进 deploy/web/dist）
./deploy/build.sh                       # 构建 wheel/dist + 按序构建镜像（Windows: deploy\build.bat）
docker compose -f deploy/docker-compose.yml up -d
```

**或者一条命令干完这一串**（含前置检查与自检）：

```bash
./deploy/up.sh                 # 一键：前端 build + 镜像 build + 起服务 + 自检
./deploy/up.sh --skip-web      # 前端没改 → 跳过 npm build（快很多）
./deploy/up.sh --collect       # 额外起定时采集 comic-scheduler
```

`up` 依次做五步：**0)** 前置检查（docker / compose v2 / `.env` / 数据目录）→
**1)** 前端 `npm run build` → **2)** 调 `build.sh`（生成产物 + 按序构建 5 个镜像）→
**3)** `compose up -d` → **4)** 自检（mysql healthy → 容器内 `/api/health` →
数据目录可写 → 对外入口 HTTP 码）。**幂等**：重复跑就是重新构建 + `up -d`，不会清数据。

## 几个不显然的点

- **构建顺序不能乱**：`api` 的 Dockerfile 会 `FROM comic-crawler:1.0.0` 并 `COPY --from=comic-web:1.0.0`，
  所以必须先有那两个镜像。顺序 `mysql → web → crawler → api → nginx` 已固定在 `build.sh` 里；
  只在单层改动时也可以 `docker compose build comic-app`；
- **构建上下文就是模块文件夹**（`context: ./api`），里面只有产物 + Dockerfile，
  所以不需要 `.dockerignore`，也不会把 `.git`/`.venv`/`node_modules` 送进构建；
- **wheel 装进 site-packages 后相对路径推导失效**，所以镜像里显式给了
  `COMIC_IMAGE_ROOT` / `COMIC_DIST_DIR` / `COMIC_STATE_FILE` 三个环境变量（见 api 与 crawler 的 Dockerfile）；
- **镜像内仍是仓库的相对布局**（`/app/api-service/`、`/app/crawler-service/src/`、`/app/comic-web/dist/`）——
  `core/config.py` 正是按这个相对关系定位 `comic_crawler` 包与 `dist` 的；
- **采集层能单独用**：`docker run --rm comic-crawler:1.0.0 python -m comic_crawler.cli list`；
- **`/data` 必须在镜像里建好**（采集层 Dockerfile 里做了 `mkdir + chown`）——
  命名卷首次创建会继承镜像中该路径的属主，否则以 uid 10001 运行的进程写不进去；
- **app 单进程**（不加 `--workers`）—— 内存任务表与内存开关状态尚未改造，多 worker 会导致"任务查不到"；
- **容器名固定**：`comic-mysql` / `comic-app` / `comic-nginx`（+ `comic-scheduler`）——
  由 compose 的 `container_name` 指定，不用 compose 自动生成的 `xxx-1` 形式，运维时好叫；
- **宿主端口可配**：`.env` 的 `HTTP_PORT`（默认 80）。80 常被别的程序占用（Windows 上尤其），
  改成 8080 之类即可，容器内仍是 80；
- **数据分两处**：`mysql_data` 卷 → 数据库（`down` 不删卷）；**图库与源开关状态在宿主目录**
  （bind 到容器 `/data`，默认 `../crawler-service/data`，可用 `.env` 的 `COMIC_DATA_HOST` 改）——
  **与本地直跑共用同一份**，所以本地转存的图容器立刻能读（反之亦然）。服务器请指到仓库外的独立盘，
  并保证目录可写（`sudo chown -R 10001:10001 <dir>`，容器内进程 uid 10001）；
- **管理台接口目前无鉴权**（`/api/admin/*` 不做限制）—— 已知项，后续处理；现阶段仅用于测试上线。

完整说明（环境变量、上线前必做清单、迁移脚本怎么跑）见 [`../docs/deploy.md`](../docs/deploy.md)。
