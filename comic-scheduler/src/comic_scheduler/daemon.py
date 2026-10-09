"""定时任务执行器的主循环 —— 每 `TICK_SECONDS` 看一次表。

## 一轮的生命周期

1. 读配置（`schedule.json`，api 写的）与运行态（`schedule_state.json`，本进程写的）；
2. **手动请求优先**：有 `schedule_run_now.json` 就**先消费再跑**（避免下一 tick 重复触发），不看 cron；
3. 否则按 cron 判定（`facade.is_due` = 命中 + 未跑过 + 未过宽限窗口）；
4. **跑之前**先把 `lastRunTs` 与 `running=true` 落盘 —— 进程中途被杀也不会把同一轮重跑一遍；
5. 用 `facade.run_round` 跑一轮，**动作由配置的 `action` 决定**：`sync` 逐源采集 / `inspect` 失效巡检
   （两者返回同一形状，含人话 `summary`）；
6. 跑完把结果写回运行态**与任务表 `admin_task`**（管理台「最近任务」据此显示：谁触发的、在跑还是完了）；
7. 采集轮若有「真有新章节」的作品，给**收藏者**发更新通知（消息中心，走 HTTP，见 `_notify_fans`）；
8. 平时每 60s 刷一次心跳（页面据此判断执行器在不在线）。

**归属**：定时轮次没有账号 → 记「系统（定时）」；「立即执行一次」用**点按钮的人**（账号由请求文件带来）。

**错过不补**：进程当时没在跑（或已过宽限窗口）→ 这一轮跳过，要补就点页面上的「立即执行一次」。
**表达式非法**：本轮不跑，原因写进运行态（页面显示红字），不静默回落、也不乱跑。

## 退出

收到 SIGINT / SIGTERM 干净退出（`docker stop` 靠这个）。退出时**不**把 `running` 复位 ——
下次启动看到 `running=true` 就顺手复位并打一条"上次没跑完"的日志（比静默留着更可信）。
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime

from comic_core.logctx import new_task_id
from comic_crawler.facade import (
    consume_run_now,
    default_sources,
    is_due,
    load_schedule_config,
    load_schedule_state,
    run_round,
    save_schedule_state,
)

logger = logging.getLogger("comic.scheduler")

#: 看表间隔（秒）。它只是"多久检查一次"，不是业务参数 —— 所以不进管理台配置。
#: 取 5s：既让「立即执行一次」几秒内就动起来，读两个小 JSON 的代价也微不足道。
TICK_SECONDS = 5

#: 心跳写入间隔（秒）：页面据此判断执行器是否还活着。没有变化时不必每 tick 都写文件。
_HEARTBEAT_SECONDS = 60

_stop = threading.Event()
_last_heartbeat = 0.0
_cron_error: str | None = None


def _setup_logging() -> None:
    """日志：带时间戳；顺带落一份到 `log_record`，让管理台「日志查询」页能筛到本进程。"""
    logging.basicConfig(
        level=logging.WARNING,      # 第三方库留在 WARNING，否则 httpx 会对每张图刷一行
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for name in ("comic_crawler", "comic_core", "comic.scheduler"):
        logging.getLogger(name).setLevel(logging.INFO)
    try:
        from comic_core.storage.mysql.log_handler import install

        install()
    except Exception:
        # 落库失败不影响采集：日志照常打到 stdout
        logger.exception("安装日志落库 Handler 失败（继续运行，日志不落库）")


def _persist(**patch) -> None:
    """把运行态写回文件（页面读它）。每次都带上 pid 与心跳时间。"""
    state = load_schedule_state()
    state.update(
        pid=os.getpid(),
        heartbeatAt=datetime.now().isoformat(timespec="seconds"),
        cronError=_cron_error,
    )
    state.update(patch)
    save_schedule_state(state)


def _task_store():
    """任务表句柄（"记进管理台任务列表"用）。**连不上库不该拦住采集**，故各处都兜异常。"""
    from comic_core.storage.mysql import MySQLTaskStore

    return MySQLTaskStore()


def _target_names(config, action: str) -> list[str]:
    """这一轮实际的目标：采集 = 配置的源（留空取默认集）；巡检 = 至多一个源（否则全库，返空）。"""
    if action == "inspect":
        return [config.sources[0]] if len(config.sources) == 1 else []
    return list(config.sources) or default_sources()


def _task_open(task_id: str, config, trigger: str, owner: dict, names: list[str]) -> None:
    """在任务表登记这一轮（`running`），归属：定时 = 系统，立即执行 = 点按钮的人。

    ⚠️ 落库失败只记日志：`admin_task` 是**可观测性**，不是采集的前置条件。
    """
    action = getattr(config, "action", "sync")
    try:
        _task_store().insert({
            "task_id": task_id,
            "task_type": "schedule",
            "status": "running",
            "message": "运行中",
            "result": None,
            "params": {
                "trigger": trigger,
                "action": action,
                "sources": names,
                "mode": config.mode if action != "inspect" else None,
                "limit": config.limit if action != "inspect" else None,
                "since": config.since,
            },
            "user_id": owner.get("id"),
            "username": owner.get("username") or "",
            "started_at": datetime.now(),
            "finished_at": None,
        })
    except Exception:
        logger.exception("定时任务：登记任务表失败（不影响本轮执行）")


def _task_close(task_id: str, status: str, message: str, result=None) -> None:
    """收尾任务表（写状态 / 摘要 / 结果）+ 往**消息中心**发一条。"""
    try:
        _task_store().finish(task_id, status=status, message=message, result=result)
    except Exception:
        logger.exception("定时任务：任务表收尾失败（不影响运行态文件）")
    _publish(task_id)


def _publish(task_id: str) -> None:
    """把这一轮发进消息中心 —— **走 HTTP**（`POST /api/messages`，服务令牌鉴权）。

    为什么不在本进程直写库：**写入入口只有 api 那一处**（2026-10-06 定）——
    校验与收敛（`kind`/`level` 合法值、长度上限、鉴权）只实现一遍，别的进程就不会绕过它写脏消息。
    api 自己的任务收尾则走进程内直调（同进程不必自己调自己）。

    ⚠️ 发失败只记 warning：消息是可观测性，不该因为 api 没起来就让这一轮算失败。
    """
    try:
        from comic_core.notify import publish_message
        from comic_core.storage.mysql.message_store import task_message

        row = _task_store().get(task_id)
        if not row:
            return
        msg = task_message(row)
        publish_message(
            kind=msg["kind"],
            level=msg["level"],
            title=msg["title"],
            body=msg["body"],
            # 入参快照：消息中心据此显示"哪段时间范围"（`since` = 起始时间）
            params=msg.get("params"),
            task_id=msg["task_id"],
            source=msg["source"],
            user_id=msg["user_id"],
            username=msg["username"],
            # 任务消息只给**管理员及以上**看：采集/巡检是管理台的事（收件范围由 task_message 给，
            # 这里显式透传，免得将来 task_message 改了口径而这条路径没跟上）
            min_role=msg.get("min_role") or "admin",
        )
    except Exception:
        logger.exception("定时任务：消息发布失败（不影响本轮）")


def _notify_fans(result: dict) -> int:
    """把本轮**真有新章节**的作品通知给收藏者（消息中心）→ 本轮发出的条数。

    明细来自 `run_round` 各源 result 里的 `stats.updated`（采集轮才有；巡检轮的
    `results` 形状不同，取不到就跳过）。分发逻辑与 api 手动采集**共用**
    `comic_core.fanout`；这里**不传 publish** → 默认走 HTTP（与 `_publish` 同一理由：
    写入入口只有 api 那一处，本进程不直写库）。

    ⚠️ 失败只记 warning：消息是可观测性，不该因为它没发出去让这一轮算失败。
    """
    try:
        from comic_core.fanout import notify_favorite_updates

        updates: list[dict] = []
        for value in (result.get("results") or {}).values():
            if isinstance(value, dict):
                updates.extend((value.get("stats") or {}).get("updated") or [])
        if not updates:
            return 0
        sent = notify_favorite_updates(updates)
        if sent:
            logger.info("定时任务：收藏更新通知已发出 %d 条", sent)
        return sent
    except Exception:
        logger.exception("定时任务：收藏更新通知失败（不影响本轮）")
        return 0


def run_once(config, trigger: str, owner: dict | None = None) -> dict:
    """跑一轮并写回运行态（+ 任务表）；异常不外抛（执行器要能一直活着）。

    `owner` = 这一轮的归属账号：定时轮没有账号（记「系统（定时）」），
    「立即执行一次」则用**点按钮的人**（账号由触发请求文件带过来）。
    """
    owner = dict(owner or {})
    if not owner.get("username"):
        owner["username"] = "系统（定时）" if trigger == "定时" else "系统（手动）"
    # ⚠️ 任务号必须**带随机后缀**（与 api 侧同一套规则，见 comic_core.logctx.new_task_id）：
    #    定时器一轮接一轮跑，只用秒级时间戳会在同一秒内撞 `admin_task` 的唯一键。
    task_id = new_task_id("schedule")
    action = getattr(config, "action", "sync")
    names = _target_names(config, action)
    started = datetime.now()
    _persist(
        running=True,
        lastRunTs=time.time(),      # 先记：进程被杀也不会把同一轮重跑
        lastRunAt=started.isoformat(timespec="seconds"),
        lastStatus="running",
        lastMessage=f"{trigger} 执行中（{action}）",
        lastSources=names,
        lastTrigger=trigger,
        lastTaskId=task_id,
    )
    _task_open(task_id, config, trigger, owner, names)
    logger.info(
        "定时任务：%s 触发一轮（动作=%s，模式=%s），目标=%s task=%s",
        trigger, action, config.mode, "、".join(names) or "(全库)", task_id,
        extra={"log_fields": {"event": "schedule.run", "reason": trigger}},
    )

    result: dict
    try:
        result = run_round(config, trigger, task_id=task_id)
        failed = list(result.get("failed") or [])
        status = "done" if not failed else "failed"
        # 摘要由 run_round 统一给（采集与巡检形状一致），执行器不再关心里面是什么动作
        message = result.get("summary") or f"{trigger}：成功 {result.get('ok', 0)} 个源"
    except Exception as exc:
        logger.exception("定时任务：%s 这一轮异常", trigger)
        result, status, message = {"error": str(exc)}, "failed", f"{trigger} 执行异常：{exc}"

    _persist(running=False, lastStatus=status, lastMessage=message)
    _task_close(task_id, status, message, result)
    _notify_fans(result)
    logger.info("定时任务：%s 结束 —— %s", trigger, message,
                extra={"log_fields": {"event": "schedule.done", "reason": status}})
    return result


def _tick() -> None:
    """看一次表：手动请求 → cron 判定 → （必要时）跑一轮 / 刷心跳。"""
    global _cron_error, _last_heartbeat

    config = load_schedule_config()

    # 1) 手动请求优先。先消费（删除请求文件）再跑：否则下一 tick 会再触发一次
    request = consume_run_now()
    if request is not None:
        owner = {"id": request.get("userId"), "username": request.get("username") or ""}
        logger.info("收到「立即执行一次」请求（%s，来自 %s）",
                    request.get("requestedAt"), owner["username"] or "未知账号")
        run_once(config, "手动", owner=owner)
        _last_heartbeat = time.time()
        return

    # 2) cron 到点判定
    now = datetime.now()
    state = load_schedule_state()
    try:
        fire = is_due(config, now, state.get("lastRunTs"))
    except ValueError as exc:
        # 表达式非法（配置文件被手改坏）：本轮不跑，把原因写给页面；只在变化时记日志，免得刷屏
        if _cron_error != str(exc):
            logger.error("定时任务：cron 表达式无法解析，本轮不触发 —— %s", exc)
            _cron_error = str(exc)
            _persist(running=False)
        elif time.time() - _last_heartbeat >= _HEARTBEAT_SECONDS:
            _last_heartbeat = time.time()
            _persist()
        return

    if _cron_error is not None:      # 表达式改对了 → 清掉页面上的红字
        logger.info("定时任务：cron 表达式已恢复正常")
        _cron_error = None
        _persist()

    if fire is not None:
        run_once(config, "定时")
        _last_heartbeat = time.time()
        return

    if time.time() - _last_heartbeat >= _HEARTBEAT_SECONDS:
        _last_heartbeat = time.time()
        _persist()


def _on_signal(signum, _frame) -> None:  # pragma: no cover - 只在真进程里跑
    logger.info("收到信号 %s，准备退出", signum)
    _stop.set()


def main(argv: list[str] | None = None) -> int:
    """执行器入口：`python -m comic_scheduler` / `comic-scheduler`。"""
    _setup_logging()

    for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if sig is not None:
            try:
                signal.signal(sig, _on_signal)
            except Exception:
                pass  # 某些平台/线程上下文里注册不了，忽略即可（不影响主循环）

    state = load_schedule_state()
    if state.get("running"):
        logger.warning("上次退出时有一轮没跑完（运行态里 running=true），已复位")
    _persist(running=False)
    logger.info(
        "定时任务执行器已启动（pid=%s，每 %ss 看一次表）—— 配置见管理台「定时任务」栏",
        os.getpid(), TICK_SECONDS,
    )

    while not _stop.is_set():
        try:
            _tick()
        except Exception:
            logger.exception("定时任务检查异常")
        _stop.wait(TICK_SECONDS)

    logger.info("定时任务执行器已停止")
    return 0
