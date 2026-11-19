# Dify 平台：启动与配置迁移
本文件说明 comic 依赖的 Dify 实例**如何启动**、**配置与数据怎么导出导入**。Dify 是独立上游项目（官方源码 clone + 源码内 `docker/` 目录跑 compose），**不在本仓库编排内**；本仓库只负责调用它。
## 定位与依赖关系
Dify 承担对话编排：意图路由、知识库检索、漫画查询、以及把「改代码」指令转给 TaskBridge。两边是**双向依赖**：comic 调用 Dify 的 API，Dify 的 HTTP 节点又反调 comic 的宿主端口。
下表列出三个关键连接点。
| 方向 | 连接 | 说明 |
|---|---|---|
| comic → Dify | `http://<宿主>:80/v1/chat-messages` | LangBot 的 DifyAgent 用 `host.docker.internal/v1` + 应用 key |
| Dify → comic | `host.docker.internal:8000/api/comics` | 2 号线（漫画查询），需 `comic-app` 发布 8000 |
| Dify → comic | `host.docker.internal:8020/command` | 3 号线（改代码），需 `comic-taskbridge` 发布 8020 |
因此启动顺序是：先起 comic 的 API 与 TaskBridge，再起 Dify；否则 2/3 号线会命中异常分支返回「暂时不可用」。
## 前置条件
Dify 是 15 个容器的分布式系统（api / worker / worker_beat / web / plugin_daemon / sandbox / ssrf_proxy / nginx / postgres / redis / weaviate 等），不是单进程程序。
下表列出实测的资源与端口占用。
| 项 | 要求 / 实测 |
|---|---|
| 内存 | 实测 15 个容器合计约 2.3 GB，建议宿主 ≥ 8 GB |
| 磁盘 | 镜像约 6 GB + 数据 1.1 GB（plugin_daemon 977 MB 占大头） |
| 宿主端口 | 80（nginx 唯一入口）；内部服务不映射 |
| 依赖 | Docker + Compose v2（本机实测 v5.1.3） |
## 首次启动
官方方式是在**源码目录**里跑 compose，配置就跟着源码走。
```bash
git clone --depth 1 https://github.com/langgenius/dify.git /opt/dify
cd /opt/dify/docker
cp .env.example .env          # 再按需改 SECRET_KEY、数据库口令
docker compose -p docker up -d
```
本机路径是 `D:\software\RuoYi\dify\docker`，项目名 `docker` 由目录名推出，所以容器叫 `docker-api-1` 而不是 `dify-api-1`。首次启动会自动建库表结构，约 1~2 分钟。
## 日常启停
下表列出常用命令；项目名 `docker` 必须带上，否则会当成新项目重建一套。
| 操作 | 命令 |
|---|---|
| 起 / 重建 | `docker compose -f docker-compose.yaml -p docker up -d` |
| 看状态 | `docker compose -f docker-compose.yaml -p docker ps` |
| 停（保留容器） | `docker compose -f docker-compose.yaml -p docker stop` |
| 删容器（数据在 volumes 保留） | `docker compose -f docker-compose.yaml -p docker down` |
| 跟随日志 | `docker logs -f docker-api-1` |
也可用本仓库的封装脚本免记路径：`powershell -File scripts\stack.ps1 up dify`。
## 不要用 restart
`docker compose restart` **会忽略 `depends_on` 的顺序**，所有容器同时重启。实测后果：`plugin_daemon` 抢在 `db_postgres` 就绪前连接数据库，直接 `panic: failed to init dify plugin db` 退出并重启，期间整个 Dify 返回 503（约 1~2 分钟）。
正确做法是 `up -d`：对已运行的容器等价于「按依赖顺序处理变化」，不会抢跑。
## 配置构成
Dify 的配置不是单个文件，而是「一份 compose + 一棵 env 片段树」，缺一不可。
下表列出配置家族的职责。
| 路径（相对 `docker/`） | 作用 | 改动频率 |
|---|---|---|
| `docker-compose.yaml` | 16 个服务的编排（上游原版，本机未改） | 升级时随上游更新 |
| `.env` | 密钥与 profile：`SECRET_KEY`、数据库口令、`COMPOSE_PROFILES` | 每环境一份，**不入库** |
| `envs/`（42 个） | 各服务的环境变量：数据库、向量库、nginx、ssrf 代理等 | 调参时改 |
| `nginx/` | 反代模板与入口脚本 | 基本不动 |
| `ssrf_proxy/` | squid 配置，本项目加了 `cache deny all` | 本项目改过 |
| `volumes/` | 运行数据（db / weaviate / plugin_daemon / app storage） | 数据，不迁移配置时忽略 |
## 配置导出
配置总量约 180 KB，整目录打包即可；**必须连同 `envs/` 一起走**，只带 compose 会起不来。
```bash
cd /opt/dify/docker
tar czf dify-config.tgz docker-compose.yaml .env envs/ nginx/ ssrf_proxy/
```
导出后建议检查三点：`.env` 里的 `SECRET_KEY` 与 `COMPOSE_PROFILES` 是否保留；`ssrf_proxy/squid.conf.template` 末尾是否有 `cache deny all`；`envs/` 是否 42 个文件齐全。
## 数据导出
业务数据全在 Postgres；向量库与插件可选择「搬目录」或「重建」，后者更稳。
下表列出四类数据与推荐做法。
| 数据 | 位置 | 体积 | 推荐 |
|---|---|---|---|
| 业务库（应用 / 编排 / 知识库 / 会话） | `volumes/db/data` | 102 MB | **必须** `pg_dump` |
| 向量索引 | `volumes/weaviate` | 25 MB | 到新机器**重建索引** |
| 插件运行时 | `volumes/plugin_daemon` | 977 MB | 到新机器**重装插件** |
| 应用存储 | `volumes/app/storage` | ≈0 | 一般可忽略 |
导出业务库的做法：
```bash
docker exec docker-db_postgres-1 pg_dump -U postgres -d dify -Fc -f /tmp/dify.dump
docker cp docker-db_postgres-1:/tmp/dify.dump ./dify.dump
```
## 应用与编排导出
两类内容**不在 `pg_dump` 的可读形态里**，建议额外留一份文本备份。
| 内容 | 在哪 | 导出方式 |
|---|---|---|
| 应用编排（画布） | Postgres `workflows` 表 | 控制台 → 应用 → 「导出 DSL」，存 YAML |
| 知识库源文档 | 上传时的 md / pdf / xlsx | 从原始目录拷，或 `volumes/app/storage` |
| 应用 API Key | 控制台 → 应用 → API 访问 | 单独记录（DLSL 里不含 Key） |
DSL 只有编排结构，**不含知识库内容与 API Key**；三者要分别备齐才算完整。
## 在新机器导入
按「配置 → 起服务 → 恢复数据 → 重建检索」的顺序执行，顺序错了会浪费一轮索引。
```bash
# 1. 配置
git clone --depth 1 https://github.com/langgenius/dify.git /opt/dify
cd /opt/dify/docker
tar xzf dify-config.tgz            # 覆盖 compose 与 .env

# 2. 起服务（首次自动建表）
docker compose -p docker up -d
docker compose -p docker ps        # 等 api 变 healthy

# 3. 恢复业务数据（覆盖空库）
docker cp dify.dump docker-db_postgres-1:/tmp/
docker exec docker-db_postgres-1 pg_restore -U postgres -d dify --clean --if-exists /tmp/dify.dump
docker compose -p docker up -d     # 让 api/worker 重连

# 4. 控制台里重建知识库索引、重装插件
```
`SECRET_KEY` **必须与原环境完全一致**：Dify 用它加密存储模型 provider 的 API Key，换掉之后所有模型调用都会失败（表现为「密钥无效」而不是连接错误）。
## 迁移校验清单
切换后逐项核对，任何一项不符先回滚再看日志。
下表列出可量化的验收项。
| 检查 | 期望 | 命令 |
|---|---|---|
| 首页 | 200 | `curl -I http://localhost/` |
| 容器数 | 15 个 Up | `docker compose -p docker ps` |
| 应用数 | 4 | 控制台应用列表 |
| 知识库分段 | 225（本环境实测值） | 控制台知识库详情 |
| 模型可用 | 任一应用能跑通 | 控制台「调试与预览」 |
| comic 三线 | 1/2/3 均正常 | QQ 里各发一句 |
## 常见坑
**① 只拷 compose 不拷 `envs/`**：容器起不来或静默用错数据库，报错通常与「环境变量缺失」无关，很难一眼看出来。
**② `SECRET_KEY` 变了**：模型 provider 的 Key 解不开，日志是「invalid api key」类错误，容易被误判成网关问题。
**③ profile 与向量库不匹配**：`.env` 里 `COMPOSE_PROFILES` 要含 `postgresql,weaviate,collaboration`，且与 `VECTOR_STORE` 一致，否则对应服务不启动。
**④ squid 缓存掩盖故障**：`ssrf_proxy` 会缓存 GET 响应，后端挂了仍返回旧数据。本项目已在 `squid.conf.template` 里加 `cache deny all`，迁移时别漏。
**⑤ 用 `restart` 重启**：见上文「不要用 restart」，这会让 plugin_daemon 抢跑并导致整站 503。

**⑥ 跨机迁移的坑另有一份清单**：租户私钥文件、`dify_plugin` 库、squid 的宿主映射与 DNS 缓存、私网白名单等 10 条，见 [`deploy/docs/NOTES.md`](../deploy/docs/NOTES.md) 第三章「跨机迁移」。
