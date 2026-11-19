# TaskBridge

## 定位
把「QQ 群里一句话」变成「仓库里一次可审阅的改动」。它是 Dify 与 coding agent 之间的任务网关，**不参与对话理解**。

链路：`QQ → NapCat → LangBot（OneBot v11 流水线）→ Dify Chatflow → TaskBridge → opencode CLI + 模型`

## 模块结构
本模块是独立目录（不再挂在 `tools/` 下）：`run.py` 是入口，`taskbridge/` 是包本体。`run.py` 把自己的上级目录塞进 `sys.path`，所以 `python taskbridge-service/run.py` 就能直接跑，不需要安装成包。

```
taskbridge-service/
├── run.py               # 启动入口（uvicorn 由这里拉起）
├── README.md            # 本文件（导读）
├── docs/NOTES.md        # 踩坑与复盘
└── taskbridge/          # 包：config / store / workspace / agent / worker / commands / notify / main
```

它跑在 `comic-taskbridge` 容器里（见 `deploy/docker-compose.yml`）：仓库以**可写**方式挂到 `/repo`，镜像内同时装 python（服务本体）与 node（opencode 是 npm 包）。

## 为什么需要它
聊天窗口承载不了「改代码」这类长任务：Dify 的 HTTP 节点几十秒就超时、agent 可能跑飞、改动必须人工确认后才提交。TaskBridge 负责排队、校验、持久化与落地，四件事缺一不可。

## 两种模式
同一个入口按内容自动分派，避免「问问题却被当成改代码」：

| 模式 | 判定 | 行为 |
|---|---|---|
| `code` | 含改动类动词（改 / 加 / 删 / 修复 / 部署…） | 建分支 → agent 改文件 → 出 diff → **等人工确认** |
| `ask` | 问号结尾，或含疑问词（多少 / 哪些 / 为什么 / 在哪…） | **禁止改文件**，读代码后直接回答，答案入库并主动推送 |

## 分支模型
每个任务在主仓库里开一个分支 `tb/<任务号>`，coding agent 直接在工作区改；确认后在该分支提交，再把 `main` 快进过去、删分支，**并把 `main` 推到远端**。推送失败不回滚本地提交，错误会原样推送到 QQ（附处理命令）。丢弃则还原改动、切回 `main`、删分支。

```
POST /tasks  → git checkout -b tb/A49A189F → agent 改文件 → 采集 diff 并硬校验
             → awaiting_review（此时工作区停在任务分支上）
POST /apply  → git add/commit → git checkout main → git merge --ff-only → git branch -D
POST /discard→ git checkout -- <files> + clean → git checkout main → git branch -D
```

任务开始前就处于「已修改」状态的文件（你自己在改的东西）会被记为基线，**不纳入本次任务、也不会被提交**。

## 不变量（改实现前先读）
- **提交即返回**：`POST /tasks` 毫秒级返回任务号，绝不等待 agent 执行完成。
- **硬校验**：成败只看 `git status` 与 `diff`，**不采信模型的「done」**（实测有模型会谎报完成）。
- **人工确认**：`awaiting_review` 之后必须显式调 `/apply` 才提交。
- **应用即推送**：apply 合并后会自动把 `main` 推到远端，推送失败只把错误报到 QQ（本地提交保留）。
- **原子提交**：只提交本次任务涉及的文件，不裹挟工作区里其它未提交改动。

## 代价（选分支模型的必然结果）
- 任务期间**主仓库工作区就是改动现场**：同一时间只能有一个任务（并发固定为 1）；
- 本地跑着的服务会立刻看到 agent 的半成品改动；
- 任务未收尾前不要手工切分支或提交，否则 apply 会失败（会明确报错）。

## 上手命令
```bash
# 容器里跑（推荐）：部署编排已包含该服务
docker compose -f deploy/docker-compose.yml up -d comic-taskbridge
# 本机直跑（需要已装 opencode 与 fastapi/uvicorn）
python taskbridge-service/run.py
# 健康检查
curl http://127.0.0.1:8020/healthz
```

## 接口
下表列出对外接口。

| 接口 | 作用 |
|---|---|
| `POST /command` | **自然语言入口**：一句话完成提交/进度/应用/丢弃，返回可直接回给用户的 `reply` |
| `POST /tasks` | 提交任务，立即返回任务号（`action` / `prompt` / `allowed_paths`） |
| `GET /tasks/{id}` | 查进度（含任务分支名）；`?full=1` 连带完整 diff |
| `POST /tasks/{id}/apply` | 确认后落地：分支提交 → `main` 快进 → 推远端，需给 `message`（Conventional Commits）；推送失败写入 `push_error` 并推送到 QQ |
| `POST /tasks/{id}/discard` | 丢弃：还原改动、删任务分支 |

`/command` 支持的句式（Dify 只需一个 HTTP 节点）：

| 输入 | 动作 |
|---|---|
| `把首页轮播间隔改成 5 秒` | 当作新任务提交，回任务号 |
| `进度 A7F3` | 查状态（含改动文件与改动量） |
| `应用 A7F3` | 提交；可带自定义信息：`应用 A7F3 docs(web): 说明` |
| `丢弃 A7F3` | 放弃并删分支 |
| `帮助` | 用法说明 |

## 状态机
`queued → running → awaiting_review → applying → applied`；`ask` 模式走 `answered`；失败/放弃是 `failed` / `discarded`。服务重启时残留的 `running` / `applying` 会被标成失败，并把工作区还原到 `main`。

## 配置（环境变量）
下表列出影响运行位置与外部依赖的变量。

| 变量 | 默认 | 作用 |
|---|---|---|
| `TB_REPO_ROOT` | 仓库根 | 操作的 git 仓库（容器里是 `/repo`） |
| `TB_HOST` / `TB_PORT` | `0.0.0.0` / `8020` | 监听地址 |
| `TB_OPENCODE_BIN` | `opencode` | opencode 可执行文件（容器里是 `/usr/local/bin/opencode`） |
| `TB_XDG_ROOT` | `logs/taskbridge/ocdata` | opencode 的数据目录（**跨平台不通用**，容器里指到独立卷） |
| `TB_PUSH_BASE` / `TB_PUSH_TOKEN` / `TB_PUSH_TARGETS` | 空 | 主动推送通道（NapCat 的 OneBot HTTP） |
| `TB_GIT_PUSH` | `true` | apply 后是否自动把 `main` 推到远端 |
| `TB_GIT_REMOTE` / `TB_GIT_BRANCH` | `origin` / `main` | 推哪个远端、哪个分支 |
| `TB_GIT_PUSH_TIMEOUT` | `120` | 推送超时（秒），避免队列卡死 |
| `TB_KEY_ENV_FILE` / `TB_KEY_ENV_NAME` | `chat-service/.../.env` / `COMIC_LLM_API_KEY` | 模型密钥来源（不落盘到别处） |

## 已踩过的坑
踩坑细节见 [docs/NOTES.md](docs/NOTES.md)（opencode 日志目录不可写、worktree 副本失效、容器里 git 把整仓看成已修改等）。
