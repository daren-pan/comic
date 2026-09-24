"""收藏 / 历史列表的批量取数（消除逐条 `get_comic` 的 N+1）。

**纯逻辑、不连库**：在导入 `routers.users` / `services.tags` 之前，把 `core.db` 换成桩模块
（`tests/_stub_db.py`，`sys.modules` 预置），因此 `MySQLStorage` 根本不会被实例化，也不会打开连接。

⚠️ 桩**必须**用 `_stub_db` 那一份，不要在本文件里再造一个：`sys.modules['core.db']` 是进程级全局，
而应用模块是 `from core.db import db`（导入时绑定值）—— 两份桩会互相污染（详见该模块文件头）。

为什么值得单独守一条：这两个接口原先 `rows = [db.get_comic(cid) for cid in ...]` ——
而 `MySQLStorage` 每次调用都新建连接，代价随收藏 / 历史条数线性增长。
`/api/comics` 的标签 N+1 已经因此修过一次（见 `services.tags.attach_tags`），
这里用"断言逐条查询次数为 0"把同类退化拦住。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for _p in (str(APP_DIR), str(TESTS_DIR)):   # tests 目录也入 path：单跑本文件时 _stub_db 才可导入
    if _p not in sys.path:
        sys.path.insert(0, _p)


from _stub_db import DB as _DB, USERS as _USERS, install_stub  # noqa: E402

install_stub()  # 必须在导入应用模块之前装桩

from fastapi import HTTPException  # noqa: E402

from routers.users import (  # noqa: E402  （必须在装桩之后导入）
    favorites,
    history,
    put_history,
    remove_history,
)
from schemas import HistoryPut  # noqa: E402


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

        out = history("u1", user=None)

        self.assertEqual([e["comicId"] for e in out["data"]], [6, 5])
        self.assertEqual(_DB.single_calls, [])
        self.assertEqual(_DB.batch_calls, [[6, 999, 5]])

    def test_history_keeps_entry_fields(self):
        """历史条目自带字段（章节 / 页码 / 时间）原样保留。"""
        _DB.comics = {5: _row(5)}
        _USERS.history_rows = [_history_row(5, 50)]

        entry = history("u1", user=None)["data"][0]

        self.assertEqual(entry["chapterId"], 50)
        self.assertEqual(entry["pageNo"], 1)
        self.assertEqual(entry["chapterTitle"], "第1话")
        self.assertEqual(entry["readAt"], "2026-09-14 12:00:00")
        self.assertEqual(entry["comic"]["id"], 5)

    # ---------------- 历史的归属与写入校验（2026-09-21 修 IDOR + 两个 500） ----------------

    def test_history_anonymous_uses_path_uid(self):
        """游客（无 token）仍按路径里的匿名 id 归属 —— 匿名续读这个能力不能被修没了。"""
        history("anon-uuid", user=None)
        self.assertEqual(_USERS.history_reads, ["anon-uuid"])

    def test_history_logged_in_uses_account_id(self):
        """登录后归属**账号 id**，路径里的 uid 不再被信任。

        这是 IDOR 的正题：此前无条件用 URL 里的 uid，而那个 UUID 是前端明文拼在路径上的
        （会进访问日志 / 浏览器历史 / Referer），等于"知道 UUID 就能读写删别人的历史"。
        """
        history("someone-elses-uuid", user={"id": 7})
        self.assertEqual(_USERS.history_reads, ["7"])

    def test_put_history_rejects_unknown_chapter(self):
        """章节不存在 → 404。此前会一路走到 `fk_hist_comic` 外键失败，返回 **500**。"""
        with self.assertRaises(HTTPException) as ctx:
            put_history("u1", HistoryPut(comicId=5, chapterId=999, pageNo=1), user=None)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(_USERS.history_writes, [])

    def test_put_history_rejects_chapter_of_other_comic(self):
        """章节属于**别的作品** → 404（挡住"合法 comicId + 乱填 chapterId"写进脏进度）。"""
        _DB.chapters = {60: {"id": 60, "comic_id": 6}}
        with self.assertRaises(HTTPException) as ctx:
            put_history("u1", HistoryPut(comicId=5, chapterId=60, pageNo=1), user=None)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(_USERS.history_writes, [])

    def test_put_history_writes_to_resolved_owner(self):
        """校验通过 → 按**解析后**的归属写入（登录用户写账号 id）。"""
        _DB.chapters = {60: {"id": 60, "comic_id": 5}}
        put_history("anon-uuid", HistoryPut(comicId=5, chapterId=60, pageNo=3), user={"id": 7})
        self.assertEqual(_USERS.history_writes, [("7", 5, 60, 3)])

    def test_remove_history_uses_resolved_owner(self):
        """删除同样按解析后的归属 —— 否则会"删不掉自己的历史"。"""
        remove_history("anon-uuid", 5, user={"id": 7})
        self.assertEqual(_USERS.history_deletes, [("7", 5)])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
