# deploy · 知识库（AI 维护）

> 本文件是 deploy 的**踩坑与知识沉淀**，由 AI 协作时维护 ——
> **每次踩坑 / 实测 / 复盘写到这里**，不再写进 `README.md`（README 只放模块框架、约定与用途，给人看）。
> 具体逻辑由源码注释解释维护，这里只放「为什么」与「踩过的坑」。
> ⚠️ **部署操作须知**（环境变量、构建上下文、卷的坑）集中在 README 的「几个不显然的点」——
> 那是"做之前必须知道"的；本文件只放**做完之后才知道的**（实测、复盘）。

## 条目模板（新增知识时按此写）

```markdown
#### 标题（一句话说清是什么）

- **日期**：YYYY-MM-DD（多个用 ` / ` 分隔）
- **背景 / 现象**：发生了什么（决策类写"当时的背景"）
- **根因**：为什么会这样（决策类写"为什么这么定"）
- **结论**：怎么解决 / 最终决定是什么
- **实测**（可选）：关键数字 / 验证方式
- **位置**（可选）：涉及的文件 / 页面
```

---

## 一、历史决策

### 1.1 comic-web 镜像部署下线（2026-10-10）

- **背景 / 现象**：原有两个前端镜像（`deploy/web` + `deploy/front`）。
- **根因**：comic-front 支持移动 / 网页双形态后，一个镜像覆盖两个端 —— 没必要维护两份。
- **结论**：`deploy/web/` 已删除，compose / build 脚本里不再有 `comic-web` 服务与 `WEB_PORT`；
  旧前端保留在仓库里仅作参考实现。

> ⚠️ 2026-10-14 复核更正：本节决策**已被推翻** —— comic-web 以纯 Vue3 重写（蓝本取自 comic-front），`deploy/web/` 回归、compose / build 脚本重新有 `comic-web` 服务与 `WEB_PORT`，两个前端镜像功能等价（宿主 85 / 86）。本节仅作 2026-10-10 当时的决策留档。

---

## 二、踩坑记录

### 2.1 wheel 重建的字节漂移让镜像层缓存每轮失效（"每次构建都在重新下载依赖"）

- **日期**：2026-10-14
- **背景 / 现象**：用户感觉"每次跑 up.sh 都要花很长时间下载依赖"；按预期源码没变时不该重复下载。
- **根因**（两条，互相叠加）：
  1. **wheel 重建的字节漂移（主因）**：`build.sh` 每轮**无条件重建 wheel**，而 `pip wheel` 默认把
     **构建时刻**写进 whl 的 zip 时间戳 —— 同样源码重建出的 whl **字节不同**（实测 md5 每次都变、
     大小相同）→ 三个 Python 镜像里 `COPY dist/` 的层缓存每轮失效 → 后面的 `pip install` 层跟着
     重跑；构建缓存冷时就是全部依赖重新下载（30 个包）。
  2. **scheduler 层 pip 没挂缓存**：`deploy/scheduler/Dockerfile` 用的是 `pip install --no-cache-dir`
     且**没有** `--mount=type=cache`（crawler / api 两层都有）—— 该层每次重跑都全量重新下载
     （实测同样 17 个包：crawler 层全 "Using cached"、scheduler 层全 "Downloading"）。
- **结论**：
  1. `build.sh` 在构建 wheel 前固定 `SOURCE_DATE_EPOCH`（可复现构建标准变量，默认 `0`）——
     源码不变时 whl 逐字节一致 → `COPY`/`pip` 层全部命中缓存；
  2. `scheduler/Dockerfile` 对齐 crawler / api：加 `--mount=type=cache,target=/root/.cache/pip`、
     去掉 `--no-cache-dir`。
- **实测**：
  | 场景 | 修复前 | 修复后 |
  |---|---|---|
  | comic-api 镜像：构建缓存冷 | **169s**（30 包全下载，cryptography 4.8MB 花了 33s） | — |
  | comic-api 镜像：输入不变 | — | **5~6s 全 CACHED** |
  | comic-api 镜像：wheel 重建（字节不变） | 每轮重跑 pip 层 | **6s 全 CACHED**（含 pip 层） |
  | comic-scheduler 镜像：层重跑 | **62s**（17 包全下载） | **10s**（17 包全缓存）→ 再跑 4s 全 CACHED |
- **位置**：`deploy/build.sh`（`build_wheel` 之前的 `export SOURCE_DATE_EPOCH`）、
  `deploy/scheduler/Dockerfile`（pip 行）；机理涉及各 `deploy/*/Dockerfile` 的 COPY→pip 层序。

> 附注（2026-10-15 已治）：`# syntax=docker/dockerfile:1.4` 会让每轮构建去拉"语法镜像"
> （docker/dockerfile）的元数据 —— 镜像源抽风时（daocloud 502）直接挂构建（服务器实测：
> 卡 121s 后报 502，api / crawler 两处都挂）。已删掉这两处该行、改用 BuildKit 内置前端
> （scheduler / mysql / web / front 本来就没这行、一直构建正常 —— 即内置前端足够）。
> ⚠️ 以后新增 Dockerfile 不要加 `# syntax=`；切换前端版本属一次性缓存失效（实测一轮 32s，
> 之后恢复全缓存）。

### 2.2 构建"时好时坏"的镜像源根因（已由 §2.3 根治）

- **日期**：2026-10-15
- **现象**：同一份代码，构建有时通、有时挂 —— 报错集中在
  `[internal] load metadata for ...` / `resolve image config for ...` + `502 Bad Gateway`。
- **机制（实测）**：BuildKit 每轮构建都会"解析基础镜像"，**本地镜像库已有该镜像时是纯本地操作、
  零网络**（用 DNS 无法解析的假域名 + 本地镜像实测构建成功）；缺镜像时才会走网络 ——
  撞上 daocloud 间歇抽风（502）即挂。另：Dockerfile 里 `m.daocloud.io/...` 是**直连引用**，
  与 daemon 的 `registry-mirrors` 配置无关（加速器只作用于 `docker.io` 官方名）。
- **过程方案（均已被 §2.3 取代，留档）**：① 离线 save/load 转移基础镜像；② 等镜像源恢复带重试补拉；
  ③ 配阿里云加速器（daemon.json）。

### 2.3 基础镜像改从本项目 ACR 拉取（根治"看镜像源脸色"）

- **日期**：2026-10-15
- **决策**：三个基础镜像（`python:3.13-slim` / `nginx:alpine` / `mysql:8.0`）推送到本项目 ACR
  （`crpi-zu4tna9y8drenzc4.cn-hangzhou.personal.cr.aliyuncs.com/comic-website`），
  6 个 Dockerfile 的 `FROM` 直接引用 ACR（不再出现 `m.daocloud.io`）。
- **配套**：`deploy/push-base-images.sh` —— 首次搭建 / 基础镜像升级时推送用（日常构建不跑）。
  ⚠️ 仓库为**私有**（个人版推送自动创建的仓库默认私有）——**服务器需先 `docker login` 一次**
  （凭证持久保存，之后构建自动带上）；或把三个仓库改为公开可免登录。
  > ⚠️ 2026-10-15 复核更正：此前"公开可拉"是误判（当时只查"有没有 token"、未解码权限）。
### 2.4 新机器首次构建 comic-app 会因 ACR 未登录而失败
- **日期**：2026-11-19
- **现象**：`docker compose -f deploy/docker-compose.yml build comic-app` 报
  `pull access denied ... crpi-zu4tna9y8drenzc4.cn-hangzhou.personal.cr.aliyuncs.com/comic-website/python:3.13-slim`；
  ACR 主机本身是通的（匿名请求 `/v2/` 返回 401，说明网络没问题、只是缺认证）。
- **原因**：ACR 仓库为私有，本机 `~/.docker/config.json` 里没有任何 `auths` 记录。
- **处理**：`docker login crpi-zu4tna9y8drenzc4.cn-hangzhou.personal.cr.aliyuncs.com`
  （用户名=阿里云账号或 RAM 子账号；密码=ACR 控制台「访问凭证」里的**固定密码**，不是阿里云登录密码）。
  登录后凭据持久保存，之后构建自动带上。
- **临时替代**：`deploy/api/Dockerfile` 的 `FROM` 已参数化为 `ARG BASE_IMAGE`（默认 ACR）。
  没有凭据时可临时 `--build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.13-slim`，
  或在 `deploy/.env` 里设 `COMIC_BASE_IMAGE` 覆盖 —— 但那样底座与线上不同源，只适合联调。
- **核对方式**：`docker image inspect comic-api:1.0.0 --format '{{json .RootFS.Layers}}'` 的前 4 层
  应与 ACR 基础镜像完全一致（2026-11-19 实测一致）。
  > 纯匿名实测：token 为空权限（`access: []`）、匿名拉 manifest 被 401 拒。
- **基础镜像升级流程**（以后要动版本时）：
  1. 本机拉新版本（如 `docker pull python:3.14-slim`），同步改 `push-base-images.sh` 里的标签；
  2. `bash deploy/push-base-images.sh` 推到 ACR；
  3. 改 6 个 Dockerfile 的 `FROM` 标签（python 三处 / nginx 两处 / mysql 一处）；
  4. 正常 `up.sh` 构建（自动从 ACR 拉新版）。
- **实测**（2026-10-15）：三镜像推送 `PUSH-ALL-OK`；**6 个镜像全部重建成功**、日志 `m.daocloud`
  引用数 **0**；匿名拉取复核：token 为空权限、manifest 被 401 拒（→ 私有，服务器需登录）。

---

## 三、跨机迁移（Dify + QQ 机器人，2026-11-19 实测）

把本地一套（Dify 15 容器 + NapCat + LangBot + comic 全栈）搬到一台干净的 Ubuntu 服务器，踩了下面九个坑。
**顺序即排查顺序**：前一个没解决，后一个根本不会暴露。
判断"哪一环断了"的经验：`docker logs <容器> | grep -E 'error|Error|失败'` 先看**最靠近数据源**的那个容器。

### 3.1 Dify 的租户私钥不在数据库里，`pg_dump` 搬不走

- **现象**：库、插件、向量数据都搬完了，页面能打开、应用都在，但任何对话都 500：
  `Exception: Private key not found, tenant_id: <uuid>`。
- **根因**：租户 RSA 私钥是**文件** `volumes/app/storage/privkeys/<tenant>/private.pem`，
  Dify 用它解密 provider 凭据；单独的 `pg_dump` 只有表数据。
- **结论**：迁移清单必须包含 `volumes/app/storage`（很小，实测 56KB，含 `privkeys/` 与
  上传的原始文档 `upload_files/`）。
- **实测**：补上 `storage.tgz` 后解压到 `volumes/app/storage`，重启 api，对话恢复。

### 3.2 插件状态在**另一个数据库** `dify_plugin`

- **现象**：对话报 `Provider langgenius/xxx/xxx does not exist`，但 `dify` 库里 `providers` 表明明有记录。
- **根因**：Dify 1.x 把插件守护进程的状态单独放在 `dify_plugin` 库（`plugins` /
  `plugin_installations` / `plugin_declarations`），只导 `dify` 会丢。
- **结论**：`pg_dump -d dify` 与 `pg_dump -d dify_plugin` **两份都要**；
  目标机先 `create database dify_plugin;` 再 `pg_restore`。
- **实测**：`dify` 8.3MB、`dify_plugin` 51KB；导入后 `plugins` 4 行、`plugin_installations` 4 行。

### 3.3 `host.docker.internal` 在 Linux 上不存在，而且**代理容器也要加**

- **现象**：工作流里的 HTTP 节点全部失败，返回"服务没有响应"。
- **根因**：① 这个域名是 Docker Desktop 特供，Linux 无；② 节点的请求**经 `ssrf_proxy`（squid）出网**，
  只给 `api` / `worker` 加映射不够，squid 自己解析不到就直接回 503。
- **结论**：`api` / `worker` / `api_websocket` / `ssrf_proxy` / `agent_ssrf_proxy` **五个服务**都要
  `extra_hosts: ["host.docker.internal:host-gateway"]`；用 `docker-compose.override.yaml` 覆盖，
  不要改上游 `docker-compose.yaml`。
- **实测**：缺 squid 时 `access.log` 里是 `TCP_MISS/503 ... HIER_NONE/-`；补上后 200。

### 3.4 squid 会缓存 DNS，容器重建后把请求发到旧 IP

- **现象**：改成服务名直连后，工作流报"暂时不可用"，但容器间 `curl` 是通的。
- **根因**：`comic-app` / `comic-taskbridge` 重建后 IP 互换，squid 缓存了旧解析，
  `access.log` 显示 `HIER_DIRECT/<旧IP>`。
- **结论**：`ssrf_proxy/squid.conf.template` 末尾加 `positive_dns_ttl 30 seconds` +
  `negative_dns_ttl 0 seconds`，最多 30 秒自愈；改完必须重建 `ssrf_proxy` 容器。
- **实测**：改前 503 且指向旧 IP，改后 200。

### 3.5 私网白名单要按目标机改写，不能照抄本地

- **现象**：SSRF 层拒绝内网地址，HTTP 节点全挂。
- **根因**：`.env` 里 `SSRF_PROXY_ALLOW_PRIVATE_IPS` 默认是 Docker Desktop 的
  `192.168.65.254/32`，与 Linux 宿主网关 `172.17.0.1` 不匹配。
- **结论**：服务器上改成 `172.17.0.1/32,172.18.0.0/16`（前者是宿主网关，后者是编排网段）；
  想让 squid 认**服务名**再加 `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=comic-app,comic-taskbridge`。
- **实测**：容器内 `grep 172.17 /etc/squid/dify_allow_private.conf` 能看到生效行。

### 3.6 LangBot 主服务与插件运行时的版本必须一致，且**数据库要配套**

- **现象**：消息能收到、也回了，但内容永远是 `Agent runner execution failed.`；
  主服务日志刷 `Plugin runtime did not become ready within 180 seconds`。
- **根因**：本地镜像 `v4.11.8`、服务器拉的是 `v4.11.9`。新版把库升到
  `0053_knowledge_artifact_sources` 之后，旧版代码直接 `ResolutionError: No such revision`；
  新版配旧库又会插件握手超时。
- **结论**：`rockchin/langbot` **不要用 `latest`**，固定成 `v4.11.8`（`LANGBOT_IMAGE_TAG` 可覆盖），
  且数据库与镜像**同一版本**；从旧机器搬库时连同 `langbot.db-wal` 一起搬。
- **实测**：`latest`（11-18 构建）→ 握手超时；`v4.11.8`（镜像 ID 与本地一致）→ 秒连。

### 3.7 插件依赖在容器里现装，默认 PyPI 会让握手超时

- **现象**：运行时日志停在 `Ensuring all installed plugins dependencies are installed...`，
  之后没有下文，主服务判定超时。
- **根因**：插件环境用 `pip`/`uv` 现装依赖，国内直连 PyPI 只有几十 KB/s，
  装不完 180 秒就绪窗口。
- **结论**：给 `comic-langbot` 与 `comic-langbot-runtime` 都加
  `PIP_INDEX_URL` / `UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`。
- **实测**：同样两个插件，改源前卡十几分钟、改源后 1 分钟内装完。

### 3.8 `DifyAgent` 插件跑在**运行时容器**里，宿主映射漏在它身上

- **现象**：`Dify runner error: [Errno -2] Name or service not known`；
  补上宿主映射后又变成 `All connection attempts failed`（能解析但连不上 80）。
- **根因**：① 插件不在 `comic-langbot` 里执行，而在 `comic-langbot-runtime` 里，
  后者没加 `host.docker.internal`；② 改端口后插件里存的 `base-url` 仍是旧的 80。
- **结论**：`comic-langbot-runtime` 也要 `extra_hosts`；Dify 换端口时，
  **LangBot 数据库里 `legacy_pipelines.config` 的 `base-url` 要同步改**（它不读环境变量）。
- **实测**：`curl http://host.docker.internal:8088/v1/parameters` 带 key 返回 200 才算通。

### 3.9 推送 token 少一个 `=`，NapCat 一律 403

- **现象**：任务改完但用户收不到通知，TaskBridge 日志 `[notify] private:xxx 推送失败：HTTP Error 403`。
- **根因**：NapCat 的 OneBot HTTP token 是 33 位 base64（**结尾带 `=`**），
  抄进 `.env` 时少了填充符，只剩 32 位。
- **结论**：`TB_PUSH_TOKEN` 必须与 `napcat/config/onebot11_<QQ>.json` 里
  `network.httpServers[0].token` **逐字符一致**；改完重建 `comic-taskbridge` 才生效。
- **实测**：33 位 → 200；32 位 → 403。核对方式：
  `docker exec comic-taskbridge python3 -c "import os;print(len(os.environ['TB_PUSH_TOKEN']))"`。

### 3.10 容器 `core.autocrlf=true` 会让"丢弃"后整份文件显示被改写

- **现象**：任务改 3 行、执行「丢弃」后，`git status` 仍有改动，
  `git diff --stat` 是 `638 insertions(+), 638 deletions(-)`。
- **根因**：仓库索引是 LF，容器全局 `core.autocrlf=true`，checkout 任务分支时把文件写成 CRLF；
  丢弃还原后工作区仍是 CRLF，于是整份文件都"变了"。此时若误用 `git add -A` 会把整仓重写。
- **结论**：容器里设 `core.autocrlf false`（`deploy/taskbridge/Dockerfile` 已改）。
  已污染的工作区修法：容器/宿主仓库级设 `core.autocrlf false` 后 `git checkout -- <文件>`。
- **实测**：修复前后同一文件的 `diff_stat` 从 `638 insertions(+)` 变成 `1 insertion(+)`。

---