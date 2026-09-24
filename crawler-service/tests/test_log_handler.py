"""日志落库Handler 的取值逻辑（`record_to_row`）。

**纯逻辑：不连库、不起线程** —— 被测函数只吃一个 `LogRecord` 吐一行 dict。
（真正写库的部分由 `MySQLLogStore.insert_many` 负责，见 `test_log_query.py` 对查询条件的断言。）

守这些点的原因：这一层是"日志能不能按作品/章节/任务筛出来"的唯一入口 ——
字段名写错、`extra` 取错、类型没转成 int，查询页筛选就会静默失效。
"""
from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comic_core import logctx  # noqa: E402
from comic_core.storage.mysql import record_to_row  # noqa: E402


def _record(
    msg: str = "转存失败 | x",
    args: tuple = (),
    name: str = "comic_crawler.images.transfer",
    level: int = logging.WARNING,
    exc_info=None,
    **extra,
) -> logging.LogRecord:
    rec = logging.LogRecord(
        name=name, level=level, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=exc_info,
    )
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


class TestRecordToRow(unittest.TestCase):
    def test_generic_fields(self):
        row = record_to_row(_record("hello %s", ("world",)))
        self.assertEqual(row["message"], "hello world")   # 参数已渲染
        self.assertEqual(row["level"], "WARNING")
        self.assertEqual(row["logger"], "comic_crawler.images.transfer")
        self.assertTrue(hasattr(row["created_at"], "year"))
        self.assertEqual(row["exc_type"], "")
        self.assertEqual(row["exc_text"], "")

    def test_business_fields_from_extra(self):
        row = record_to_row(_record(log_fields={
            "event": "transfer.fail", "source": "zaimanhua",
            "comic_id": 151, "comic_title": "午夜心旋律",
            "chapter_id": 679, "chapter_title": "第03话",
            "endpoint": "https://m.zaimanhua.com/api/...", "pages": 37,
            "reason": "重拉返回 0 页（源站侧无内容）",
        }))
        self.assertEqual(row["event"], "transfer.fail")
        self.assertEqual(row["comic_id"], 151)
        self.assertEqual(row["chapter_title"], "第03话")
        self.assertEqual(row["pages"], 37)

    def test_missing_or_bad_extra_does_not_break(self):
        """没有 extra / extra 不是 dict / 字段是脏值 → 留空或 None，绝不抛异常。"""
        self.assertEqual(record_to_row(_record())["source"], "")
        self.assertEqual(record_to_row(_record(log_fields="oops"))["source"], "")
        row = record_to_row(_record(log_fields={"comic_id": "abc", "pages": "", "event": None}))
        self.assertIsNone(row["comic_id"])   # 转不成 int → None（不是 "abc"）
        self.assertIsNone(row["pages"])
        self.assertEqual(row["event"], "")

    def test_string_numbers_are_coerced(self):
        """查询页按 comic_id 筛，列是 INT —— 传进来是字符串也得转成 int。"""
        row = record_to_row(_record(log_fields={"comic_id": "151", "chapter_id": "679", "pages": 37}))
        self.assertEqual(row["comic_id"], 151)
        self.assertEqual(row["chapter_id"], 679)

    def test_task_context_from_logctx(self):
        """任务信息从 logctx 来（任务线程绑定过就有）。"""
        logctx.bind_task("transfer-2-1789373866", "transfer")
        try:
            row = record_to_row(_record())
        finally:
            logctx.bind_task("", "")
        self.assertEqual(row["task_id"], "transfer-2-1789373866")
        self.assertEqual(row["task_type"], "transfer")

    def test_explicit_extra_overrides_context(self):
        """显式 extra 优先于上下文（允许某条日志标注到别的任务上）。"""
        logctx.bind_task("sync-1-1", "sync")
        try:
            row = record_to_row(_record(log_fields={"task_id": "transfer-9-9"}))
        finally:
            logctx.bind_task("", "")
        self.assertEqual(row["task_id"], "transfer-9-9")

    def test_exception_is_captured(self):
        try:
            raise ValueError("boom")
        except ValueError:
            row = record_to_row(_record("处理失败", exc_info=sys.exc_info()))
        self.assertEqual(row["exc_type"], "ValueError")
        self.assertIn("ValueError: boom", row["exc_text"])
        self.assertIn("Traceback", row["exc_text"])

    def test_long_text_is_clipped(self):
        """message / exc_text 是 TEXT 列，单条日志不能撑爆它。"""
        row = record_to_row(_record("x" * 50000))
        self.assertLessEqual(len(row["message"]), 4000)
        self.assertTrue(row["message"].endswith("..."))

    def test_all_columns_present(self):
        """行必须覆盖 log_record 的全部业务列（少一列 insert 就会报错）。"""
        from comic_core.storage.mysql.log_store import LOG_COLUMNS

        self.assertEqual(set(record_to_row(_record())), set(LOG_COLUMNS))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
