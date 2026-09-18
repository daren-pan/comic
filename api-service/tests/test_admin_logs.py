"""运行日志查询服务（`api-service/services/logs.py`）。

**纯逻辑、不连库**：把 `logs._store` 换成假 store，断言
① 筛选条件原样透传给存储层、② 行被序列化成前端契约（驼峰 + 时间格式化）、③ 分页参数有上下限、
④ 时间列一律按**北京时间**出参（容器是 UTC 时要自动补 8 小时）。

为什么要守：查询页的每个筛选框都靠这次透传。若某个参数名写错（比如 `comic_id` 写成 `comicId`），
表现是"筛了没反应"而不是报错 —— 必须靠断言卡住。
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services import logs  # noqa: E402

BEIJING = timedelta(hours=8)


class FakeLogStore:
    """假存储：记录收到的查询条件，返回固定行。"""

    def __init__(self) -> None:
        self.last_query: dict = {}
        self.last_purge: int | None = None
        self.last_get: int | None = None
        self.rows = [
            {
                "id": 7,
                "created_at": datetime(2026, 9, 14, 16, 31, 25),
                "level": "WARNING",
                "logger": "comic_crawler.images.transfer",
                "message": "转存失败 | zaimanhua | …",
                "task_id": "transfer-2-1789373866",
                "task_type": "transfer",
                "exc_type": "",
                "source": "zaimanhua",
                "comic_id": 151,
                "comic_title": "午夜心旋律",
                "chapter_id": 679,
                "chapter_title": "第03话",
                "endpoint": "https://m.zaimanhua.com/api/app/v1/comic/chapter/71419/137421",
                "pages": 37,
                "reason": "重拉返回 0 页（源站侧无内容）",
                "event": "transfer.fail",
            }
        ]

    def query(self, **kw):
        self.last_query = kw
        return list(self.rows), 1

    def get(self, log_id: int):
        self.last_get = log_id
        row = dict(self.rows[0])
        row["exc_text"] = "Traceback ...\nValueError: boom"
        return row

    def purge(self, days: int = 30) -> int:
        self.last_purge = days
        return 42


class TestLogQueryService(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeLogStore()
        patcher = mock.patch.object(logs, "_store", self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        # 时区跑测试的机器不一定，**显式钉住读进程偏移**，否则断言会随环境漂移。
        # 默认按"部署正确"（容器 TZ=Asia/Shanghai）→ 时间列是恒等变换。
        self._offset(BEIJING)

    def _offset(self, delta: timedelta) -> None:
        p = mock.patch.object(logs, "_LOCAL_UTC_OFFSET", delta)
        p.start()
        self.addCleanup(p.stop)

    def test_filters_are_passed_through(self):
        logs.query(
            level="WARNING", source="zaimanhua", event="transfer.fail",
            task_id="transfer-2-1", comic_id=151, keyword="午夜",
            since="2026-09-14", until="2026-09-15", page=2, page_size=20,
        )
        q = self.store.last_query
        self.assertEqual(q["level"], "WARNING")
        self.assertEqual(q["source"], "zaimanhua")
        self.assertEqual(q["event"], "transfer.fail")
        self.assertEqual(q["task_id"], "transfer-2-1")
        self.assertEqual(q["comic_id"], 151)
        self.assertEqual(q["keyword"], "午夜")
        self.assertEqual(q["since"], "2026-09-14")
        self.assertEqual(q["until"], "2026-09-15")
        self.assertEqual(q["page"], 2)
        self.assertEqual(q["page_size"], 20)

    def test_row_is_serialized_to_camel_case(self):
        got = logs.query()["items"][0]
        self.assertEqual(got["id"], 7)
        self.assertEqual(got["createdAt"], "2026-09-14 16:31:25")   # 时间已格式化
        self.assertEqual(got["comicId"], 151)
        self.assertEqual(got["comicTitle"], "午夜心旋律")
        self.assertEqual(got["chapterTitle"], "第03话")
        self.assertEqual(got["taskId"], "transfer-2-1789373866")
        self.assertEqual(got["reason"], "重拉返回 0 页（源站侧无内容）")
        self.assertNotIn("excText", got)          # 列表不带堆栈
        self.assertNotIn("exc_text", got)         # 蛇形字段不外泄

    def test_time_is_beijing_when_container_is_utc(self):
        """容器时区是 UTC（漏配 `COMIC_TZ` / 没重建）→ 时间列自动补 8 小时。

        这是 2026-09-18「服务器上日志时间早 8 小时」的兜底：库里按**写入进程的本机时间**存，
        UTC 容器写出来的就是 UTC，页面要北京时间就得 +8。配了 TZ 的部署走上面的恒等分支。
        """
        self._offset(timedelta(0))                       # 模拟 UTC 容器
        self.assertEqual(logs.query()["items"][0]["createdAt"], "2026-09-15 00:31:25")

    def test_aware_value_is_converted_not_double_shifted(self):
        """带 tzinfo 的值只做一次换算：UTC 的 08:31 → 北京 16:31（不再叠加进程偏移）。"""
        row = dict(self.store.rows[0])
        row["created_at"] = datetime(2026, 9, 14, 8, 31, 25, tzinfo=timezone.utc)
        self.assertEqual(logs.to_log_row(row)["createdAt"], "2026-09-14 16:31:25")

    def test_time_none_is_passed_through(self):
        """时间缺失时不炸（脏数据 / 手工插入的行）—— 原样返回 None。"""
        row = dict(self.store.rows[0])
        row["created_at"] = None
        self.assertIsNone(logs.to_log_row(row)["createdAt"])

    def test_result_carries_pagination(self):
        r = logs.query(page=3, page_size=20)
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["page"], 3)
        self.assertEqual(r["pageSize"], 20)

    def test_page_size_is_clamped(self):
        """分页大小有上下限；**回报的值必须是实际生效的值**（不能"传 0 却报别的"）。"""
        self.assertEqual(logs.query(page_size=99999)["pageSize"], 200)   # 上限 200
        self.assertEqual(logs.query(page_size=0)["pageSize"], 50)        # 未指定 → 默认 50
        self.assertEqual(logs.query(page_size=-5)["pageSize"], 1)        # 负数 → 至少 1
        self.assertEqual(logs.query(page=-5)["page"], 1)
        # 实际生效值与透传给存储层的值一致
        logs.query(page_size=99999)
        self.assertEqual(self.store.last_query["page_size"], 200)

    def test_detail_includes_stack(self):
        row = logs.detail(7)
        self.assertEqual(self.store.last_get, 7)
        self.assertIn("ValueError: boom", row["excText"])

    def test_detail_missing_returns_none(self):
        self.store.get = lambda log_id: None          # type: ignore[method-assign]
        self.assertIsNone(logs.detail(999))

    def test_purge_passes_days(self):
        self.assertEqual(logs.purge(7), 42)
        self.assertEqual(self.store.last_purge, 7)

    def test_options_expose_levels_and_events(self):
        opt = logs.options()
        self.assertIn("WARNING", opt["levels"])
        self.assertIn("transfer.fail", opt["events"])
        # 封面落盘的两端（成功 / 失败）也要在下拉里，否则筛不出来
        self.assertIn("cover.fail", opt["events"])
        self.assertIn("cover.ok", opt["events"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
