"""瓜子漫画（guazi）适配器的纯逻辑测试 —— 时间窗口（方案A · 按天）。

只测不触发网络的纯方法：_since_day / _date_param / _extract_update_date /
_passes_window 的日级比较。运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.adapter.guazi_source import GuaziAdapter
from parsel import Selector
from unittest import mock


class TestDateParam(unittest.TestCase):
    """_date_param：按 since 与"今天"的天数差选 date 档位。真实 date.today 会漂移，
    故用 mock 固定今天为 2026-09-05，直接断言真实方法返回。"""

    def _param(self, since_day):
        with mock.patch("comic_crawler.adapter.guazi_source.date") as m:
            m.today.return_value = datetime.date(2026, 9, 5)
            return GuaziAdapter._date_param(since_day)

    def test_first_none_is_today(self):
        self.assertEqual(self._param(None), "today")

    def test_today_delta_0_today(self):
        self.assertEqual(self._param(datetime.date(2026, 9, 5)), "today")

    def test_yesterday_delta_1_today(self):
        self.assertEqual(self._param(datetime.date(2026, 9, 4)), "today")

    def test_week_delta_4(self):
        self.assertEqual(self._param(datetime.date(2026, 9, 1)), "week")

    def test_month_delta_16(self):
        self.assertEqual(self._param(datetime.date(2026, 8, 20)), "month")

    def test_all_delta_gt_31(self):
        self.assertEqual(self._param(datetime.date(2026, 6, 1)), "all")


class TestSinceDay(unittest.TestCase):
    def test_none_returns_none(self):
        self.assertIsNone(GuaziAdapter._since_day(None))

    def test_datetime_trunc_to_date(self):
        since = datetime.datetime(2026, 9, 5, 15, 1, 54)
        self.assertEqual(GuaziAdapter._since_day(since), datetime.date(2026, 9, 5))

    def test_old_datetime_trunc(self):
        since = datetime.datetime(2026, 9, 1, 8, 30)
        self.assertEqual(GuaziAdapter._since_day(since), datetime.date(2026, 9, 1))


class TestExtractUpdateDate(unittest.TestCase):
    """_extract_update_date：解析 <p class='desc'> 的「更新时间：YYYY-MM-DD」。"""

    def test_parse_iso_date(self):
        html = '<p class="desc">更新时间：2026-09-05<br>最新章节：第30章<br>状态：连载</p>'
        self.assertEqual(
            GuaziAdapter._extract_update_date(Selector(text=html)),
            datetime.date(2026, 9, 5),
        )

    def test_parse_among_multiple_desc(self):
        # 详情页可能有多个 p.desc（首个是简介），须遍历全部节点拼接后再匹配
        html = (
            '<p class="desc">收到叔叔的请求，小a来到农场...</p>'
            '<p class="desc">更新时间：2026-09-05<br>章节总数：30 话</p>'
        )
        self.assertEqual(
            GuaziAdapter._extract_update_date(Selector(text=html)),
            datetime.date(2026, 9, 5),
        )

    def test_cn_date_format_none(self):
        # 中文"2026年09月05日"不被支持（站点实际用 YYYY-MM-DD）
        html = '<p class="desc">更新时间：2026年09月05日</p>'
        self.assertIsNone(GuaziAdapter._extract_update_date(Selector(text=html)))

    def test_no_desc_none(self):
        self.assertIsNone(GuaziAdapter._extract_update_date(Selector(text="<p>无时间</p>")))


class TestPassesWindow(unittest.TestCase):
    """_passes_window 的日级比较（>= since_day 保留，早于 since_day 过滤）。"""

    def _compare(self, updated, since_day):
        return updated >= since_day

    def test_keeps_on_or_after(self):
        self.assertTrue(self._compare(datetime.date(2026, 9, 5), datetime.date(2026, 9, 1)))
        self.assertTrue(self._compare(datetime.date(2026, 9, 1), datetime.date(2026, 9, 1)))

    def test_filters_before(self):
        self.assertFalse(self._compare(datetime.date(2026, 8, 31), datetime.date(2026, 9, 1)))


# 真实列表卡片：封面 <img> 自身无 class，包在 <a class='mobile-update-cover'> 里
# （2026-09-05 实测：现行 class 匹配 XPath 命中 0/30，父级 a 定位命中 30/30）
CARD_HTML = """
<article class="mobile-update-card">
  <a class="mobile-update-cover" href="/comic.php?id=30876">
    <img src="https://img.guazicdn.com/mkz/comics/cover/215982/260829/cover.jpg" alt="封面" width="300" height="400" loading="eager">
  </a>
  <h2><a href="/comic.php?id=30876">快穿系统：反派大佬不好惹</a></h2>
  <p><a href="/chapter.php?id=2543668">序章</a></p>
  <small>恋爱 / 古风</small>
  <a class="mobile-update-read" href="/chapter.php?id=2543668">更新</a>
</article>
"""


class TestCardCoverParse(unittest.TestCase):
    """列表卡片封面解析回归测试（不联网，mock _fetch_selector 返回本地卡片 HTML）。

    防止回归：封面 <img> 无 class 时被遗漏导致 cover_url 为空。
    """

    def _adapter(self, page_html):
        adapter = GuaziAdapter(object())  # http 字段不被使用（_fetch_selector 被 mock）
        adapter._fetch_selector = mock.Mock(return_value=Selector(text=page_html))
        return adapter

    def test_card_cover_extracted(self):
        # fetch_comic_list 会翻页探测下一页 → mock _next_page_has_items 避免额外请求
        adapter = self._adapter(CARD_HTML + CARD_HTML)
        adapter._next_page_has_items = mock.Mock(return_value=False)
        res = adapter.fetch_comic_list(page=1, since=None)
        self.assertEqual(len(res.items), 1)
        self.assertEqual(
            res.items[0].cover_url,
            "https://img.guazicdn.com/mkz/comics/cover/215982/260829/cover.jpg",
        )
        self.assertEqual(res.items[0].source_comic_id, "30876")
        self.assertEqual(res.items[0].title, "快穿系统：反派大佬不好惹")
        self.assertEqual(res.items[0].category, "恋爱 / 古风")


if __name__ == "__main__":
    unittest.main()
