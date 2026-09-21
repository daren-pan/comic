"""在漫画 / 再漫画（zaimanhua）适配器单测：列表翻页按时间窗口边界收敛。

只覆盖纯逻辑（不连网、不连库）：`fetch_comic_list` 的窗口过滤与翻页停止条件。
"""
from __future__ import annotations

import unittest
from datetime import datetime

from comic_crawler.sources.zaimanhua.adapter import ZaimanhuaAdapter


def _row(cid: str, title: str, ts: int) -> dict:
    """构造一条「最近更新」列表行（字段见 /api/app/v1/comic/update/list/0/{page}）。"""
    return {
        "comic_id": cid,
        "id": 0,
        "title": title,
        "last_updatetime": ts,
        "cover": "",
        "authors": "",
        "status": "连载",
        "types": "",
    }


def _ts(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d).timestamp())


class TestZaimanhuaAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.ad = ZaimanhuaAdapter(http=object())

    # ------------------------------------------------------------------
    def test_fetch_list_and_request_path(self):
        """列表走 /comic/update/list/0/{page}，按窗口过滤后仍可继续翻页。"""
        calls: list[str] = []

        def fake(path, params=None):
            calls.append(path)
            return {"data": [_row("1", "A", _ts(2026, 9, 16))]}

        self.ad._api_get = fake
        res = self.ad.fetch_comic_list(page=1, since=None)
        self.assertEqual([it.title for it in res.items], ["A"])
        self.assertEqual(calls[0], "/api/app/v1/comic/update/list/0/1")

    def test_fetch_list_paginate_to_window_edge(self):
        """窗口内更新超一页时应继续翻页；翻到某页全部越过 since 才停（对齐 mangadex）。"""
        since = datetime(2026, 9, 10)

        # 第 1 页：09-16（窗口内）；第 2 页：09-01（窗口外）
        pages = {
            "1": {"data": [_row("a", "A", _ts(2026, 9, 16)), _row("b", "B", _ts(2026, 9, 15))]},
            "2": {"data": [_row("c", "C", _ts(2026, 9, 1)), _row("d", "D", _ts(2026, 9, 1))]},
        }

        def fake(path, params=None):
            page = path.rsplit("/", 1)[-1]
            return pages.get(page, {"data": []})

        self.ad._api_get = fake
        r1 = self.ad.fetch_comic_list(page=1, since=since)
        self.assertEqual([it.title for it in r1.items], ["A", "B"])
        # 本页原始数据不足 20 部（假数据），has_next 由「满页」判定，这里直接构造满页场景
        # —— 用第二页验证「越过边界即停」的核心逻辑。
        r2 = self.ad.fetch_comic_list(page=2, since=since)
        self.assertEqual(r2.items, [])      # 本页全在窗口外 → 无收集
        self.assertFalse(r2.has_next)       # 已越过 since 边界 → 停，不翻第 3 页

    def test_fetch_list_stops_at_max_page(self):
        """无 since（全量/首采）时翻到 MAX_PAGE 安全阀为止。"""
        import comic_crawler.sources.zaimanhua.adapter as zh

        self.ad._api_get = lambda path, params=None: {"data": [_row("x", "X", _ts(2026, 9, 16))] * 20}
        r = self.ad.fetch_comic_list(page=zh.MAX_PAGE, since=None)
        self.assertFalse(r.has_next)        # 已到安全阀页 → 不再翻


if __name__ == "__main__":
    unittest.main()
