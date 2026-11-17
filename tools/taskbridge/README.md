# TaskBridge

## 定位
把「QQ 群里一句话」变成「仓库里一次可审阅的改动」。它是 Dify 与 coding agent 之间的任务网关，**不参与对话理解**。

链路：`QQ → NapCat → LangBot（OneBot v11 流水线）→ Dify Chatflow → TaskBridge → opencode CLI + 模型`

## 为什么需要它
聊天窗口承载不了「改代码」这类长任务：Dify 的 HTTP 节点几十秒就超时、agent 可能跑飞、改动必须人工确认后才提交。TaskBridge 负责排队、校验、持久化与落地，四件事缺一不可。

## 分支模型
每个任务在主仓库里开一个分支 `tb/<任务号>`，coding agent 直接在工作区改；确认后在该分支提交，再把 `main` 快进过去并删分支。丢弃则还原改动、切回 `main`、删分支。

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
- **原子提交**：只提交本次任务涉及的文件，不裹挟工作区里其它未提交改动。

## 代价（选分支模型的必然结果）
- 任务期间**主仓库工作区就是改动现场**：同一时间只能有一个任务（并发固定为 1）；
- 本地跑着的服务会立刻看到 agent 的半成品改动；
- 任务未收尾前不要手工切分支或提交，否则 apply 会失败（会明确报错）。

## 上手命令
```bash
# 启动（默认 0.0.0.0:8020）
python tools/taskbridge/run.py
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
| `POST /tasks/{id}/apply` | 确认后落地并提交，需给 `message`（Conventional Commits） |
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
`queued → running → awaiting_review → applying → applied`，另有两个终态 `discarded` / `failed`。服务重启时残留的 `running` / `applying` 会被标成失败，并把工作区还原到 `main`。

## 已踩过的坑
**① coding agent 的日志目录可能不可写**：opencode 默认写 `~/.local/share/opencode/log`，在受限沙箱或只读 HOME 下会直接报 `FileSystem.open` 退出。解决办法是把 `XDG_DATA_HOME` / `XDG_CACHE_HOME` / `XDG_CONFIG_HOME` 重定向到本服务自己的目录（`logs/taskbridge/ocdata`）。

**② 曾经用 worktree 做副本，结果 agent 改到了主仓库**：worktree 的 `.git` 只是指针文件，`--git-common-dir` 会指回主仓库，agent 据此把工程根判成主仓库，改动全落在主仓库、副本里 diff 为空。现在改用分支模型，不再有副本，这个坑随之消失；但仍保留「改动路径白名单 + diff 非空 + 文件数上限」三道硬校验。
