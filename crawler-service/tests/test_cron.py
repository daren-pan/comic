"""cron 表达式解析与时刻计算（`comic_crawler.scheduling.cron`）—— 纯逻辑，不连库、不联网。

为什么值得钉死：定时任务**全靠这个引擎判定"什么时候跑"**，算错的表现是"该跑不跑"或
"一小时跑几十次"，两者都不会报错、只会静静地发生。这里覆盖：

- 合法写法：`*` / `*/N` / 单值 / 区间 / 区间步长 / 逗号列表；
- 非法写法：段数不对、越界、单值带步长、区间颠倒、空列表项 —— 一律 `ValueError`（消息带段名）；
- 周日 `0` 与 `7` 等价；
- **日与周同时受限 → 取「或」**（Vixie cron 标准语义）；
- `next_after`：同日稍后 / 恰好命中要往后推 / 跨天 / 跨月 / 闰年 2 月 29 日。
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comic_crawler.scheduling.cron import DEFAULT_CRON, parse_cron  # noqa: E402


class TestParse(unittest.TestCase):
    """表达式解析与非法输入。"""

    def test_common_expressions(self) -> None:
        cases = {
            # 表达式: (分钟数, 小时集合或 None, 日数)
            "0 3 * * *": (1, {3}, 31),
            "*/15 * * * *": (4, None, 31),
            "0 */6 * * *": (1, {0, 6, 12, 18}, 31),
            "0 9-18/2 * * 1,3,5": (1, {9, 11, 13, 15, 17}, 31),
            "0 0 29 2 *": (1, {0}, 1),
        }
        for expr, (n_minutes, hours, n_days) in cases.items():
            spec = parse_cron(expr)
            self.assertEqual(spec.expression, expr)
            self.assertEqual(len(spec.minutes), n_minutes, expr)
            if hours is not None:
                self.assertEqual(set(spec.hours), hours, expr)
            if n_days is not None:
                self.assertEqual(len(spec.days), n_days, expr)

    def test_star_and_lists(self) -> None:
        spec = parse_cron("0,30 8,20 * * *")
        self.assertEqual(set(spec.minutes), {0, 30})
        self.assertEqual(set(spec.hours), {8, 20})
        self.assertEqual(len(spec.days), 31)
        self.assertFalse(spec.dom_restricted)
        self.assertFalse(spec.dow_restricted)

    def test_sunday_0_and_7_equivalent(self) -> None:
        self.assertEqual(parse_cron("0 3 * * 0").weekdays, parse_cron("0 3 * * 7").weekdays)
        self.assertEqual(set(parse_cron("0 3 * * 7").weekdays), {0})

    def test_field_count_mismatch(self) -> None:
        for expr in ("", "0 3 * *", "0 3 * * * *"):
            with self.assertRaises(ValueError, msg=expr):
                parse_cron(expr)

    def test_out_of_range(self) -> None:
        for expr in ("60 0 * * *", "0 24 * * *", "0 0 0 * *", "0 0 32 * *", "0 0 * 13 *", "0 0 * * 8"):
            with self.assertRaises(ValueError, msg=expr):
                parse_cron(expr)

    def test_bad_syntax(self) -> None:
        for expr in ("0 3 * * abc", "5/2 * * * *", "0 5-3 * * *", "0 3 * * 1,,2", "-1 0 * * *"):
            with self.assertRaises(ValueError, msg=expr):
                parse_cron(expr)

    def test_error_message_names_the_field(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            parse_cron("0 99 * * *")
        self.assertIn("时", str(ctx.exception))

    def test_default_expression_is_daily_0300(self) -> None:
        self.assertEqual(DEFAULT_CRON, "0 3 * * *")


class TestMatching(unittest.TestCase):
    """分钟级命中与「日/周」语义。"""

    def test_matches_exact_minute(self) -> None:
        spec = parse_cron("0 3 * * *")
        self.assertTrue(spec.matches(datetime(2026, 10, 6, 3, 0)))
        self.assertFalse(spec.matches(datetime(2026, 10, 6, 3, 1)))
        self.assertFalse(spec.matches(datetime(2026, 10, 6, 4, 0)))

    def test_every_15_minutes(self) -> None:
        spec = parse_cron("*/15 * * * *")
        for minute in (0, 15, 30, 45):
            self.assertTrue(spec.matches(datetime(2026, 10, 6, 9, minute)), minute)
        for minute in (1, 14, 46, 59):
            self.assertFalse(spec.matches(datetime(2026, 10, 6, 9, minute)), minute)

    def test_weekday_field(self) -> None:
        spec = parse_cron("0 3 * * 1")  # 周一
        self.assertTrue(spec.matches(datetime(2026, 10, 5, 3, 0)))    # 2026-10-05 是周一
        self.assertFalse(spec.matches(datetime(2026, 10, 6, 3, 0)))   # 周二

    def test_day_of_month_field(self) -> None:
        spec = parse_cron("0 3 1 * *")
        self.assertTrue(spec.matches(datetime(2026, 11, 1, 3, 0)))
        self.assertFalse(spec.matches(datetime(2026, 11, 2, 3, 0)))

    def test_dom_and_dow_restricted_means_or(self) -> None:
        """标准语义：日与周**都**受限时取「或」—— `0 3 1 * 1` = 每月 1 号或每周一。"""
        spec = parse_cron("0 3 1 * 1")
        self.assertTrue(spec.matches(datetime(2026, 10, 1, 3, 0)))    # 1 号（周四）
        self.assertTrue(spec.matches(datetime(2026, 10, 5, 3, 0)))    # 周一
        self.assertFalse(spec.matches(datetime(2026, 10, 6, 3, 0)))   # 周二且非 1 号
        # 只有日受限（周是 *）→ 退回「且」
        only_dom = parse_cron("0 3 1 * *")
        self.assertFalse(only_dom.matches(datetime(2026, 10, 5, 3, 0)))


class TestNextAfter(unittest.TestCase):
    """`next_after`：严格晚于给定时刻的下一次命中。"""

    def test_same_day_later(self) -> None:
        spec = parse_cron("0 3 * * *")
        self.assertEqual(spec.next_after(datetime(2026, 10, 6, 2, 0)), datetime(2026, 10, 6, 3, 0))

    def test_exactly_on_fire_time_goes_to_next_day(self) -> None:
        spec = parse_cron("0 3 * * *")
        self.assertEqual(spec.next_after(datetime(2026, 10, 6, 3, 0)), datetime(2026, 10, 7, 3, 0))

    def test_interval_expression_rolls_forward(self) -> None:
        spec = parse_cron("*/15 * * * *")
        self.assertEqual(spec.next_after(datetime(2026, 10, 6, 10, 7)), datetime(2026, 10, 6, 10, 15))
        self.assertEqual(spec.next_after(datetime(2026, 10, 6, 10, 45)), datetime(2026, 10, 6, 11, 0))

    def test_weekly_rolls_to_next_week(self) -> None:
        spec = parse_cron("0 3 * * 1")
        # 2026-10-06 是周二 → 下一个周一 10-12
        self.assertEqual(spec.next_after(datetime(2026, 10, 6, 9, 0)), datetime(2026, 10, 12, 3, 0))

    def test_leap_day_is_found(self) -> None:
        spec = parse_cron("0 0 29 2 *")
        self.assertEqual(spec.next_after(datetime(2026, 3, 1)), datetime(2028, 2, 29, 0, 0))

    def test_impossible_expression_returns_none(self) -> None:
        """`2 月 30 号` 永远不命中 → 搜索上界内无解，返回 None（而不是死循环）。"""
        self.assertIsNone(parse_cron("0 0 30 2 *").next_after(datetime(2026, 1, 1)))


if __name__ == "__main__":
    unittest.main()
