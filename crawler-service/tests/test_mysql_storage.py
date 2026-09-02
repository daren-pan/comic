"""MySQL 存储集成测试：连接本机 Docker MySQL（3307）验证接口一致性。

无 MySQL 环境时自动跳过（skip）。运行：
    PYTHONPATH=src python -m unittest tests.test_mysql_storage -v
"""
from __future__ import annotations

import unittest

from comic_crawler.fingerprint import build_fingerprint
from comic_crawler.models import ComicDetail


def _mysql_available() -> bool:
    try:
        from comic_crawler.mysql_storage import MySQLStorage

        s = MySQLStorage()
        s.stats()
        return True
    except Exception:
        return False


@unittest.skipUnless(_mysql_available(), "本机 MySQL 不可用，跳过 MySQL 集成测试")
class TestMySQLStorage(unittest.TestCase):
    def setUp(self):
        from comic_crawler.mysql_storage import MySQLStorage

        self.s = MySQLStorage()
        self._clean_test_data()

    def tearDown(self):
        self._clean_test_data()

    def _clean_test_data(self):
        """只删除测试创建的记录（source 以 test_ 前缀标记），不污染库内现有数据。"""
        with self.s._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM comic WHERE source LIKE 'test_%'")
                ids = [r["id"] for r in cur.fetchall()]
                if not ids:
                    return
                marks = ",".join(["%s"] * len(ids))
                cur.execute(f"DELETE FROM page WHERE chapter_id IN (SELECT id FROM chapter WHERE comic_id IN ({marks}))", ids)
                cur.execute(f"DELETE FROM chapter WHERE comic_id IN ({marks})", ids)
                cur.execute(f"DELETE FROM favorite WHERE comic_id IN ({marks})", ids)
                cur.execute(f"DELETE FROM history WHERE comic_id IN ({marks})", ids)
                cur.execute(f"DELETE FROM comic WHERE id IN ({marks})", ids)

    def test_upsert_and_dedup(self):
        a = ComicDetail(
            source="test_source", source_comic_id="1", title="测试漫",
            author="作者", status="连载", category="测试",
        )
        id1, new1 = self.s.upsert_comic(a, build_fingerprint(a.title, a.author))
        id2, new2 = self.s.upsert_comic(a, build_fingerprint(a.title, a.author))
        self.assertTrue(new1)
        self.assertFalse(new2)
        self.assertEqual(id1, id2)
        # 指纹去重：test_source 只保留 1 条（库内另有正式数据，不做全库断言）
        with self.s._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM comic WHERE source='test_source'")
                self.assertEqual(cur.fetchone()["c"], 1)

    def test_user_center(self):
        from comic_crawler.mysql_storage import MySQLUserStore

        u = MySQLUserStore()
        a = ComicDetail(source="test_source", source_comic_id="9", title="用户漫", author="作者")
        cid, _ = self.s.upsert_comic(a, build_fingerprint(a.title, a.author))
        u.set_favorite("t-user", cid, True)
        self.assertTrue(u.is_favorite("t-user", cid))
        self.assertEqual(u.list_favorites("t-user"), [cid])
        u.set_favorite("t-user", cid, False)
        self.assertFalse(u.is_favorite("t-user", cid))
        u.upsert_history("t-user", cid, 1, 5)
        rows = u.list_history("t-user")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["page_no"], 5)
        u.delete_history("t-user", cid)
        self.assertEqual(len(u.list_history("t-user")), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
