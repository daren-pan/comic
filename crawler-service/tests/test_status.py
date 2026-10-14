"""`comic_core.status` 归一：各源写法 → 规范值。

对应 2026-10-13 的修复。此前四个源适配器**各写一套**状态映射、输出用词互不相同：

| 源 | 输出 |
|---|---|
| `weebcentral` / `mangadex` | 连载 / 完结 / 休载 / 已取消 |
| `copymanga` | 连载 / 完结 |
| `zaimanhua` | 透传源站文本（连载中） |
| `ComicBrief` 默认值 | 连载 |

于是库内并存三种写法（实测 `连载` 29 / `连载中` 23 / `完结` 2），
而 `api-service` 的接口层还用白名单静默兜底、只认「连载中/已完结」——
**那 2 部已完结的作品被强制显示成了"连载中"**。

（本模块住在 `comic_core`，但测试放这里 —— 与 `test_taxonomy.py` 同一惯例：
comic_core 没有自己的 tests 目录。）

运行：PYTHONPATH=src;../comic-core/src python -m unittest discover -s tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_core.status import (  # noqa: E402
    ALL_STATUSES,
    STATUS_CANCELLED,
    STATUS_FINISHED,
    STATUS_HIATUS,
    STATUS_ONGOING,
    is_known_status,
    normalize_status,
)


class TestNormalizeStatus(unittest.TestCase):
    def test_ongoing_aliases(self):
        for raw in ("连载", "連載", "连载中", "連載中", "Ongoing", "ongoing", " 连载 "):
            self.assertEqual(normalize_status(raw), STATUS_ONGOING, raw)

    def test_finished_aliases(self):
        for raw in ("完结", "完結", "已完结", "已完結", "Completed", "complete"):
            self.assertEqual(normalize_status(raw), STATUS_FINISHED, raw)

    def test_hiatus_and_cancelled_are_not_merged(self):
        """`休载` / `已取消` 有各自的真实语义，**不得**被压进「连载中/已完结」。

        这是刻意与旧白名单划清界限：那个兜底把任何不认识的写法都改成"连载中"，
        包括本该显示"已完结"的作品。
        """
        self.assertEqual(normalize_status("hiatus"), STATUS_HIATUS)
        self.assertEqual(normalize_status("休載"), STATUS_HIATUS)
        self.assertEqual(normalize_status("已取消"), STATUS_CANCELLED)
        self.assertEqual(normalize_status("Cancelled"), STATUS_CANCELLED)

    def test_blank_becomes_ongoing(self):
        """拿不到状态 = 当作在连载（与 `ComicBrief.status` 的默认语义一致）。"""
        for raw in (None, "", "   "):
            self.assertEqual(normalize_status(raw), STATUS_ONGOING)

    def test_unknown_is_kept_verbatim(self):
        """未命中**保留原文**（不吞、不猜）—— 新增源应显式登记到 `_ALIASES`。"""
        self.assertEqual(normalize_status("连载再开"), "连载再开")
        self.assertEqual(normalize_status("unknown-status"), "unknown-status")

    def test_idempotent(self):
        """归一后的值再归一次不变（接口层与入库路径都会调用它）。"""
        for status in ALL_STATUSES:
            self.assertEqual(normalize_status(status), status)

    def test_is_known_status(self):
        self.assertTrue(is_known_status("连载中"))
        self.assertTrue(is_known_status("休载"))
        self.assertFalse(is_known_status("连载"))       # 历史写法，尚未归一
        self.assertFalse(is_known_status(None))


class TestAdaptersUseSharedNormalizer(unittest.TestCase):
    """四个源都改调同一个函数 —— 用真实适配器验证，防止有人再就地写一份映射表。"""

    def _adapter(self, name: str):
        from comic_crawler.sources.registry import create_adapter

        return create_adapter(name, http=object())

    def test_sources_no_longer_have_their_own_status_map(self):
        import comic_crawler.sources.mangadex.adapter as mg
        import comic_crawler.sources.weebcentral.adapter as wc

        self.assertFalse(hasattr(wc, "STATUS_MAP"), "weebcentral 不该再有私有状态映射表")
        self.assertFalse(
            hasattr(mg.MangaDexAdapter, "_STATUS_MAP"), "mangadex 不该再有私有状态映射表"
        )

    def test_mangadex_maps_to_canonical_values(self):
        self.assertEqual(self._adapter("mangadex")._status_text("ongoing"), STATUS_ONGOING)
        self.assertEqual(self._adapter("mangadex")._status_text("completed"), STATUS_FINISHED)
        self.assertEqual(self._adapter("mangadex")._status_text(None), "")   # 拿不到 → 空串（调用方兜底）

    def test_copymanga_maps_to_canonical_values(self):
        ad = self._adapter("copymanga")
        self.assertEqual(ad._status_of({"status": {"display": "已完結"}}), STATUS_FINISHED)
        self.assertEqual(ad._status_of({"status": {"display": "連載中"}}), STATUS_ONGOING)
        self.assertEqual(ad._status_of({}), "")                             # 拿不到 → 空串


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
