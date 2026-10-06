# comic-scheduler —— 定时任务执行器（独立进程）

读管理台「定时任务」栏配的 **5 段 cron**，到点对选中的数据源跑采集，并把运行态写回文件供页面展示。

**为什么独立成进程**（2026-10-06 定）：执行器此前是 api 进程里的一个后台线程，**随 api 生死** ——
api 重启/重部署时定时采集会中断，采集负载也与请求处理抢同一个 Python 进程。搬出来之后：

- 采集与接口**生命周期解耦**（api 滚动更新不影响定时采集）；
- 定时执行器可以单独重启、单独扩缩、单独看日志；
- 容器名沿用编排里既有的 **`comic-scheduler`**（不再藏在 `comic-app` 里）。

## 与 api 的分工：只通过三个文件交换

| 文件（都在运行时数据目录 `<data>/`） | 写者 | 读者 | 内容 |
|---|---|---|---|
| `schedule.json` | api（页面保存） | **本进程** | 配置：enabled / cron / sources / mode / limit / since |
| `schedule_state.json` | **本进程** | api（页面展示） | 运行态：running / 上次结果 / 本轮源 / 心跳 / cron 错误 |
| `schedule_run_now.json` | api（「立即执行一次」按钮） | **本进程**（读到即删） | 触发请求 |

⚠️ **一个文件一个写者**是这个设计的核心：两个进程同时写同一个 JSON 会互相截断，
所以"触发"走独立文件而不是往状态文件里塞字段。读写实现见
[`crawler-service/src/comic_crawler/scheduling/schedule_state.py`](../crawler-service/src/comic_crawler/scheduling/schedule_state.py)。

## 与管理台手动触发的一致性

两边最终调的是**同一个函数** `comic_crawler.scheduling.runner.sync_source`
（本进程走 `run_round`，api 的 `admin_jobs.sync_job` 是它的薄包装）——
所以存储句柄、`mode`/`limit`/`since`、统计口径**构造上一致**，不靠人工对齐。

## 一轮干什么：`action`

配置里的 `action` 决定这一轮的动作（`run_round` 内部分派，**两者返回同一形状**，含人话
`summary`，所以执行器与任务表都不必关心差异）：

| 值 | 走什么 | 说明 |
|---|---|---|
| `sync`（默认） | 逐源 `sync_source` | 单源失败不拖累其他源；`mode`/`limit`/`since` 生效 |
| `inspect` | 一次 `inspect_sync` | 失效巡检：转存未转存页 + **全表**校验 + 恢复丢失。⚠️ **不含**管理台手动巡检的第 3 步「全库封面自愈」（那步偏重，巡检频率高，不该每次都多打源站请求）。`sources` **恰好点名一个源**才限定范围，否则全库/全源；`since` 是**转存**窗口下界（校验始终全表） |

## 每一轮都进任务表

跑之前往 `admin_task` 插一行 `running`，跑完改成 `done`/`failed`（`task_type=schedule`），
并往**消息中心**发一条（`POST /api/messages`，收件范围 = 管理员及以上）——
所以定时轮次在管理台能看到两次：跑的时候是"进行中"条目，跑完变成一条带结果的消息
（采集管理页原来那块「最近任务」2026-10-06 已并入消息中心）：

- **归属**：定时轮次没有账号 → 记「系统（定时）」；「立即执行一次」记**点按钮的那个人**
  （账号由触发请求文件带过来，`requestTime/userId/username`）。
- **`params` 快照**：`trigger` / `action` / `sources` / `mode` / `limit` / `since` —— 复盘"当时配的是什么"。
  **同一份入参也会随消息发出去**（`publish_message(params=…)`）：消息中心每条任务消息都显示
  `入参：起始 … · 增量 · 上限 …`，一眼看出这轮数据的时间范围。
- ⚠️ **落库失败只记日志**：任务表是**可观测性**，不是采集的前置条件（连不上库照跑）。
- ⚠️ **任务号必须带随机后缀**（`comic_core.logctx.new_task_id`，与 api 侧同一套规则）：
  定时器一轮接一轮，只用秒级时间戳会撞 `admin_task` 的唯一键 —— 实测同一秒内第二轮直接
  `Duplicate entry`，且它的收尾会**覆盖第一轮的行**。

## 基础命令

```bash
# 环境：复用项目自带的 venv（依赖已由 comic-core / comic-crawler 传递进来）
# ⚠️ 两个本地包不在 PyPI 上，本机直跑要把两个 src 放进 PYTHONPATH（或各做一次 editable 安装）：
export PYTHONPATH=../crawler-service/src:../comic-core/src      # PowerShell: $env:PYTHONPATH="../crawler-service/src;../comic-core/src"

# 前台跑（Ctrl+C 退出）；改完配置 ≤5s 生效，不必重启
python -m comic_scheduler          # 等价于控制台脚本 comic-scheduler

# 只跑一轮就退出（排查用：不看 cron，立刻跑一次配置里的源）
python -c "from comic_scheduler.daemon import *; import comic_crawler.facade as f; run_once(f.load_schedule_config(), '手动')"
```

容器里由 compose 的 `comic-scheduler` 服务启动（`python -m comic_scheduler`），
配置与状态都落在 bind 到 `/data` 的宿主运行时数据目录，**与本地直跑读写同一批文件**。

## 约定（改动前先读）

- **错过不补**：进程当时没在跑（或已过 300s 宽限窗口）→ 这一轮跳过。要补就点页面上的
  「立即执行一次」（它写触发文件，本进程在下一个 tick 内看到就跳一轮）。
- **表达式非法**：本轮**不跑**，原因写进运行态（页面会显示红字），**不静默回落**成某个默认表达式
  —— 猜错用户意图比不跑更糟。
- **先记 `lastRunTs` 再跑**：所以进程中途被杀也不会把同一轮重跑一遍；启动时若看到
  `running=true`（上次没跑完）会复位并打一条 warning。
- **心跳**：没有变化时每 60s 写一次运行态；页面可据此判断执行器是否还活着。
- **日志落库**：本进程也装了 `log_record` 的 Handler，所以管理台「日志查询」页能按
  `event=schedule.run` / `task_id=schedule-<时间戳>-<随机>` 筛到定时执行的日志；
  同一轮的**状态**在任务表 `admin_task`（见上节）。
- **依赖方向**：`scheduler → crawler → core`，**不依赖 api-service**。改这里不影响接口层的分层断言；
  反之 api 只认 facade 契约面（见 `api-service/README.md` 与 `test_crawler_boundary.py`）。
