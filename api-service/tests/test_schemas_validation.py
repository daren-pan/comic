"""入参边界（`api-service/schemas.py`）—— 把越界输入拦成 422，别让它一路走到 SQL 变成 500。

对应的两个**实测 500**（2026-09-21）：

- `PUT /api/users/{uid}/history` 传不存在的 `comicId` → 撞 `fk_hist_comic` 外键 → 500；
- 同一个接口传超长 uid → 撞 `history.user_id VARCHAR(64)` → 500。

uid 的长度/形态由路由上的 `Path(max_length=64, pattern=...)` 守（FastAPI 层，见
`routers/users.py` 的 `UserId` 与端到端探针）；**本文件守请求体这一侧**。

纯 Pydantic 断言：不连库、不装桩（`schemas` 不依赖 `core.db`）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from pydantic import ValidationError  # noqa: E402

from schemas import (  # noqa: E402
    MAX_KEYWORD_LEN,
    MAX_SOURCE_LEN,
    AdminHealBody,
    AdminImportBody,
    AdminSyncBody,
    HistoryPut,
)


class TestHistoryPut(unittest.TestCase):
    """阅读进度：id 必须是正整数（0 / 负数在库里永远是无效主键）。"""

    def test_valid(self):
        body = HistoryPut(comicId=5, chapterId=60, pageNo=3)
        self.assertEqual((body.comicId, body.chapterId, body.pageNo), (5, 60, 3))

    def test_page_no_defaults_to_one(self):
        self.assertEqual(HistoryPut(comicId=5, chapterId=60).pageNo, 1)

    def test_rejects_non_positive_ids(self):
        for bad in ({"comicId": 0, "chapterId": 1}, {"comicId": 1, "chapterId": 0},
                    {"comicId": -1, "chapterId": 1}, {"comicId": 1, "chapterId": -1},
                    {"comicId": 1, "chapterId": 1, "pageNo": 0}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                HistoryPut(**bad)


class TestAdminSyncBody(unittest.TestCase):
    """采集入参：`mode` 收口成两个字面量，`limit` 不能是 0/负数。"""

    def test_defaults_to_incremental(self):
        self.assertEqual(AdminSyncBody(source="zaimanhua").mode, "incremental")

    def test_accepts_both_modes(self):
        for mode in ("incremental", "full"):
            with self.subTest(mode=mode):
                self.assertEqual(AdminSyncBody(source="s", mode=mode).mode, mode)

    def test_rejects_mode_typo(self):
        """`mode="ful"` 这种笔误此前会**静默按增量跑**（用户以为跑了全量）。"""
        with self.assertRaises(ValidationError):
            AdminSyncBody(source="s", mode="ful")

    def test_rejects_bad_source_and_limit(self):
        for bad in ({"source": ""}, {"source": "x" * (MAX_SOURCE_LEN + 1)},
                    {"source": "s", "limit": 0}, {"source": "s", "limit": -5}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                AdminSyncBody(**bad)

    def test_accepts_limit(self):
        self.assertEqual(AdminSyncBody(source="s", limit=3).limit, 3)


class TestAdminHealBody(unittest.TestCase):
    """封面自愈：`keyword` 必填，且有上限（否则会拼出上千个 LIKE）。"""

    def test_rejects_empty_keyword(self):
        with self.assertRaises(ValidationError):
            AdminHealBody(keyword="")

    def test_rejects_overlong_keyword(self):
        with self.assertRaises(ValidationError):
            AdminHealBody(keyword="x" * (MAX_KEYWORD_LEN + 1))

    def test_accepts_normal_keyword(self):
        self.assertEqual(AdminHealBody(keyword="36,惡女").keyword, "36,惡女")


class TestAdminImportBody(unittest.TestCase):
    """按需导入：source 必填，first_chapters 要么不填（全量收目录）要么 >= 1。"""

    def test_rejects_empty_source(self):
        with self.assertRaises(ValidationError):
            AdminImportBody(source="")

    def test_rejects_non_positive_first_chapters(self):
        with self.assertRaises(ValidationError):
            AdminImportBody(source="s", first_chapters=0)

    def test_allows_omitting_first_chapters(self):
        self.assertIsNone(AdminImportBody(source="s").first_chapters)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
