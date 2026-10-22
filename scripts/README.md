# scripts —— 环境初始化、启动与打包

**只放"跑起来 / 产出发布物"相关的脚本**（幂等的环境、启动与打包动作），不放业务逻辑、
不放一次性数据迁移（数据迁移在 [`../tools/`](../tools/README.md)）。

Windows（`.bat`）与 Unix（`.sh`）各一份，内容等价。

| 脚本 | 作用 | 说明 |
|---|---|---|
| `init_mysql.bat` / `.sh` | 按 `comic-core/sql/mysql_schema.sql` 建库建表 | 一般**不用跑**：本项目独占的 `comic-mysql` 容器首次启动会自动建。脚本幂等且**不含 `DROP`、不会清空数据**；口令自动读 `deploy/.env` |
| `start_mysql.bat` / `.sh` | 本地开发：启动站点到 `:8000`（读 MySQL） | 依赖数据库容器 `comic-mysql` 可达（默认 `127.0.0.1:3309`，参数自动读 `deploy/.env`） |
| `check.bat` / `.sh` | **一键自检**：crawler 单测 + api 分层守卫 + 前端 `tsc --noEmit` | 提交前跑一次；可软链进 `.git/hooks/pre-commit` 自动拦截 |
| `dev.sh` | **本地开发环境**：`status` / `up api`·`web`·`front` / `down ...` / `bootstrap` | python 是项目内两层：`.python/` 底座 + `crawler-service/.venv`（缺失自动下载/创建）；前端用标准 `npm run dev`；`up` 是前台进程，agent 用 `run_in_background` |
| `package.bat` / `.sh` | **打包部署产物**到 `build/deploy`（部署时才生成，不入库） | 需要先 `npm run build` 出 `comic-web/dist` |

## 自检（提交前建议跑一次）

```bash
./scripts/check.sh        # Unix
scripts\check.bat         # Windows
```

三步全过才输出 `OK all checks passed`。**为什么要脚本**：两个服务的分层守卫
（`crawler-service/tests/test_layering.py`、`api-service/tests/test_layering.py`）
只有在真的跑测试时才会红，靠"自觉"必然退化——把它固化成一条命令，
或直接软链进 git 钩子：

```bash
ln -sf ../../scripts/check.sh .git/hooks/pre-commit
```


## 本地开发服务（`dev.sh`）

```bash
bash scripts/dev.sh status      # MySQL / 解释器来源 / 端口 / /api/health 一览
bash scripts/dev.sh bootstrap   # 手动创建 / 补齐 python 环境（一般不用手动跑，up api 会自动做）
bash scripts/dev.sh up api      # 起后端 :8000（前台；agent 加 run_in_background）
bash scripts/dev.sh up web      # 起 comic-web :5173
bash scripts/dev.sh up front    # 起 comic-front :5174
bash scripts/dev.sh down api    # 停（也支持 web / front / all）
```

- **python 是项目内两层**（都进 `.gitignore`，不碰系统 python）：
  `.python/` = 官方 CPython 3.13 底座（缺失自动下载，约 15MB）；`crawler-service/.venv` = 运行环境，
  `pyvenv.cfg` 的 `home` 指向 `.python`。`up api` / `check.sh` 会自动建齐，底座不一致会自动重建。
  详见 `NOTES.md` §2.4。
- 前端用标准 `npm run dev` / `npm run dev:h5`（`npm` 已由受管 Node 接管），探测失败时才回退 node 直调 bin —— 见 `NOTES.md` §2.1；
- `up` 是**前台**进程：人在终端跑（Ctrl+C 停），agent 调用时加 `run_in_background: true`；
- 停止按端口找 PID（`taskkill //PID`），**不要 `taskkill /IM python.exe`**。

## 部署打包

仓库**不再保留发布包副本**（原先的 `comic-deploy/` 已删除，避免手工双副本漂移）。
部署时按需生成：

```bash
./scripts/package.sh                 # 产出 build/deploy（可用参数指定输出目录）
./scripts/package.bat                # Windows 等价
```

产出结构与开发态**同构**，因此图库根解析（`comic_core.paths.SERVICE_ROOT`）两种形态一致：

```
build/deploy/
├── main.py  core/  routers/  services/  schemas.py  serializers.py   # HTTP 层
├── src/comic_core/                                                  # 公共内核（领域模型/存储/图库/标签）
├── src/comic_crawler/                                               # 采集包
├── src/comic_scheduler/                                             # 定时任务执行器（独立进程）
├── dist/                                                            # 前端产物（同源托管）
├── sql/mysql_schema.sql
├── requirements.txt                                                 # core + crawler + scheduler + api 依赖合并去重
└── README-DEPLOY.md
```

> ⚠️ 上面 `core/`（api 的 HTTP 分层包）与 `src/comic_core/`（公共内核）**同名不同物**，别混。
> 两个包都放 `src/` 下是为了让 data 目录仍解析到 `<bundle>/data/`。
> 定时采集要**另起一个进程**：`PYTHONPATH=src python -m comic_scheduler`（管理台配的 cron 靠它跑）。

用法示例：

```bash
./scripts/init_mysql.sh          # 首次建库（⚠️ 会清空 comic 库）
./scripts/start_mysql.sh         # 起服务，浏览器访问 http://127.0.0.1:8000
./scripts/package.sh /tmp/dist   # 打包到指定目录
```

> **分工**：本地开发用 `scripts/dev.sh`（`status` / `up api` / `up web` / `up front`，带 HMR）；
> **上线用 `deploy/` 的 Docker 编排**。⚠️ 不要用 `npm run dev` —— 本机 `npm` 被安全策略拦（见 NOTES §2.1）。
>
> **前置依赖**：数据库在 Docker 容器 `comic-mysql`（**本项目独占实例**，宿主 `127.0.0.1:3309`；
> **不是**本机 3306，也不是别的系统占着的 3307）。起服务前先确认 Docker Desktop 已运行、
> `docker ps` 中 `comic-mysql` 为 `Up`，否则后端连不上库。
> 日志统一写根 `logs/`（`api.log` / `vite.log`）。

---

> 踩坑、实测与复盘 → **[NOTES.md](NOTES.md)**（AI 维护）。
