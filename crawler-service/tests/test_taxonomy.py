"""标签归一化测试（纯逻辑，不连库不联网）。

覆盖：
- normalize_tag：大小写 / 全角半角 / 连字符 / 空格 / 撇号 / 间隔号 折叠成同一键；
- canonical_tag：跨源跨语言同义命中（Comedy+搞笑→喜剧、ゆり+Girls' Love→百合）；
- 刻意保留原文：形态类（Web Comic / Full Color）、更新季（2026春）、敏感标签（Loli 等）；
- 幂等性与边界：canonical(canonical(x)) == canonical(x)、空串 / None；
- 词表自检：规范名映射到自身、同一别名不得指向两个规范名（防止写表时冲突）；
- 写入路径：`MySQLStorage._sync_tags` 落库前确实做了归一化（假 cursor 断言 SQL 参数）。

运行：PYTHONPATH=src python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.storage.mysql.comic_store import MySQLStorage
from comic_crawler.taxonomy import SYNONYMS_PATH, canonical_tag, is_known, normalize_tag


class _FakeCursor:
    """只记录 SQL 的假游标（验证 `_sync_tags` 行为，不连库）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple | None]] = []

    def execute(self, sql: str, args: tuple | None = None):
        self.calls.append((" ".join(sql.split()), args))
        return 1

    def fetchone(self):
        return {"id": 1}


class TestTagTaxonomy(unittest.TestCase):
    # ------------------------------------------------------------------
    def test_normalize_folds_variants(self):
        same = [
            "Sci-Fi",
            "Sci Fi",
            "scifi",
            "  SCI-FI  ",
            "ＳＣＩ－ＦＩ",  # 全角
        ]
        keys = {normalize_tag(s) for s in same}
        self.assertEqual(keys, {"scifi"})
        # 撇号 / 空格 / 间隔号 均被折叠
        self.assertEqual(normalize_tag("Boys' Love"), normalize_tag("Boys Love"))
        self.assertEqual(normalize_tag("Boys’ Love"), normalize_tag("boys-love"))
        self.assertEqual(normalize_tag("girls · love"), normalize_tag("Girls Love"))

    def test_canonical_hits_across_sources(self):
        # 同一概念的不同源写法 -> 同一规范名
        self.assertEqual(canonical_tag("Comedy"), "喜剧")
        self.assertEqual(canonical_tag("搞笑"), "喜剧")
        self.assertEqual(canonical_tag("欢乐向"), "喜剧")
        self.assertEqual(canonical_tag("Romance"), "恋爱")
        self.assertEqual(canonical_tag("爱情"), "恋爱")
        self.assertEqual(canonical_tag("School Life"), "校园")
        self.assertEqual(canonical_tag("Slice of Life"), "日常")
        self.assertEqual(canonical_tag("Action"), "动作")
        self.assertEqual(canonical_tag("热血"), "动作")
        self.assertEqual(canonical_tag("武侠"), "武侠")
        self.assertEqual(canonical_tag("Martial Arts"), "武侠")
        # 跨语言（日文）
        self.assertEqual(canonical_tag("ゆり"), "百合")
        self.assertEqual(canonical_tag("Girls' Love"), "百合")
        # 写法差异（连字符/大小写）也能命中
        self.assertEqual(canonical_tag("sci fi"), "科幻")
        self.assertEqual(canonical_tag("SUPERNATURAL"), "神魔")

    def test_unmapped_kept_verbatim(self):
        """形态类 / 更新季 / 敏感标签不做映射，原样保留（避免把错译固化成规范名）。"""
        for name in ("Web Comic", "Full Color", "Long Strip", "Oneshot", "Doujinshi",
                     "2026春", "AA", "Loli", "Shota", "Incest", "Sexual Violence"):
            self.assertEqual(canonical_tag(name), name)
            self.assertFalse(is_known(name), f"{name} 不应出现在词表内")

    def test_idempotent_and_boundaries(self):
        for name in ("Comedy", "搞笑", "Web Comic", "Loli", "ゆり", "Sci-Fi"):
            once = canonical_tag(name)
            self.assertEqual(canonical_tag(once), once, f"{name} 归一化不幂等")
        self.assertEqual(canonical_tag(""), "")
        self.assertEqual(canonical_tag("   "), "")
        self.assertEqual(canonical_tag(None), "")  # type: ignore[arg-type]

    def test_synonym_table_self_consistent(self):
        """词表自检：规范名不得被别的组当别名；一个别名只能指向一个规范名。"""
        raw = json.loads(SYNONYMS_PATH.read_text(encoding="utf-8"))
        owner: dict[str, str] = {}
        for canonical, aliases in raw.items():
            self.assertTrue(canonical.strip(), "存在空的规范名")
            self.assertEqual(canonical_tag(canonical), canonical, f"{canonical} 未映射到自身")
            for name in (canonical, *(aliases or [])):
                key = normalize_tag(name)
                self.assertNotIn(
                    key, ("",),
                    f"{canonical} 的别名 {name!r} 归一化后为空",
                )
                prev = owner.setdefault(key, canonical)
                if prev != canonical:
                    # 一组的主名若恰好是另一组的别名，也会走到这里 —— 直接报出来
                    self.assertEqual(
                        prev, canonical,
                        f"写法 {name!r} 同时指向 {prev!r} 与 {canonical!r}",
                    )

    def test_sync_tags_applies_canonicalization(self):
        """写入路径：落库前把各源写法换成规范名，且同一作品的重复概念只写一次。"""
        cur = _FakeCursor()
        MySQLStorage._sync_tags(cur, 7, ["Comedy", "搞笑", "Web Comic"])
        inserted = [
            args[0] for sql, args in cur.calls if sql.startswith("INSERT IGNORE INTO tag")
        ]
        # Comedy 与 搞笑 合并为「喜剧」（只插一次）；未映射的原样保留
        self.assertEqual(inserted, ["喜剧", "Web Comic"])
        linked = [args for sql, args in cur.calls if sql.startswith("INSERT IGNORE INTO comic_tag")]
        self.assertEqual(len(linked), 2)   # 两条关联（喜剧 / Web Comic）

    def test_sync_tags_skips_symbols_and_empties(self):
        """防御仍在：空串与纯符号片段不入库（避免孤儿标签）。"""
        cur = _FakeCursor()
        MySQLStorage._sync_tags(cur, 8, ["", "  ", "/", "·", "Comedy"])
        inserted = [
            args[0] for sql, args in cur.calls if sql.startswith("INSERT IGNORE INTO tag")
        ]
        self.assertEqual(inserted, ["喜剧"])


if __name__ == "__main__":
    unittest.main()
