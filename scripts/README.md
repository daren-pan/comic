# scripts —— 环境初始化、启动与打包

**只放"跑起来 / 产出发布物"相关的脚本**（幂等的环境、启动与打包动作），不放业务逻辑、
不放一次性数据迁移（数据迁移在 [`../tools/`](../tools/README.md)）。

Windows（`.bat`）与 Unix（`.sh`）各一份，内容等价。

| 脚本 | 作用 | 说明 |
|---|---|---|
| `init_mysql.bat` / `.sh` | 按 `crawler-service/sql/mysql_schema.sql` 初始化 `comic` 库 | 幂等（`CREATE DATABASE IF NOT EXISTS`），**但会 DROP 重建表 → 会清空现有数据** |
| `start_mysql.bat` / `.sh` | 启动站点到 `:8000`（读 MySQL） | 依赖 MySQL 可达，连接参数用 `COMIC_MYSQL_*` 覆盖（默认 127.0.0.1:3307） |
| `check.bat` / `.sh` | **一键自检**：crawler 单测 + api 分层守卫 + 前端 `tsc --noEmit` | 提交前跑一次；可软链进 `.git/hooks/pre-commit` 自动拦截 |
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


## 部署打包

仓库**不再保留发布包副本**（原先的 `comic-deploy/` 已删除，避免手工双副本漂移）。
部署时按需生成：

```bash
./scripts/package.sh                 # 产出 build/deploy（可用参数指定输出目录）
./scripts/package.bat                # Windows 等价
```

产出结构与开发态**同构**，因此图库根解析（`comic_crawler.paths.SERVICE_ROOT`）两种形态一致：

```
build/deploy/
├── main.py  core/  routers/  services/  schemas.py  serializers.py   # HTTP 层
├── src/comic_crawler/                                               # 采集包
├── dist/                                                            # 前端产物（同源托管）
├── sql/mysql_schema.sql
├── requirements.txt                                                 # api + crawler 依赖合并去重
└── README-DEPLOY.md
```

用法示例：

```bash
./scripts/init_mysql.sh          # 首次建库（⚠️ 会清空 comic 库）
./scripts/start_mysql.sh         # 起服务，浏览器访问 http://127.0.0.1:8000
./scripts/package.sh /tmp/dist   # 打包到指定目录
```

> 日常开发请**不要**用这里的启动脚本，改用热重载：
> `cd api-service && ../crawler-service/.venv/Scripts/python.exe -m uvicorn main:app --port 8000`
> 以及 `cd comic-web && npm run dev`（5173，带 HMR）。
