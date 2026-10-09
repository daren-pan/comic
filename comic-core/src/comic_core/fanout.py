"""收藏更新通知（fan-out）：采集更新了作品 → 找到收藏者 → 逐人发「更新了」消息。

## 为什么要一层"分发"

采集发生在两处 —— api 进程内的**手动采集**与独立进程 `comic-scheduler` 的**定时轮次**，
两边都会更新作品；而「谁收藏了这些作品」的查询与「消息长什么样」的组装必须**只有一份**
（两边发出来的消息要长得一样，与 `message_store.task_message` 同一理由）。
采集侧只负责把「本次真有新章节的作品」记进 `SyncStats.updated`（明细，纯数据），
本模块负责把它变成消息 —— 放在共用内核，两个调用方各自 import。

## 投递通道由调用方注入

写入消息中心只有一个入口（2026-10-06 定），但"怎么到那个入口"分两种：

- **api 进程内**：传 `publish=services.messages.publish` —— 同进程直调写入口，省一次自己调自己；
- **其他进程**（`comic-scheduler`、运维脚本）：不传 → 默认走 `notify.publish_message`
  （HTTP + 服务令牌，见 `comic_core/notify.py`）。

## 收件范围与口径

- 每条消息 `to_user_id` **定向到收藏者本人**（`min_role=''`）—— 收藏本身就要登录，
  "没登录的用户不处理"在这里是构造上成立的；
- 通知对象只认**已登录账号**：`UserStore.list_favoriters` 的 JOIN 会把已删账号滤掉；
- **下架作品不通知**（`list_favoriters` 默认 `listed_only=True`）—— 详情页 404，
  通知了只会点进死链；
- 同一作品**每批新章节只发一次**：明细来自"本次真有新章节"同一处记账，
  没新章节的轮次天然不发（同一时间窗内重复触发也不会重复通知）。

## 失败语义

**任何失败都只记 warning、不抛异常** —— 消息是可观测性，不该因为它没发出去
就让采集任务算失败（与 `services.messages.publish_task` 同一约定）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: 正文里最多列几个新章节名（超出用省略号收尾）
MAX_TITLES = 3

#: 消息类型（前端 `kindLabel` / `statusLabel` 据此显示「更新」与"通知"）。
#: 不是任务类型（sync/inspect…）—— 它是**给普通用户**的作品更新提醒。
KIND = "update"


def _user_store():
    """收藏者查询句柄（**测试可替换**：传 `store=` 即可脱离 MySQL 断言逻辑）。"""
    from .storage.mysql import MySQLUserStore

    return MySQLUserStore()


def _http_publish(payload: dict):
    """默认投递通道：`notify.publish_message`（HTTP + 服务令牌）—— 给 api 之外的进程用。"""
    from .notify import publish_message

    return publish_message(
        kind=payload.get("kind") or "system",
        level=payload.get("level") or "info",
        title=payload.get("title") or "",
        body=payload.get("body") or "",
        params=payload.get("params"),
        source=payload.get("source") or "",
        to_user_id=payload.get("toUserId"),
        min_role=payload.get("minRole") or "",
    )


def _body_of(count: int, titles: list[str]) -> str:
    """正文：`新增 N 话`（有章节名时再列最多 3 个，超出加省略号）。"""
    body = f"新增 {count} 话" if count else "有新章节入库"
    if titles:
        body += "：" + "、".join(titles) + ("…" if count > len(titles) else "")
    return body


def build_payloads(updates: list[dict], fans: dict[int, list[int]]) -> list[dict]:
    """组装「每（更新作品 × 收藏者）一条」的消息载荷（**纯函数**，便于单测）。

    `updates`：`SyncStats.updated` 的明细 —— `{comic_id, title, source, new_chapters, titles}`
    （见 `comic_core.models.SyncStats`）；`fans`：`{comic_id: [user_id, ...]}`
    （`UserStore.list_favoriters` 的结果）。载荷用前端契约的驼峰（与 `POST /api/messages` 同形）。
    """
    payloads: list[dict] = []
    for up in updates or []:
        if not isinstance(up, dict):
            continue
        try:
            comic_id = int(up.get("comic_id"))
        except (TypeError, ValueError):
            continue
        title = str(up.get("title") or "").strip() or f"作品 {comic_id}"
        count = int(up.get("new_chapters") or 0)
        titles = [str(t) for t in (up.get("titles") or []) if str(t).strip()][:MAX_TITLES]
        for user_id in fans.get(comic_id) or ():
            payloads.append({
                "kind": KIND,
                "level": "info",
                "title": f"《{title}》更新了",
                "body": _body_of(count, titles),
                "params": {
                    "comicId": comic_id,
                    "newChapters": count,
                    "source": up.get("source") or "",
                },
                "source": up.get("source") or "",
                "toUserId": user_id,     # 定向：只有他看得到
                "minRole": "",
            })
    return payloads


def notify_favorite_updates(updates: list[dict], *, publish=None, store=None) -> int:
    """给收藏了这些更新作品的用户各发一条消息，返回**发出的条数**（没有任何收藏者 = 0）。

    - `updates`：采集侧给的「本次真有新章节」明细节（可为空/None，直接返回 0）；
    - `publish`：投递函数（载荷 dict → 任意），不传走 HTTP（见模块 docstring）；
    - `store`：收藏者查询（默认 `MySQLUserStore`），传假的即可单测。

    失败语义见模块 docstring：**只记 warning、不抛**。
    """
    try:
        valid = [u for u in (updates or []) if isinstance(u, dict) and u.get("comic_id")]
        if not valid:
            return 0
        fans = (store or _user_store()).list_favoriters([int(u["comic_id"]) for u in valid])
        payloads = build_payloads(valid, fans)
        if not payloads:
            return 0
        send = publish or _http_publish
        sent = 0
        for payload in payloads:
            try:
                send(payload)
                sent += 1
            except Exception:
                logger.warning(
                    "收藏更新通知投递失败（user=%s comic=%s）",
                    payload.get("toUserId"), (payload.get("params") or {}).get("comicId"),
                )
        logger.info("收藏更新通知：%d 部更新、发出 %d 条消息", len(valid), sent)
        return sent
    except Exception:
        logger.exception("收藏更新通知分发失败（不影响采集）")
        return 0
