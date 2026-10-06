"""管理台「定时任务」的**接口侧**（`services/scheduler.py`）—— 纯逻辑 + 临时文件，不连库、不起进程。

采集已经交给独立进程 `comic-scheduler`（见 `comic-scheduler/README.md`），所以接口侧只剩四件事：
**读配置 / 存配置（含 cron 语义校验）/ 读运行态算「下次执行」/ 写触发请求**。本文件就守这四件：

- 非法 cron 在**保存时**即被拒（`ValueError` → 路由层 400），且**不落盘**；
- 保存会归一化（多余空白、未注册的源名丢弃）；
- 「下次执行」是**严格未来**时刻（不是"现在正待跑的那一轮"）；
- 执行器是独立进程 → `executorAlive` 必须如实反映"它到底在不在"（靠心跳判定）；
- 「立即执行一次」只**写触发文件**，不等采集结果（结果由执行器写运行态）。

cron 引擎与运行态文件的细节分别由 `crawler-service/tests/test_cron.py` 与
`test_schedule_timing.py` 钉死，本文件不重复。
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

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services import scheduler  # noqa: E402


def _tmp_root() -> Path:
    """临时目录根：默认系统 temp，可用 `COMIC_TEST_TMP` 覆盖（受限/沙箱环境把文件限制在工作区内）。"""
    root = Path(os.environ.get("COMIC_TEST_TMP") or tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_tmp_dir() -> Path:
    """建唯一临时子目录。

    ⚠️ 用 `Path.mkdir()`（默认权限，继承父目录授权）而**不是** `tempfile.mkdtemp()`：
    后者带 0700 且不继承父目录权限，在受限环境里随后连自己都写不进去（实测 `PermissionError`，
    `chmod 0777` 也无效）。
    """
    path = _tmp_root() / f"api-sched-test-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    return path


class _ScheduleClientCase(unittest.TestCase):
    """把三个文件都指到临时目录（env 覆盖是这些模块支持的正规用法），不碰真正的运行时数据目录。"""

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

    # 便捷读写
    def _config_file(self) -> Path:
        return self.dir / "schedule.json"

    def _trigger_file(self) -> Path:
        return self.dir / "run_now.json"

    def _write_state(self, **fields) -> None:
        import json

        (self.dir / "state.json").write_text(json.dumps(fields), "utf-8")

    def _body(self, **kw) -> dict:
        body = {
            "enabled": True, "cron": "0 3 * * *", "sources": ["zaimanhua"],
            "mode": "incremental", "limit": None, "since": None,
        }
        body.update(kw)
        return body


class TestUpdate(_ScheduleClientCase):
    """保存配置：语义校验 + 归一化 + 落盘。"""

    def test_rejects_invalid_cron_without_writing(self) -> None:
        with self.assertRaises(ValueError):
            scheduler.update(self._body(cron="0 99 * * *"))
        self.assertFalse(self._config_file().exists(), "非法表达式不该落盘")

    def test_rejects_wrong_field_count(self) -> None:
        with self.assertRaises(ValueError):
            scheduler.update(self._body(cron="0 3 * *"))

    def test_normalizes_and_persists(self) -> None:
        status = scheduler.update(self._body(cron="  0   3  * * *  ", sources=["zaimanhua", "nope"]))
        self.assertTrue(self._config_file().exists())
        self.assertEqual(status["config"]["cron"], "0 3 * * *")       # 空白归一化
        self.assertEqual(status["config"]["sources"], ["zaimanhua"])  # 未注册的源被丢弃
        self.assertTrue(status["config"]["enabled"])

    def test_returns_effective_config_with_next_run(self) -> None:
        status = scheduler.update(self._body(cron="*/15 * * * *", enabled=True))
        self.assertIsNotNone(status["nextRunAt"])
        self.assertEqual(status["sources"], ["zaimanhua"])

    def test_saves_action(self) -> None:
        """`action` 决定这一轮干什么（采集 / 巡检）—— 保存后必须原样生效。"""
        status = scheduler.update(self._body(action="inspect"))
        self.assertEqual(status["config"]["action"], "inspect")

    def test_unknown_action_falls_back_to_sync(self) -> None:
        """脏值收敛在采集层做（`ScheduleConfig.normalized`）：认不出就回落"采集"，不报错。"""
        status = scheduler.update(self._body(action="乱写的动作"))
        self.assertEqual(status["config"]["action"], "sync")


class TestStatus(_ScheduleClientCase):
    """状态：配置 + 运行态（执行器写的）+ 下次执行 + 执行器是否在线。"""

    def test_defaults_when_nothing_written(self) -> None:
        status = scheduler.status()
        self.assertFalse(status["config"]["enabled"])
        self.assertEqual(status["config"]["cron"], "0 3 * * *")
        self.assertIsNone(status["nextRunAt"])       # 未启用 → 没有下次
        self.assertFalse(status["executorAlive"])    # 没有心跳 → 不在线

    def test_next_run_is_strictly_future(self) -> None:
        scheduler.update(self._body(cron="*/15 * * * *"))
        next_run = datetime.fromisoformat(scheduler.status()["nextRunAt"])
        self.assertGreater(next_run, datetime.now())

    def test_reads_executor_state(self) -> None:
        self._write_state(
            running=True, lastRunAt="2026-10-06T03:00:04", lastStatus="running",
            lastMessage="定时 执行中（1 个源）", lastSources=["zaimanhua"],
            heartbeatAt=datetime.now().isoformat(timespec="seconds"),
        )
        status = scheduler.status()
        self.assertTrue(status["running"])
        self.assertEqual(status["lastRunAt"], "2026-10-06T03:00:04")
        self.assertEqual(status["lastSources"], ["zaimanhua"])
        self.assertTrue(status["executorAlive"], "心跳很新 → 执行器在线")

    def test_stale_heartbeat_means_executor_offline(self) -> None:
        old = (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")
        self._write_state(heartbeatAt=old)
        self.assertFalse(scheduler.status()["executorAlive"])

    def test_surfaces_cron_error_from_broken_config_file(self) -> None:
        """配置文件被手改坏 → 页面要能显示原因（而不是静默没有下次执行）。"""
        self._config_file().write_text('{"enabled": true, "cron": "0 99 * * *"}', "utf-8")
        status = scheduler.status()
        self.assertIn("时", status["cronError"] or "")
        self.assertIsNone(status["nextRunAt"])


class TestRunNow(_ScheduleClientCase):
    """「立即执行一次」：只写触发请求，不在 api 进程里跑采集。"""

    def test_writes_trigger_file(self) -> None:
        result = scheduler.run_now()
        self.assertTrue(result["requested"])
        self.assertIn("requestedAt", result)
        self.assertTrue(self._trigger_file().exists(), "触发文件要落盘，执行器才看得到")
        # 触发文件是执行器消费的：api 侧不该顺手删掉它
        self.assertTrue(self._trigger_file().exists())

    def test_records_who_requested(self) -> None:
        """点按钮的人要一路带到执行器 —— 那一轮算在他名下，而不是笼统算"系统"。"""
        import json

        result = scheduler.run_now({"id": 7, "username": "alice"})
        self.assertEqual(result["userId"], 7)
        self.assertEqual(result["username"], "alice")
        written = json.loads(self._trigger_file().read_text("utf-8"))
        self.assertEqual(written["userId"], 7)
        self.assertEqual(written["username"], "alice")

    def test_works_without_user(self) -> None:
        """兼容：拿不到账号时（内部调用）也能写请求，只是归属留空。"""
        result = scheduler.run_now()
        self.assertTrue(self._trigger_file().exists())
        self.assertIn(result["username"], ("", None))

    def test_works_even_when_executor_is_offline(self) -> None:
        """执行器没起来时按钮也不报错 —— 请求先落盘，等它起来再跑（页面据心跳提示离线）。"""
        scheduler.run_now()
        self.assertTrue(self._trigger_file().exists())


if __name__ == "__main__":
    unittest.main()
