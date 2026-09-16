"""收藏 / 历史列表的批量取数（消除逐条 `get_comic` 的 N+1）。

**纯逻辑、不连库**：在导入 `routers.users` / `serializers` 之前，把 `core.db` 换成桩模块
（`sys.modules` 预置），因此 `MySQLStorage` 根本不会被实例化，也不会打开任何连接。

为什么值得单独守一条：这两个接口原先 `rows = [db.get_comic(cid) for cid in ...]` ——
而 `MySQLStorage` 每次调用都新建连接，代价随收藏 / 历史条数线性增长。
`/api/comics` 的标签 N+1 已经因此修过一次（见 `serializers.attach_tags`），
这里用"断言逐条查询次数为 0"把同类退化拦住。
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class FakeDB:
    """记录调用次数的假存储 —— 只实现本测试触达的方法。"""

    def __init__(self) -> None:
        self.comics: dict[int, dict] = {}
        self.batch_calls: list[list[int]] = []
        self.single_calls: list[int] = []

    def reset(self) -> None:
        self.comics = {}
        self.batch_calls = []
        self.single_calls = []

    # --- 被路由器 / 序列化层调用 ---
    def get_comics_by_ids(self, comic_ids: list[int]) -> dict[int, dict]:
        if not comic_ids:                    # 与 MySQLStorage 一致：空输入直接返回，不发查询
            return {}
        self.batch_calls.append(list(comic_ids))
        return {i: self.comics[i] for i in comic_ids if i in self.comics}

    def get_comic(self, comic_id: int):
        self.single_calls.append(comic_id)          # ← 出现即说明 N+1 回来了
        return self.comics.get(comic_id)

    def get_comic_tags_bulk(self, comic_ids: list[int]) -> dict[int, list[str]]:
        return {}

    def get_comic_tags(self, comic_id: int) -> list[str]:
        return []


class FakeUsers:
    """假用户中心：只给列表接口供 id / 历史行。"""

    def __init__(self) -> None:
        self.fav_ids: list[int] = []
        self.history_rows: list[dict] = []

    def reset(self) -> None:
        self.fav_ids = []
        self.history_rows = []

    def list_favorites(self, user_id: str) -> list[int]:
        return list(self.fav_ids)

    def list_history(self, user_id: str) -> list[dict]:
        return list(self.history_rows)


_DB = FakeDB()
_USERS = FakeUsers()

# 预置桩模块：必须在下面 import 应用模块之前完成
_STUB = types.ModuleType("core.db")
_STUB.db = _DB
_STUB.users = _USERS
sys.modules["core.db"] = _STUB

from routers.users import favorites, history   # noqa: E402  （必须在装桩之后导入）


def _row(comic_id: int, title: str = "") -> dict:
    """一行"够 to_comic 用"的作品数据。"""
    return {
        "id": comic_id,
        "title": title or f"作品{comic_id}",
        "author": "某作者",
        "category": "测试",
        "status": "连载中",
        "description": "",
        "latest_chapter_title": "第1话",
        "chapter_count": 3,
        "views": 10,
        "favorite_count": 1,
        "heat": 1012,
        "sync_time": "2026-09-14 12:00:00",
        "source": "zaimanhua",
    }


def _history_row(comic_id: int, chapter_id: int) -> dict:
    return {
        "comic_id": comic_id,
        "chapter_id": chapter_id,
        "page_no": 1,
        "read_at": "2026-09-14 12:00:00",
        "chapter_title": "第1话",
    }


class TestBatchListing(unittest.TestCase):
    def setUp(self) -> None:
        _DB.reset()
        _USERS.reset()

    # ---------------- 收藏 ----------------

    def test_favorites_use_one_batch_query(self):
        """一次批量取回，且保持收藏顺序（倒序），没有逐条查询。"""
        _DB.comics = {i: _row(i) for i in (11, 12, 13)}
        _USERS.fav_ids = [13, 12, 11]

        out = favorites("u1", user={"id": 1})

        self.assertEqual([c["id"] for c in out["data"]], [13, 12, 11])
        self.assertEqual(_DB.single_calls, [])            # ← 没有逐条 get_comic
        self.assertEqual(_DB.batch_calls, [[13, 12, 11]])  # ← 就一次

    def test_favorites_skip_missing_comic(self):
        """库里已不存在的作品直接跳过，不让接口整体失败。"""
        _DB.comics = {11: _row(11)}
        _USERS.fav_ids = [11, 999]

        out = favorites("u1", user={"id": 1})

        self.assertEqual([c["id"] for c in out["data"]], [11])

    def test_favorites_empty_returns_empty(self):
        """空收藏不做任何查询。"""
        out = favorites("u1", user={"id": 1})
        self.assertEqual(out["data"], [])
        self.assertEqual(_DB.batch_calls, [])

    def test_favorites_include_source_and_tags(self):
        """来源是单个字符串（一行=一个收录源），标签为数组。"""
        _DB.comics = {11: _row(11)}
        _USERS.fav_ids = [11]

        item = favorites("u1", user={"id": 1})["data"][0]

        self.assertEqual(item["source"], "zaimanhua")
        self.assertEqual(item["tags"], [])

    # ---------------- 历史 ----------------

    def test_history_use_one_batch_query(self):
        """历史同样批量取作品，并保持阅读时间倒序；作品已删则跳过。"""
        _DB.comics = {5: _row(5), 6: _row(6)}
        _USERS.history_rows = [
            _history_row(6, 60),
            _history_row(999, 1),     # 作品已不存在 → 跳过
            _history_row(5, 50),
        ]

        out = history("u1")

        self.assertEqual([e["comicId"] for e in out["data"]], [6, 5])
        self.assertEqual(_DB.single_calls, [])
        self.assertEqual(_DB.batch_calls, [[6, 999, 5]])

    def test_history_keeps_entry_fields(self):
        """历史条目自带字段（章节 / 页码 / 时间）原样保留。"""
        _DB.comics = {5: _row(5)}
        _USERS.history_rows = [_history_row(5, 50)]

        entry = history("u1")["data"][0]

        self.assertEqual(entry["chapterId"], 50)
        self.assertEqual(entry["pageNo"], 1)
        self.assertEqual(entry["chapterTitle"], "第1话")
        self.assertEqual(entry["readAt"], "2026-09-14 12:00:00")
        self.assertEqual(entry["comic"]["id"], 5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
