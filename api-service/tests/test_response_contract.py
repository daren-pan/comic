"""响应契约守卫 —— 防止 `schemas_out` 的模型与两个"外部事实"漂移。

## 为什么需要它

`response_model` 有两面：好处是 OpenAPI 终于能描述响应，代价是 FastAPI 会
**静默裁剪未声明的字段**（改前裸 dict 不过滤）。漏一个字段的后果是
"前端某字段变 `undefined`，后端不报错、日志也没有" —— 最难排查的那类问题。

本测试用三道断言把它挡在测试期（**纯逻辑：不连库、不起 HTTP**）：

1. **serializers 的输出 = 模型字段**：`to_comic` 等构造出的字段集合，
   必须与模型声明的一致（多一个少一个都红）。
2. **字段快照**：字段集合被改动时必须**显式**更新下面的 `CONTRACT` ——
   改契约这件事因此一定会出现在 diff 里，而不是悄悄溜进生产。
3. **派生列的 fail-fast**：`chapter_count` / `favorite_count` / `heat` **不是
   `comic` 表的列**，由 SQL 聚合算出（见 `comic_store._COMIC_COLS`）。
   某个查询忘了投影时，`to_comic` 必须**抛错**而不是静默给 0 ——
   后者会让榜单排序错乱而无人察觉。这条把该行为钉住。
"""
from __future__ import annotations

import unittest

from schemas_out import (
    AdminComicOut,
    AdminUserOut,
    ChapterOut,
    CommentOut,
    ComicOut,
    MessageItemOut,
    PageOut,
    SourceSearchItemOut,
    UserOut,
)
from serializers import to_admin_comic, to_admin_user, to_chapter, to_comment, to_comic, to_page, user_out

#: 字段快照 —— 契约变更时**必须**同步改这里（这是本文件的主要价值：让改动显式可见）。
CONTRACT: dict[str, set[str]] = {
    'ComicOut': {
        'id', 'title', 'author', 'category', 'status', 'description', 'cover',
        'latestChapterTitle', 'chapterCount', 'views', 'favoriteCount', 'heat',
        'updatedAt', 'source', 'tags',
    },
    'AdminComicOut': {
        'id', 'title', 'author', 'category', 'status', 'description', 'cover',
        'latestChapterTitle', 'chapterCount', 'views', 'favoriteCount', 'heat',
        'updatedAt', 'source', 'tags',
        # 治理字段（只给管理台）
        'listed', 'commentEnabled', 'sourceComicId',
    },
    'ChapterOut': {'id', 'comicId', 'title', 'orderNo', 'createdAt', 'isNew'},
    'PageOut': {'pageNo', 'imageUrl', 'width', 'height'},
    'CommentOut': {'id', 'content', 'author', 'authorId', 'createdAt'},
    'UserOut': {'id', 'username', 'nickname', 'role', 'avatarUrl', 'createdAt'},
    'AdminUserOut': {'id', 'username', 'nickname', 'role', 'createdAt'},
    'SourceSearchItemOut': {
        'source', 'sourceComicId', 'title', 'author', 'cover', 'status',
        'latestChapterTitle', 'tags', 'comicId',
    },
    'MessageItemOut': {
        'id', 'messageId', 'kind', 'level', 'title', 'body', 'params',
        'taskId', 'source', 'username', 'minRole', 'status', 'time', 'read',
    },
}

_MODELS = {
    'ComicOut': ComicOut, 'AdminComicOut': AdminComicOut, 'ChapterOut': ChapterOut,
    'PageOut': PageOut, 'CommentOut': CommentOut, 'UserOut': UserOut,
    'AdminUserOut': AdminUserOut, 'SourceSearchItemOut': SourceSearchItemOut,
    'MessageItemOut': MessageItemOut,
}


def _comic_row() -> dict:
    """一行"够 `to_comic` 用"的作品数据：**含三个派生列**（它们不在 `comic` 表上）。"""
    return {
        'id': 1, 'title': '标题', 'author': '作者', 'category': '科幻', 'status': '连载中',
        'description': '简介', 'latest_chapter_title': '第1话',
        'chapter_count': 3, 'views': 10, 'favorite_count': 2, 'heat': 1014,
        'sync_time': '2026-10-13T10:00:00.000Z', 'source': 'zaimanhua', 'tags': ['科幻'],
    }


def _chapter_row() -> dict:
    return {
        'id': 1, 'comic_id': 1, 'title': '第1话', 'chapter_no': 1,
        'sync_time': '2026-10-13T10:00:00.000Z', 'is_new': True,
    }


def _comment_row() -> dict:
    return {
        'id': 1, 'content': '内容', 'nickname': '昵称', 'username': 'login',
        'user_id': 2, 'created_at': '2026-10-13 10:00:00',
    }


def _user_row() -> dict:
    return {
        'id': 1, 'username': 'login', 'nickname': '昵称', 'role': 'user',
        'avatar_url': '', 'created_at': '2026-10-13T10:00:00',
    }


class TestFieldsAreUnchanged(unittest.TestCase):
    """字段快照：集合一变就红，迫使契约改动显式出现在 diff 里。"""

    def test_snapshot_matches_models(self):
        for name, expected in CONTRACT.items():
            self.assertEqual(
                set(_MODELS[name].model_fields), expected,
                f'{name} 的字段集合变了 —— 这是契约变更，请确认前端与文档同步后再更新本快照',
            )


class TestSerializersMatchModels(unittest.TestCase):
    """serializers 构造出的字段必须与模型声明**逐一对应**（多一个少一个都算漂移）。"""

    def _assert_same(self, model_cls, out, label: str):
        self.assertEqual(
            set(out.model_dump()), set(model_cls.model_fields),
            f'{label} 构造的字段与模型声明不一致',
        )

    def test_comic(self):
        self._assert_same(ComicOut, to_comic(_comic_row()), 'to_comic')

    def test_admin_comic(self):
        row = _comic_row() | {'listed': 1, 'comment_enabled': 0, 'source_comic_id': '87652'}
        self._assert_same(AdminComicOut, to_admin_comic(row), 'to_admin_comic')

    def test_chapter(self):
        self._assert_same(ChapterOut, to_chapter(_chapter_row()), 'to_chapter')

    def test_page(self):
        self._assert_same(PageOut, to_page({'page_no': 1}, 1, 2), 'to_page')

    def test_comment(self):
        self._assert_same(CommentOut, to_comment(_comment_row()), 'to_comment')

    def test_user(self):
        self._assert_same(UserOut, user_out(_user_row()), 'user_out')

    def test_admin_user(self):
        self._assert_same(AdminUserOut, to_admin_user(_user_row()), 'to_admin_user')


class TestTypesAreNormalized(unittest.TestCase):
    """库行的**值类型没有保证**（随驱动/取数层而变）→ 出参类型必须已归一。

    实测过的坑：同一句 SQL，用 MCP 工具查 `chapter_count` 是字符串 `"30"`，
    项目自己的存储层跑出来是 int —— `to_comic` 曾漏套 `int()`，靠驱动好心才没出事。
    """

    def test_counts_are_int_even_if_driver_returns_str(self):
        row = _comic_row() | {'chapter_count': '3', 'views': '10', 'favorite_count': '2', 'heat': '1014'}
        out = to_comic(row)
        for field in ('chapterCount', 'views', 'favoriteCount', 'heat'):
            self.assertIsInstance(getattr(out, field), int, f'{field} 未归一成 int')

    def test_timestamps_are_iso_strings(self):
        out = to_comic(_comic_row())
        self.assertIsInstance(out.updatedAt, str)
        self.assertIn('T', out.updatedAt, '时间必须用 T 分隔（空格形式会被 JS 的 new Date 误读）')

    def test_none_values_fall_back_to_empty(self):
        """库行里的 NULL 不能变成 500：这些字段有 `or ""` 兜底。"""
        row = _comic_row() | {'author': None, 'description': None, 'latest_chapter_title': None}
        out = to_comic(row)
        self.assertEqual(out.author, '')
        self.assertEqual(out.description, '')
        self.assertEqual(out.latestChapterTitle, '')


class TestDerivedColumnsFailFast(unittest.TestCase):
    """派生列没被投影时必须**抛错**，不能静默给 0（否则榜单排序错乱且无人察觉）。"""

    def test_missing_heat_raises(self):
        row = _comic_row()
        del row['heat']
        with self.assertRaises(KeyError):
            to_comic(row)

    def test_missing_sync_time_raises(self):
        row = _comic_row()
        del row['sync_time']
        with self.assertRaises(KeyError):
            to_comic(row)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
