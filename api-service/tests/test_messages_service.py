"""消息中心服务（`services/messages.py`）—— 纯逻辑，**不连库**（假 store 注入）。

被测的是这轮"消息中心面向所有登录用户"的核心契约：

- **按收件范围过滤**：定向某人（`to_user_id`）+ 最低角色（`min_role`）；口径只有一处 ——
  `message_store.visible_roles(role)`（"最低角色要求"语义，所以 `min_role='admin'` 时超管也看得到）；
- **已读按账号各一份**：标记已读要带 user，且只影响本人（`message_read` 表）；
- **列表 = 库里的消息 + 正在跑的任务**（后者仅管理员及以上；未读数只算库里的消息）；
- `unread` 与列表**一次返回**；只看未读时不掺运行中的任务；
- **写入收口**：`publish()` 把前端驼峰映射成入库行（含 `toUserId`/`minRole`）；
- 任务收尾 `publish_task()` 用公共的 `task_message()` 造消息，收件范围固定 `admin`，
  **发失败不影响任务**；
- 前端契约：`id` 字符串（消息 `msg-<数字>`、任务用任务号）、`messageId` 供标记已读、
  `status` 由 `level` 推出（error → failed）、`time` 统一 `T` 分隔。
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services import messages  # noqa: E402

ADMIN = {"id": 1, "username": "admin", "role": "superadmin"}
STAFF = {"id": 3, "username": "ops", "role": "admin"}
NORMAL = {"id": 2, "username": "qa_mobile", "role": "user"}


def _msg_row(mid: int, *, title: str, minutes_ago: int = 0, level: str = "info",
             read: bool = False, kind: str = "sync", task_id: str = "",
             min_role: str = "", to_user_id: int | None = None) -> dict:
    return {
        "id": mid, "kind": kind, "level": level, "title": title, "body": f"{title} 的正文",
        "task_id": task_id, "source": "zaimanhua", "user_id": 7, "username": "alice",
        "to_user_id": to_user_id, "min_role": min_role,
        "params": {"source": "zaimanhua", "mode": "incremental", "since": "2026-10-01"},
        "created_at": datetime.now() - timedelta(minutes=minutes_ago),
        "read_at": datetime.now() if read else None,
    }


class _FakeMessageStore:
    """内存假消息表：**自己按 `visible_roles` 过滤**（这样"可见性口径"也被顺带测到）。"""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.published: list[dict] = []
        self.marked: list[tuple[int, int]] = []
        self.marked_all: list[int] = []

    def list(self, *, user=None, limit: int = 50, unread_only: bool = False, kind=None):
        rows = [r for r in self.rows if _visible(r, user)]
        if unread_only:
            rows = [r for r in rows if r["read_at"] is None]
        return sorted(rows, key=lambda r: r["id"], reverse=True)[:limit]

    def unread_count(self, user=None):
        return sum(1 for r in self.rows if _visible(r, user) and r["read_at"] is None)

    def publish(self, payload: dict) -> int:
        self.published.append(payload)
        return 100 + len(self.published)

    def mark_read(self, msg_id: int, user: dict) -> int:
        self.marked.append((msg_id, user["id"]))
        return 1

    def mark_all_read(self, user: dict) -> int:
        self.marked_all.append(user["id"])
        return 3


def _visible(row: dict, user: dict | None) -> bool:
    """与服务端同一口径（借 `visible_roles` 纯函数，避免测试自己实现一套）。"""
    from comic_core.storage.mysql.message_store import visible_roles

    if not user:
        return False
    if row.get("to_user_id") is not None and row["to_user_id"] != user["id"]:
        return False
    return (row.get("min_role") or "") in visible_roles(user.get("role"))


class _FakeTaskStore:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def recent(self, limit: int = 30, user_id: int | None = None) -> list[dict]:
        return self.rows[:limit]


class _MessageCase(unittest.TestCase):
    def setUp(self) -> None:
        self.msgs = _FakeMessageStore([
            _msg_row(1, title="采集完成", minutes_ago=6, read=True, min_role="admin"),
            _msg_row(2, title="巡检完成", minutes_ago=5, min_role="admin"),
            _msg_row(3, title="系统维护公告", minutes_ago=4, kind="system"),
            _msg_row(4, title="你的收藏更新了", minutes_ago=3, to_user_id=2),
            _msg_row(5, title="只给超管", minutes_ago=2, min_role="superadmin"),
            _msg_row(6, title="给管理员的定向消息", minutes_ago=1, to_user_id=1),
        ])
        self.tasks = _FakeTaskStore([])
        self._orig, self._orig_tasks = messages._store, messages._task_store
        messages._store = lambda: self.msgs            # type: ignore[assignment]
        messages._task_store = lambda: self.tasks      # type: ignore[assignment]

    def tearDown(self) -> None:
        messages._store, messages._task_store = self._orig, self._orig_tasks  # type: ignore[assignment]


class TestVisibility(_MessageCase):
    def test_normal_user_sees_only_broadcast_and_own(self) -> None:
        out = messages.feed(NORMAL, limit=20)
        self.assertEqual([i["title"] for i in out["items"]], ["你的收藏更新了", "系统维护公告"])
        self.assertEqual(out["unread"], 2)

    def test_admin_sees_task_messages_too(self) -> None:
        out = messages.feed(STAFF, limit=20)
        titles = [i["title"] for i in out["items"]]
        self.assertIn("采集完成", titles)
        self.assertIn("巡检完成", titles)
        self.assertIn("系统维护公告", titles)
        self.assertNotIn("只给超管", titles, "超管专享的消息，普通管理员看不到")
        self.assertNotIn("你的收藏更新了", titles, "定向给别人的，看不到")

    def test_superadmin_sees_all_but_others_targeted(self) -> None:
        """超管能看全所有**角色档**的消息，但"定向给某人"的只归那个人（定向 = 只给他）。"""
        out = messages.feed(ADMIN, limit=20)
        titles = [i["title"] for i in out["items"]]
        self.assertIn("只给超管", titles)
        self.assertIn("给管理员的定向消息", titles)
        self.assertNotIn("你的收藏更新了", titles, "定向给 user 2 的消息，超管也看不到")
        self.assertEqual(len(titles), 5)

    def test_no_user_sees_nothing(self) -> None:
        self.assertEqual(messages.feed({}, limit=20)["items"], [])

    def test_unread_count_is_per_user(self) -> None:
        """同一条广播，A 读过不该让 B 的角标变小。"""
        self.assertEqual(messages.unread_count(NORMAL), 2)     # 3(广播) + 4(定向给他)
        self.assertEqual(messages.unread_count(ADMIN), 4)      # 2、3、5、6 未读；1 已读；4 定向给别人
        self.assertEqual(messages.unread_count(STAFF), 2)      # 2、3；5 超管专享、4/6 定向给别人


class TestFeed(_MessageCase):
    def test_returns_items_and_unread_in_one_call(self) -> None:
        out = messages.feed(NORMAL, limit=10)
        self.assertEqual(out["unread"], 2)
        self.assertEqual(out["items"][0]["id"], "msg-4")
        self.assertEqual(out["items"][0]["messageId"], 4)
        self.assertTrue(out["items"][0]["time"].count("T") == 1, "时间是 ISO 且用 T 分隔")
        self.assertFalse(out["items"][0]["read"])

    def test_running_task_merged_only_for_admin(self) -> None:
        self.tasks.rows = [{
            "task_id": "schedule-1791277495-c90d6e", "task_type": "schedule", "status": "running",
            "message": "运行中", "result": None,
            # ⚠️ 任务表里 params 是 JSON 列，出参是**字符串** —— 列表必须解析它，才能显示起始时间
            "params": '{"trigger": "定时", "action": "sync", "since": "2026-10-01"}',
            "user_id": None,
            "username": "系统（定时）", "started_at": datetime.now(), "finished_at": None,
        }]
        admin_out = messages.feed(ADMIN, limit=20)
        self.assertEqual(admin_out["items"][0]["id"], "schedule-1791277495-c90d6e")
        self.assertEqual(admin_out["items"][0]["status"], "running")
        self.assertIsNone(admin_out["items"][0]["messageId"], "运行中的任务没有消息行")
        self.assertEqual(admin_out["items"][0]["minRole"], "admin")
        self.assertEqual(admin_out["items"][0]["params"]["since"], "2026-10-01",
                         "跑的时候也要能看出时间范围（params 是 JSON 字符串，要解析）")

        normal_out = messages.feed(NORMAL, limit=20)
        self.assertNotIn("schedule-1791277495-c90d6e", [i["id"] for i in normal_out["items"]],
                         "普通用户不该看到任务运行条目（任务消息是管理员范围的）")

    def test_finished_tasks_are_not_duplicated(self) -> None:
        self.tasks.rows = [{
            "task_id": "sync-1-aaa", "task_type": "sync", "status": "done", "message": "ok",
            "result": None, "params": None, "user_id": 7, "username": "alice",
            "started_at": datetime.now(), "finished_at": datetime.now(),
        }]
        out = messages.feed(ADMIN, limit=20)
        self.assertNotIn("sync-1-aaa", [i["id"] for i in out["items"]])

    def test_unread_only_does_not_include_running(self) -> None:
        self.tasks.rows = [{
            "task_id": "sync-9-zzz", "task_type": "sync", "status": "running", "message": "运行中",
            "result": None, "params": None, "user_id": 7, "username": "alice",
            "started_at": datetime.now(), "finished_at": None,
        }]
        out = messages.feed(ADMIN, limit=20, unread_only=True)
        self.assertNotIn("sync-9-zzz", [i["id"] for i in out["items"]])

    def test_task_table_failure_does_not_break_feed(self) -> None:
        class _Boom:
            def recent(self, limit=30, user_id=None):
                raise RuntimeError("任务表挂了")

        messages._task_store = lambda: _Boom()   # type: ignore[assignment]
        self.assertEqual(len(messages.feed(ADMIN, limit=20)["items"]), 5)

    def test_limit_is_clamped(self) -> None:
        self.assertEqual(len(messages.feed(ADMIN, limit=0)["items"]), 5)
        self.assertLessEqual(len(messages.feed(ADMIN, limit=10_000)["items"]), messages.MAX_LIMIT)


class TestParams(_MessageCase):
    def test_broken_json_is_ignored(self) -> None:
        """params 列是脏数据（不是合法 JSON）时，列表不能整体失败，只是这一条没有入参。"""
        self.msgs.rows[5]["params"] = "{不是 JSON"      # id=6，超管可见的最新一条
        out = messages.feed(ADMIN, limit=20)
        self.assertEqual(out["items"][0]["title"], "给管理员的定向消息")
        self.assertIsNone(out["items"][0]["params"])
        self.assertEqual(len(out["items"]), 5, "别的条目照常返回")

    def test_missing_params_is_none(self) -> None:
        for row in self.msgs.rows:
            row.pop("params", None)
        self.assertTrue(all(i["params"] is None for i in messages.feed(NORMAL, limit=20)["items"]))


class TestPublish(_MessageCase):
    def test_maps_camel_case_to_columns_with_audience(self) -> None:
        item = messages.publish({
            "kind": "notice", "level": "warn", "title": "源站异常", "body": "连续 5 次超时",
            "taskId": "sync-1-aaa", "source": "zaimanhua", "userId": 9, "username": "ops",
            "toUserId": 2, "minRole": "user", "params": {"since": "2026-10-01", "mode": "full"},
        })
        row = self.msgs.published[0]
        self.assertEqual(row["kind"], "notice")
        self.assertEqual(row["level"], "warn")
        self.assertEqual(row["task_id"], "sync-1-aaa")
        self.assertEqual(row["user_id"], 9)
        self.assertEqual(row["to_user_id"], 2)
        self.assertEqual(row["min_role"], "user")
        self.assertEqual(row["params"], {"since": "2026-10-01", "mode": "full"}, "入参快照要一起落库")
        self.assertEqual(item["title"], "源站异常")
        self.assertEqual(item["id"], "msg-101")
        self.assertEqual(item["status"], "done", "warn 不是失败")
        self.assertEqual(item["minRole"], "user")
        self.assertEqual(item["params"]["since"], "2026-10-01", "列表里要能看出起始时间")

    def test_defaults_to_everyone(self) -> None:
        item = messages.publish({"kind": "system", "title": "维护公告"})
        self.assertEqual(self.msgs.published[0]["min_role"], "")
        self.assertIsNone(self.msgs.published[0]["to_user_id"])
        self.assertEqual(item["minRole"], "")

    def test_error_level_maps_to_failed_status(self) -> None:
        item = messages.publish({"kind": "system", "level": "error", "title": "磁盘告警"})
        self.assertEqual(item["status"], "failed")

    def test_publish_task_is_admin_scope(self) -> None:
        """任务收尾的消息：标题带类型与成败，正文是服务端算好的整句，收件范围 = 管理员及以上。"""
        item = messages.publish_task({
            "task_id": "schedule-1-abc", "task_type": "schedule", "status": "done",
            "message": "ok",
            "result": {"summary": "定时：成功 3/3 个源", "results": {"zaimanhua": {"summary": "新增 2 部"}}},
            "params": {"sources": ["zaimanhua"], "action": "sync", "since": "2026-10-01"},
            "user_id": None, "username": "系统（定时）",
            "finished_at": datetime.now(),
        })
        self.assertEqual(item["title"], "定时轮次完成")
        self.assertIn("成功 3/3", item["body"])
        self.assertIn("zaimanhua", item["body"])
        self.assertEqual(item["source"], "zaimanhua")
        self.assertEqual(item["username"], "系统（定时）")
        self.assertEqual(item["minRole"], "admin", "任务消息只给管理员及以上看")
        self.assertEqual(item["params"]["since"], "2026-10-01", "任务消息要带入参（含起始时间）")

    def test_publish_task_failure_is_swallowed(self) -> None:
        class _Boom(_FakeMessageStore):
            def publish(self, payload):   # type: ignore[override]
                raise RuntimeError("消息表写不进去")

        messages._store = lambda: _Boom([])   # type: ignore[assignment]
        self.assertIsNone(messages.publish_task({"task_id": "x", "task_type": "sync"}))


class TestReadState(_MessageCase):
    def test_mark_read_goes_through_user(self) -> None:
        self.assertEqual(messages.mark_read(2, NORMAL), 1)
        self.assertEqual(self.msgs.marked, [(2, 2)])

    def test_mark_all_read_is_per_user(self) -> None:
        self.assertEqual(messages.mark_all_read(NORMAL), 3)
        self.assertEqual(self.msgs.marked_all, [2], "记账要落到**本人**头上")


class TestKindLabel(unittest.TestCase):
    def test_known_and_unknown(self) -> None:
        self.assertEqual(messages.kind_label("schedule"), "定时轮次")
        self.assertEqual(messages.kind_label("custom"), "custom")
        self.assertEqual(messages.kind_label(""), "消息")


if __name__ == "__main__":
    unittest.main()
