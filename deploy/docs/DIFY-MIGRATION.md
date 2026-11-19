# Dify 并入 comic 编排：迁移与上线
本文件说明 Dify 如何并入本仓库的 compose、迁到服务器时要带哪些东西、切换与回滚步骤。踩坑细节见 `NOTES.md`，不在此重复。

## 为什么并入
Dify 是独立上游项目（`langgenius/dify` 的 clone），但它的**部署配置**只有 133KB、变更极少，而**运行数据**在 `volumes/` 与数据库里。把编排并进本仓库后，服务器上只需 clone 一个仓库、跑一条 `docker compose up -d`，运维面收敛成一处。源码仍由官方提供（服务器上 `git clone` 或直接用镜像），**不进本仓库**。

## 目录与文件
并入后 Dify 相关的文件都在 `deploy/dify/` 与本目录的 compose 片段里。

| 路径 | 作用 | 进版本库 |
|---|---|---|
| `deploy/docker-compose.dify.yml` | 从上游 compose 生成的 16 个服务片段（由 `tools/gen_dify_compose.py` 产出，勿手改） | ✅ |
| `deploy/dify/envs/` | 42 个环境变量片段（数据库、向量库、各服务） | ✅ |
| `deploy/dify/nginx/`、`ssrf_proxy/` | 反代与出网代理配置（含 `cache deny all` 补丁） | ✅ |
| `deploy/dify/.env.example` | 密钥模板 | ✅ |
| `deploy/dify/.env` | 真实密钥（`SECRET_KEY`、数据库口令等） | ❌ 已 gitignore |
| `DIFY_VOLUMES` 指向的目录 | 运行数据（db / weaviate / plugin_daemon） | ❌ 数据不入库 |

## 服务器上要导入的东西
迁移时真正要带走的是四类，合计约 8MB（不含可选 1GB）。

| 类别 | 内容 | 体积 | 是否必须 |
|---|---|---|---|
| 编排与配置 | `deploy/`（compose、`dify/envs`、`dify/nginx`、`dify/ssrf_proxy`、`.env.example`） | ≈180KB | 必须 |
| 环境密钥 | `deploy/dify/.env`（含 `SECRET_KEY`、`DB_PASSWORD`、插件 token） | 1.2KB | 必须 |
| 业务数据 | `pg_dump -Fc` 导出的 Dify 库 | 7.6MB | 必须 |
| 知识库源文件 | 建库时上传的 md/pdf/xlsx（本仓库 `deploy/dify/knowledge/` 或原始目录） | 视内容 | 建议 |
| 向量数据 | `volumes/weaviate`（25MB） | 25MB | 可选，推荐重建 |
| 插件 | `volumes/plugin_daemon`（977MB） | 977MB | 可选，推荐重装 |

其中**应用编排（画布）不在文件里**：它在 Postgres 的 `workflows` 表，随 pg_dump 一起走；另外建议在 Dify 界面「导出 DSL」存一份 YAML 作为可读备份。

## 服务器上线的步骤
依赖顺序不能变：先放配置、再起服务、最后恢复数据。

```bash
# 1. 取配置（仓库已含编排）
git clone <comic 仓库> /opt/comic && cd /opt/comic/deploy

# 2. 准备密钥：从本地 .env 拷过来（SECRET_KEY 必须与原环境一致，否则已存的模型 Key 解不开）
cp dify/.env.example dify/.env && vi dify/.env

# 3. 在 .env 里指定数据目录与 profile
echo 'DIFY_VOLUMES=/srv/dify/volumes' >> .env
echo 'COMPOSE_PROFILES=weaviate,postgresql,collaboration' >> .env

# 4. 起服务（首次会自动建库表结构）
docker compose up -d

# 5. 恢复业务数据（覆盖建好的空库）
docker exec -i comic-dify-db_postgres-1 pg_restore -U postgres -d dify --clean --if-exists < dify.dump

# 6. 重建知识库索引（若没搬 weaviate）：Dify 控制台 → 知识库 → 重新索引
# 7. 重装插件（若没搬 plugin_daemon）：控制台 → 插件 → 按需安装
```

## 本地切换步骤
本机的 Dify 现在跑在独立项目 `docker` 下，切到合并编排要一次停机。

```powershell
# 1. 停旧项目（只停不删，秒级可回滚）
docker compose -f D:\software\RuoYi\dify\docker\docker-compose.yaml -p docker stop

# 2. 用合并后的编排起（容器名被固定成 docker-*，故仍叫 docker-api-1）
docker compose -f deploy/docker-compose.yml up -d

# 3. 校验：首页 200 + 数据指纹
#    apps=4 datasets=4 documents=20 segments=225 workflows>=22
# 4. 确认无误后清掉旧容器
docker compose -f D:\software\RuoYi\dify\docker\docker-compose.yaml -p docker down
```

## 校验清单
切换后逐项确认，任何一项不符就回滚。

| 检查 | 期望 |
|---|---|
| `curl -I http://localhost/` | 200 |
| 数据指纹 | apps 4 / datasets 4 / documents 20 / segments 225 |
| Dify 控制台登录 | 可进，四个应用都在 |
| 三条线 | `1 端口` / `2 黑猫…` / `3 帮助` 均正常 |
| 模型调用 | 任一应用能跑通（验证 `SECRET_KEY` 未变） |

## 回滚
`docker compose -f deploy/docker-compose.yml stop` 后对新编排 `down`，再 `docker compose -p docker ... up -d` 起回旧项目即可。数据始终在 `DIFY_VOLUMES` 指向的目录里，两边读写同一份，不会丢。
