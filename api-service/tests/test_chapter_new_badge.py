"""章节角标口径：`services.chapters.mark_latest_batch` + `serializers.to_chapter`。

**纯逻辑、不连库**（两个被测模块都不 import `core.db`，所以不需要 `_stub_db` 桩）。

口径（用户 2026-10-09 决定）：标「最近一批入库」的章节 —— 采集 / 按需导入都只把
**库内缺失**的章节一次写一批（`chapter.sync_time` 因此同批相同），所以 `sync_time`
最大的那一批就是"这部作品最近一次新增的章节"。首次收录（全部同批）**照样全标**。
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from serializers import to_chapter  # noqa: E402
from services.chapters import mark_latest_batch  # noqa: E402


def _ch(cid: int, no: int, sync_time: datetime) -> dict:
    """一行"够 to_chapter 用"的章节数据。"""
    return {
        "id": cid,
        "comic_id": 7,
        "chapter_no": no,
        "title": f"第{no}话",
        "source_chapter_id": str(no),
        "sync_time": sync_time,
    }


class TestMarkLatestBatch(unittest.TestCase):
    def test_empty_is_safe(self):
        """空列表不炸（作品没有章节）。"""
        self.assertEqual(mark_latest_batch([]), [])

    def test_single_batch_all_marked(self):
        """首次收录：全部同批 → 全标（用户决定：首收不打折扣）。"""
        t = datetime(2026, 10, 9, 10, 0, 0)
        rows = [_ch(i, i, t) for i in (1, 2, 3)]

        mark_latest_batch(rows)

        self.assertEqual([r["is_new"] for r in rows], [True, True, True])

    def test_only_newest_batch_marked(self):
        """两批：只有后入库的那批是 True，早一批原样 False。"""
        old, new = datetime(2026, 9, 16, 9, 32, 50), datetime(2026, 10, 9, 10, 15, 41)
        rows = [_ch(1, 1, old), _ch(2, 2, old), _ch(3, 3, new)]

        mark_latest_batch(rows)

        self.assertEqual([r["is_new"] for r in rows], [False, False, True])

    def test_returns_same_list_for_chaining(self):
        """原地写入并返回同一列表（与 `services.tags.attach_tags` 同一约定）。"""
        rows = [_ch(1, 1, datetime(2026, 10, 9, 10, 0, 0))]
        self.assertIs(mark_latest_batch(rows), rows)

    def test_multi_batch_only_max_wins(self):
        """三批：只有最大那批。"""
        times = [datetime(2026, 9, 16), datetime(2026, 9, 20), datetime(2026, 10, 9)]
        rows = [_ch(i, i, t) for i, t in enumerate(times, start=1)]

        mark_latest_batch(rows)

        self.assertEqual([r["is_new"] for r in rows], [False, False, True])


class TestToChapter(unittest.TestCase):
    def test_exposes_is_new(self):
        """注入 `is_new` 后按驼峰 `isNew` 出参。"""
        row = _ch(1, 1, datetime(2026, 10, 9, 10, 0, 0))
        mark_latest_batch([row])

        out = to_chapter(row)

        self.assertTrue(out["isNew"])
        self.assertEqual(out["createdAt"], row["sync_time"])

    def test_missing_mark_defaults_false(self):
        """没注入 `is_new`（别处调用）→ False，**不回退查库**（与 tags 同一约定）。"""
        out = to_chapter(_ch(1, 1, datetime(2026, 10, 9, 10, 0, 0)))
        self.assertFalse(out["isNew"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
