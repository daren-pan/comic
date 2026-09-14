"""日志查询条件的拼装（`build_filters`）—— **纯函数测试，不连库**。

为什么要守：查询页的每个筛选项最终都落到这里。条件写错（比如把 `level` 拼成 `levels`、
忘了切 query、时间窗边界算错）在页面上表现为"筛了没反应"，而不是报错 —— 靠肉眼很难发现。
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comic_crawler.storage.mysql import build_filters  # noqa: E402


class TestBuildFilters(unittest.TestCase):
    def test_no_condition_gives_empty_where(self):
        conds, params = build_filters()
        self.assertEqual(conds, [])
        self.assertEqual(params, [])

    def test_level_is_upper_cased(self):
        conds, params = build_filters(level="warning")
        self.assertEqual(conds, ["level = %s"])
        self.assertEqual(params, ["WARNING"])

    def test_each_scalar_condition(self):
        for kw, cond in (
            ({"source": "zaimanhua"}, "source = %s"),
            ({"event": "transfer.fail"}, "event = %s"),
            ({"task_id": "transfer-2-1"}, "task_id = %s"),
        ):
            conds, params = build_filters(**kw)
            self.assertEqual(conds, [cond], kw)
            self.assertEqual(len(params), 1, kw)

    def test_comic_id_cast_to_int(self):
        conds, params = build_filters(comic_id="151")
        self.assertEqual(conds, ["comic_id = %s"])
        self.assertEqual(params, [151])

    def test_keyword_searches_four_columns(self):
        conds, params = build_filters(keyword="  午夜  ")
        self.assertEqual(len(conds), 1)
        self.assertIn("message LIKE %s", conds[0])
        self.assertIn("comic_title LIKE %s", conds[0])
        self.assertIn("chapter_title LIKE %s", conds[0])
        self.assertIn("reason LIKE %s", conds[0])
        self.assertEqual(params, ["%午夜%"] * 4)   # 首尾空白已 strip

    def test_conditions_are_anded(self):
        conds, params = build_filters(level="WARNING", source="zaimanhua", event="transfer.fail")
        self.assertEqual(conds, ["level = %s", "source = %s", "event = %s"])
        self.assertEqual(params, ["WARNING", "zaimanhua", "transfer.fail"])

    def test_since_date_means_that_day_0000(self):
        conds, params = build_filters(since="2026-09-14")
        self.assertEqual(conds, ["created_at >= %s"])
        self.assertEqual(params, ["2026-09-14"])   # 交给 MySQL 当 00:00:00 比较

    def test_until_date_includes_whole_day(self):
        """截止只给日期 = **含当天全天**（内部转成次日 00:00 排他）。"""
        conds, params = build_filters(until="2026-09-14")
        self.assertEqual(conds, ["created_at < %s"])
        self.assertEqual(params[0], datetime(2026, 9, 15, 0, 0))

    def test_until_with_time_is_inclusive(self):
        """带时刻的截止 = 含该时刻（`<=`，值原样交给 MySQL 比较）。"""
        conds, params = build_filters(until="2026-09-14 16:00:00")
        self.assertEqual(conds, ["created_at <= %s"])
        self.assertEqual(params, ["2026-09-14 16:00:00"])

    def test_blank_values_are_ignored(self):
        """空串/None 视为"不限"，不能拼出 `level = ''`（否则页面点"全部"会查不到东西）。"""
        conds, params = build_filters(level="", source=None, keyword="  ", task_id="")
        self.assertEqual(conds, [])
        self.assertEqual(params, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
