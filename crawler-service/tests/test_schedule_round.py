"""定时任务「跑一轮」的动作分派（`scheduling/runner.py`）—— 纯逻辑，**不连库、不联网**。

被测的是这次新增的 `action`（2026-10-06）：

| 动作 | 走什么 | 说明 |
|---|---|---|
| `sync`（默认） | 逐源 `sync_source` | 单源失败不拖累其他源，摘要按"成功 n/m 个源" |
| `inspect` | 一次 `inspect_sync` | 转存 + 全表校验 + 恢复；**不含**手动巡检那步全库封面自愈 |

两者返回**同一形状**（含人话 `summary`），执行器与任务表不必关心动作差异 —— 这正是本文件要钉住的契约。

做法：把 `runner` 里的存储 / 图库 / 两个执行函数全换成桩（`unittest.mock.patch`），
于是"分派到谁、传了什么参数、摘要长什么样"都能断言，而不用真连 MySQL。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comic_crawler.scheduling import runner  # noqa: E402
from comic_crawler.scheduling.schedule import (  # noqa: E402
    ACTION_INSPECT,
    ACTION_SYNC,
    ScheduleConfig,
)


def _cfg(**kw) -> ScheduleConfig:
    base = dict(enabled=True, cron="0 3 * * *", action=ACTION_SYNC,
                sources=[], mode="incremental", limit=None, since=None)
    base.update(kw)
    return ScheduleConfig(**base)


class TestSyncRound(unittest.TestCase):
    """默认动作：逐源采集。"""

    def test_calls_sync_source_per_source_and_summarizes(self) -> None:
        calls: list[tuple] = []

        def fake_sync(source, mode, limit, since):
            calls.append((source, mode, limit, since))
            return {"summary": f"{source} 完成"}

        with patch.object(runner, "sync_source", fake_sync):
            out = runner.run_round(_cfg(sources=["a", "b"], mode="full", limit=3), "定时")

        self.assertEqual(calls, [("a", "full", 3, None), ("b", "full", 3, None)])
        self.assertEqual(out["action"], ACTION_SYNC)
        self.assertEqual(out["ok"], 2)
        self.assertEqual(out["failed"], [])
        self.assertEqual(out["summary"], "定时：成功 2/2 个源")

    def test_one_source_failure_does_not_stop_others(self) -> None:
        def fake_sync(source, mode, limit, since):
            if source == "boom":
                raise RuntimeError("站点 502")
            return {"summary": "ok"}

        with patch.object(runner, "sync_source", fake_sync):
            out = runner.run_round(_cfg(sources=["ok", "boom"]), "定时")

        self.assertEqual(out["ok"], 1)
        self.assertEqual(out["failed"], ["boom"])
        self.assertIn("失败 boom", out["summary"])
        self.assertFalse(out["results"]["boom"]["ok"])
        self.assertIn("502", out["results"]["boom"]["error"])


class TestInspectRound(unittest.TestCase):
    """`action=inspect`：走巡检，且**不**逐源采集。"""

    def _patches(self, seen: dict):
        def fake_inspect(storage, **kw):
            seen.update(kw)
            seen["storage"] = storage          # storage 是位置参数，单独收一下
            return {"checked": 10, "transferred": 2, "verified": 8, "recovered": 1, "invalid": 0}

        return (
            patch.object(runner, "inspect_sync", fake_inspect),
            patch.object(runner, "MySQLStorage", lambda: "STORAGE"),
            patch.object(runner, "LocalImageStore", lambda: "IMAGE_STORE"),
            patch.object(runner, "create_adapter", lambda name: f"ADAPTER:{name}"),
            patch.object(runner, "sync_source",
                         lambda *a, **kw: (_ for _ in ()).throw(AssertionError("巡检不该调采集"))),
        )

    def test_dispatches_to_inspect_with_single_source(self) -> None:
        seen: dict = {}
        patches = self._patches(seen)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            out = runner.run_round(_cfg(action=ACTION_INSPECT, sources=["zaimanhua"], since="2026-10-01"),
                                   "定时")

        self.assertEqual(seen["storage"], "STORAGE")
        self.assertEqual(seen["image_store"], "IMAGE_STORE")
        self.assertEqual(seen["source"], "zaimanhua", "恰好点名一个源 → 限定该源")
        self.assertEqual(seen["since"], "2026-10-01")
        self.assertEqual(out["action"], ACTION_INSPECT)
        self.assertEqual(out["ok"], 1)
        self.assertEqual(out["sources"], ["zaimanhua"])
        self.assertIn("巡检", out["summary"])
        self.assertIn("校验 10", out["summary"])

    def test_multiple_sources_means_whole_library(self) -> None:
        seen: dict = {}
        patches = self._patches(seen)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            out = runner.run_round(_cfg(action=ACTION_INSPECT, sources=["a", "b"]), "手动")

        self.assertIsNone(seen["source"], "点名多个源时不做限定（全库/全源）")
        self.assertEqual(out["sources"], [])
        self.assertIn("手动：巡检", out["summary"])


class TestRoundShape(unittest.TestCase):
    """两种动作的返回形状必须一致（执行器 / 任务表直接消费 `summary`）。"""

    def test_both_actions_expose_the_same_keys(self) -> None:
        with patch.object(runner, "sync_source", lambda *a, **kw: {"summary": "ok"}):
            sync_out = runner.run_round(_cfg(sources=["a"]), "定时")

        seen: dict = {}
        with patch.object(runner, "inspect_sync", lambda storage, **kw: seen.update(kw) or {"checked": 1}), \
             patch.object(runner, "MySQLStorage", lambda: None), \
             patch.object(runner, "LocalImageStore", lambda: None), \
             patch.object(runner, "create_adapter", lambda name: None):
            inspect_out = runner.run_round(_cfg(action=ACTION_INSPECT), "定时")

        for key in ("trigger", "action", "sources", "results", "ok", "failed", "summary"):
            self.assertIn(key, sync_out, key)
            self.assertIn(key, inspect_out, key)


if __name__ == "__main__":
    unittest.main()
