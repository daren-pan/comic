"""后台任务注册表（`services/tasks.py`）—— 纯逻辑，**不连库、不起线程**。

被测的是这次"任务表从内存搬到库"（2026-10-06）之后的行为契约：

- **落库与账号绑定**：触发时插一行 `running`，并把 `user_id` / `username` / 入参快照写进去；
- **收尾**：成功写 `done` + 结果、失败写 `failed` + 异常摘要（异常**不外抛**，线程不能崩）；
- **对外形状不变**：DB 行 → 前端驼峰契约（`id` / `type` / `startedAt` …），与改造前的内存版一致；
- **重启清理**：`reap_stale` 只清"本进程启动之前"的 running（多 worker 下不误伤别人正在跑的）；
- **任务号**：带随机后缀，重启后不与历史任务撞号（旧实现是进程内自增计数器）。

做法：把 `tasks._store()` 换成内存假实现（真实现要连 MySQL，而本项目单测约定"不连库"），
线程也绕开 —— 直接调 `tasks.execute()` 同步跑任务体。
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services import tasks  # noqa: E402


class _FakeStore:
    """内存假任务表：接口与 `MySQLTaskStore` 一致，断言用。

    排序刻意与真实 SQL 对齐（`ORDER BY id DESC` = **插入序倒序**），而不是按时间戳 ——
    否则同一微秒内插入的两行顺序会随机，测试就会飘。
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.reaps: list[tuple[datetime, str]] = []
        self._seq = 0

    def insert(self, row: dict) -> None:
        self._seq += 1
        self.rows[row["task_id"]] = dict(row, _seq=self._seq)

    def finish(self, task_id: str, *, status: str, message: str = "", result=None) -> None:
        self.rows[task_id].update(status=status, message=message, result=result,
                                  finished_at=datetime.now())

    def reap_running(self, before: datetime, message: str) -> list[dict]:
        """与真实实现同契约：**返回被处理的行**（调用方据此补发消息）。"""
        self.reaps.append((before, message))
        hit = [r for r in self.rows.values()
               if r["status"] == "running" and r["started_at"] < before]
        now = datetime.now()
        for row in hit:
            row.update(status="failed", message=message, finished_at=now)
        return [dict(r, status="failed", message=message) for r in hit]

    def get(self, task_id: str) -> dict | None:
        return dict(self.rows[task_id]) if task_id in self.rows else None

    def recent(self, limit: int = 30, user_id: int | None = None) -> list[dict]:
        rows = [r for r in self.rows.values() if user_id is None or r.get("user_id") == user_id]
        ordered = sorted(rows, key=lambda r: r.get("_seq", 0), reverse=True)
        return [dict(r) for r in ordered[:limit]]


class _FakeMessages:
    """内存假消息中心：只记录"任务收尾发过哪些消息"，断言用（不碰 MySQL）。"""

    def __init__(self) -> None:
        self.published: list[dict] = []

    def publish_task(self, task: dict) -> dict:
        self.published.append(task)
        return {"id": f"msg-{len(self.published)}", "title": task.get("task_id")}


class _TaskCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = _FakeStore()
        self.msgs = _FakeMessages()
        self._orig = tasks._store
        self._orig_msgs = tasks._messages
        tasks._store = lambda: self.fake          # type: ignore[assignment]
        tasks._messages = lambda: self.msgs       # type: ignore[assignment]
        self.user = {"id": 7, "username": "alice", "role": "admin"}

    def tearDown(self) -> None:
        tasks._store = self._orig                 # type: ignore[assignment]
        tasks._messages = self._orig_msgs         # type: ignore[assignment]

    def _run(self, task_id: str, fn, task_type: str = "sync", params: dict | None = None) -> None:
        # 登记 + 同步跑任务体：**不走线程**（`run_task` 会起线程，测试里那样会跑两遍且不可控）
        tasks.register(task_id, task_type, user=self.user, params=params)
        tasks.execute(task_id, task_type, fn)


class TestTaskId(_TaskCase):
    def test_shape_and_uniqueness(self) -> None:
        ids = {tasks.new_task_id("sync") for _ in range(200)}
        self.assertEqual(len(ids), 200, "任务号必须唯一（有唯一键，撞号会直接插不进去）")
        first = tasks.new_task_id("sync")
        self.assertTrue(first.startswith("sync-"))
        self.assertEqual(len(first.split("-")), 3, "形状：<类型>-<时间戳>-<随机后缀>")

    def test_no_process_counter(self) -> None:
        """旧实现带进程内自增序号；重启计数归零会与历史任务撞号，故必须已去掉。"""
        a, b = tasks.new_task_id("sync"), tasks.new_task_id("sync")
        self.assertNotEqual(a.split("-")[2], b.split("-")[2])


class TestRunAndFinish(_TaskCase):
    def test_inserts_running_with_owner_and_params(self) -> None:
        self._run("sync-1-aaa", lambda: {"ok": 1}, params={"source": "zaimanhua", "mode": "full"})
        # 收尾后状态已变 done，但归属与入参必须一直在
        row = self.fake.rows["sync-1-aaa"]
        self.assertEqual(row["user_id"], 7)
        self.assertEqual(row["username"], "alice")
        self.assertEqual(row["params"], {"source": "zaimanhua", "mode": "full"})
        self.assertIsNotNone(row["started_at"])

    def test_success_writes_done_and_result(self) -> None:
        self._run("sync-2-bbb", lambda: {"summary": "3 部"})
        row = self.fake.rows["sync-2-bbb"]
        self.assertEqual(row["status"], "done")
        self.assertEqual(row["message"], "ok")
        self.assertEqual(row["result"], {"summary": "3 部"})
        self.assertIsNotNone(row["finished_at"])

    def test_finished_task_publishes_one_message(self) -> None:
        """任务收尾要往消息中心发**一条**（消息中心的内容以库为准，不再靠前端登记）。"""
        self._run("sync-8-hhh", lambda: {"summary": "3 部"}, params={"source": "zaimanhua"})
        self.assertEqual(len(self.msgs.published), 1)
        sent = self.msgs.published[0]
        self.assertEqual(sent["task_id"], "sync-8-hhh")
        self.assertEqual(sent["task_type"], "sync")
        self.assertEqual(sent["status"], "done")
        self.assertEqual(sent["username"], "alice")

    def test_message_publish_failure_does_not_break_task(self) -> None:
        """消息发布失败不能把任务本身拖失败（消息是可观测性）。"""
        def boom(_task):
            raise RuntimeError("消息表写不进去")

        self.msgs.publish_task = boom          # type: ignore[assignment]
        self._run("sync-9-iii", lambda: None)
        self.assertEqual(self.fake.rows["sync-9-iii"]["status"], "done")

    def test_failure_is_recorded_and_not_raised(self) -> None:
        def boom():
            raise RuntimeError("源站搜不到：《某作品》")

        self._run("import-3-ccc", boom, task_type="import")   # 不抛 = 线程不会崩
        row = self.fake.rows["import-3-ccc"]
        self.assertEqual(row["status"], "failed")
        self.assertIn("源站搜不到", row["message"])
        self.assertIsNone(row["result"])

    def test_finish_failure_does_not_escape(self) -> None:
        """收尾写库失败也要被吞掉（否则后台线程崩得莫名其妙）。"""
        def bad_finish(*a, **kw):
            raise RuntimeError("DB 挂了")

        self._run("sync-4-ddd", lambda: None)      # 先正常跑一遍
        self.fake.finish = bad_finish               # type: ignore[assignment]
        tasks.execute("sync-4-ddd", "sync", lambda: None)   # 不应抛异常


class TestContract(_TaskCase):
    def test_row_maps_to_frontend_camel_case(self) -> None:
        self._run("heal-5-eee", lambda: None, task_type="heal")
        item = tasks.recent(10)[0]
        self.assertEqual(
            sorted(item.keys()),
            sorted(["id", "type", "status", "message", "result", "params",
                    "userId", "username", "startedAt", "finishedAt"]),
        )
        self.assertEqual(item["id"], "heal-5-eee")     # 对外主键 = 任务号，不是自增 id
        self.assertEqual(item["type"], "heal")
        self.assertEqual(item["username"], "alice")
        self.assertNotIn("task_id", item)

    def test_get_missing_returns_none(self) -> None:
        self.assertIsNone(tasks.get("不存在的任务号"))

    def test_recent_can_filter_by_user(self) -> None:
        self._run("sync-6-fff", lambda: None)
        self.fake.insert({
            "task_id": "sync-7-ggg", "task_type": "sync", "status": "done", "message": "ok",
            "result": None, "params": None, "user_id": 99, "username": "bob",
            "started_at": datetime.now(), "finished_at": datetime.now(),
        })
        # 最新在前（= 库里 ORDER BY id DESC）
        self.assertEqual([t["id"] for t in tasks.recent(10)], ["sync-7-ggg", "sync-6-fff"])
        self.assertEqual([t["id"] for t in tasks.recent(10, user_id=99)], ["sync-7-ggg"])


class TestReapStale(_TaskCase):
    def test_reaps_only_tasks_started_before_this_process(self) -> None:
        now = datetime.now()
        self.fake.rows["old"] = {
            "task_id": "old", "task_type": "sync", "status": "running", "message": "运行中",
            "result": None, "params": None, "user_id": 1, "username": "a",
            "started_at": now - timedelta(minutes=10), "finished_at": None,
        }
        self.fake.rows["new"] = dict(self.fake.rows["old"], task_id="new", started_at=now)

        self.assertEqual(tasks.reap_stale(now - timedelta(minutes=1)), 1)
        self.assertEqual(self.fake.rows["old"]["status"], "failed")
        self.assertEqual(self.fake.rows["old"]["message"], tasks.INTERRUPTED)
        self.assertEqual(self.fake.rows["new"]["status"], "running", "本进程启动后开始的不能动")
        # 被打断的任务也要发消息（否则它只在「最近任务」里露头，消息中心看不到）
        self.assertEqual([m["task_id"] for m in self.msgs.published], ["old"])

    def test_db_failure_is_swallowed(self) -> None:
        class _Boom(_FakeStore):
            def reap_running(self, before, message):   # type: ignore[override]
                raise RuntimeError("DB 不通")

        tasks._store = lambda: _Boom()      # type: ignore[assignment]
        self.assertEqual(tasks.reap_stale(datetime.now()), 0)   # 不能拦住 api 启动
        self.assertEqual(self.msgs.published, [])


if __name__ == "__main__":
    unittest.main()
