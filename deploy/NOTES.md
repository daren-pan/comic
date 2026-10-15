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
  > 纯匿名实测：token 为空权限（`access: []`）、匿名拉 manifest 被 401 拒。
- **基础镜像升级流程**（以后要动版本时）：
  1. 本机拉新版本（如 `docker pull python:3.14-slim`），同步改 `push-base-images.sh` 里的标签；
  2. `bash deploy/push-base-images.sh` 推到 ACR；
  3. 改 6 个 Dockerfile 的 `FROM` 标签（python 三处 / nginx 两处 / mysql 一处）；
  4. 正常 `up.sh` 构建（自动从 ACR 拉新版）。
- **实测**（2026-10-15）：三镜像推送 `PUSH-ALL-OK`；**6 个镜像全部重建成功**、日志 `m.daocloud`
  引用数 **0**；匿名拉取复核：token 为空权限、manifest 被 401 拒（→ 私有，服务器需登录）。
