"""定时任务的**时刻判定**与**运行态读写** —— 纯逻辑 + 临时目录，不连库。

被测：`scheduling/schedule.py` 的 `is_due` / `next_run_at`，以及 `scheduling/schedule_state.py`
的运行态与触发文件。三个文件路径都通过 env 指到临时目录，**不碰**真正的运行时数据目录。

为什么值得钉死：执行器（独立进程）与 api 就靠这几个函数与文件协调 ——
判定错就是"该跑不跑/重复跑"，触发文件读写错就是"点了按钮没反应/一次请求跑两轮"，
两者都不会报错、只会静静地发生。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comic_crawler.scheduling import schedule_state  # noqa: E402
from comic_crawler.scheduling.schedule import (  # noqa: E402
    GRACE_SECONDS,
    ScheduleConfig,
    is_due,
    next_run_at,
)


def _cfg(**kw) -> ScheduleConfig:
    base = dict(
        enabled=True, cron="0 3 * * *", sources=[], mode="incremental", limit=None, since=None,
    )
    base.update(kw)
    return ScheduleConfig(**base)


def _tmp_root() -> Path:
    """临时目录根：默认用系统 temp，**可用 `COMIC_TEST_TMP` 覆盖**。

    为什么留这个口子：本仓库的 AI 协作环境把写入限制在工作区内（沙箱），系统 temp 写不进去。
    那时 `COMIC_TEST_TMP=<工作区内的目录>` 就能照常跑测试 —— 普通开发机与 CI 不需要设它。
    """
    root = Path(os.environ.get("COMIC_TEST_TMP") or tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_tmp_dir() -> Path:
    """在本测试自己的临时目录里建一个唯一子目录。

    ⚠️ 用 `Path.mkdir()`（默认权限，**继承父目录的授权**）而**不是** `tempfile.mkdtemp()`：
    后者会建出带 0700、不继承父目录权限的目录，在受限环境里那个目录随后连自己都写不进去，
    连 `chmod 0777` 也救不回来（实测 PermissionError）—— 只有显式创建、继承授权才可用。
    """
    path = _tmp_root() / f"comic-sched-test-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    return path


class _TmpDataFiles(unittest.TestCase):
    """把三个文件都指到临时目录（env 覆盖是这些模块支持的正规用法）。"""

    _KEYS = (
        ("COMIC_SCHEDULE_FILE", "schedule.json"),
        ("COMIC_SCHEDULE_STATE_FILE", "state.json"),
        ("COMIC_SCHEDULE_TRIGGER_FILE", "run_now.json"),
    )

    def setUp(self) -> None:
        self.dir = _make_tmp_dir()
        self._saved: dict[str, str | None] = {}
        for name, filename in self._KEYS:
            self._saved[name] = os.environ.get(name)
            os.environ[name] = str(self.dir / filename)

    def tearDown(self) -> None:
        for name, old in self._saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        shutil.rmtree(self.dir, ignore_errors=True)


class TestIsDue(_TmpDataFiles):
    """到点判定。"""

    def test_daily_due_inside_window(self) -> None:
        fire = is_due(_cfg(), datetime(2026, 10, 6, 3, 0, 10))
        self.assertIsNotNone(fire)
        self.assertEqual(fire, datetime(2026, 10, 6, 3, 0))

    def test_daily_not_due_before_hit(self) -> None:
        self.assertIsNone(is_due(_cfg(), datetime(2026, 10, 6, 2, 59, 59)))

    def test_daily_not_due_after_window(self) -> None:
        """过窗就跳过这一轮（错过不补）：窗口 = GRACE_SECONDS 秒。"""
        after = datetime(2026, 10, 6, 3, 0) + timedelta(seconds=GRACE_SECONDS + 1)
        self.assertIsNone(is_due(_cfg(), after))

    def test_not_due_when_this_round_already_ran(self) -> None:
        ran_at = datetime(2026, 10, 6, 3, 0, 5).timestamp()
        self.assertIsNone(is_due(_cfg(), datetime(2026, 10, 6, 3, 1, 0), ran_at))

    def test_ran_yesterday_still_due_today(self) -> None:
        ran_at = datetime(2026, 10, 5, 3, 0, 2).timestamp()
        self.assertIsNotNone(is_due(_cfg(), datetime(2026, 10, 6, 3, 0, 5), ran_at))

    def test_every_15_minutes(self) -> None:
        cfg = _cfg(cron="*/15 * * * *")
        self.assertIsNotNone(is_due(cfg, datetime(2026, 10, 6, 10, 15, 5)))
        self.assertIsNone(is_due(cfg, datetime(2026, 10, 6, 10, 7, 0)))

    def test_disabled_never_due(self) -> None:
        self.assertIsNone(is_due(_cfg(enabled=False), datetime(2026, 10, 6, 3, 0, 5)))

    def test_bad_cron_raises(self) -> None:
        with self.assertRaises(ValueError):
            is_due(_cfg(cron="0 99 * * *"), datetime(2026, 10, 6, 3, 0, 5))


class TestNextRunAt(_TmpDataFiles):
    """「下次执行」是**严格未来**的时刻。"""

    def test_today_when_before_hit(self) -> None:
        self.assertEqual(
            next_run_at(_cfg(), datetime(2026, 10, 6, 1, 0, 0)),
            datetime(2026, 10, 6, 3, 0),
        )

    def test_tomorrow_right_after_hit(self) -> None:
        self.assertEqual(
            next_run_at(_cfg(), datetime(2026, 10, 6, 3, 0, 5)),
            datetime(2026, 10, 7, 3, 0),
        )

    def test_interval_expression_rolls_forward(self) -> None:
        self.assertEqual(
            next_run_at(_cfg(cron="*/5 * * * *"), datetime(2026, 10, 6, 10, 7, 0)),
            datetime(2026, 10, 6, 10, 10),
        )

    def test_disabled_has_no_next_run(self) -> None:
        self.assertIsNone(next_run_at(_cfg(enabled=False), datetime(2026, 10, 6, 1, 0)))

    def test_bad_cron_raises(self) -> None:
        with self.assertRaises(ValueError):
            next_run_at(_cfg(cron="not-a-cron"), datetime(2026, 10, 6, 1, 0))


class TestScheduleState(_TmpDataFiles):
    """运行态读写：缺文件 / 脏文件都不该抛，字段始终齐全。"""

    def test_missing_file_returns_empty_state(self) -> None:
        state = schedule_state.load_schedule_state()
        self.assertFalse(state["running"])
        self.assertIsNone(state["lastRunAt"])
        self.assertEqual(state["lastSources"], [])

    def test_round_trip(self) -> None:
        schedule_state.save_schedule_state(
            {"running": True, "lastStatus": "running", "lastRunTs": 123.0, "lastSources": ["a"]}
        )
        state = schedule_state.load_schedule_state()
        self.assertTrue(state["running"])
        self.assertEqual(state["lastStatus"], "running")
        self.assertEqual(state["lastRunTs"], 123.0)
        self.assertEqual(state["lastSources"], ["a"])

    def test_unknown_fields_are_dropped_and_known_ones_defaulted(self) -> None:
        schedule_state.state_path().write_text('{"running": true, "乱入": 1}', "utf-8")
        state = schedule_state.load_schedule_state()
        self.assertTrue(state["running"])
        self.assertNotIn("乱入", state)
        self.assertIn("heartbeatAt", state)

    def test_corrupt_file_does_not_raise(self) -> None:
        schedule_state.state_path().write_text("{ 不是 JSON", "utf-8")
        state = schedule_state.load_schedule_state()
        self.assertFalse(state["running"])


class TestRunNowTrigger(_TmpDataFiles):
    """触发文件：api 写、执行器读到即删（防一次请求跑两轮）。"""

    def test_request_then_consume(self) -> None:
        payload = schedule_state.request_run_now()
        self.assertIn("requestedAt", payload)
        self.assertTrue(schedule_state.trigger_path().exists())

        consumed = schedule_state.consume_run_now()
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed["requestedAt"], payload["requestedAt"])
        # 读到即删：第二次消费必须为空，否则执行器会重复跑
        self.assertFalse(schedule_state.trigger_path().exists())
        self.assertIsNone(schedule_state.consume_run_now())

    def test_corrupt_trigger_is_consumed_as_empty(self) -> None:
        schedule_state.trigger_path().write_text("{ 坏", "utf-8")
        self.assertIsNotNone(schedule_state.consume_run_now())
        self.assertFalse(schedule_state.trigger_path().exists())


if __name__ == "__main__":
    unittest.main()
