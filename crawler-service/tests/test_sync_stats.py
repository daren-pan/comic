"""同步统计口径 + `sync_time` 刷新时机（2026-10-07 改）。

两条口径一起改的，所以放同一个文件里钉住：

1. **`updated_comics` = 本次真有新章节的已有作品数** —— 扫到但没新章节**不计**，
   于是"同一时间窗内第二次触发"自然是 `更新 0`（此前是"命中已有行就 +1"，
   所以 155 部扫出「新增 41 / 更新 114」，看着像有 114 部变了，其实什么都没变）。
2. **`comic.sync_time` = 内容最近变化的时刻**（最近更新页角标 / `sort=updated` 取它）：
   新收录、元数据变化、来了新章节 → 刷新；**扫到但没变化 → 不刷**。

运行：python -m unittest discover -s tests（离线可跑，不连库）
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_core.models import (  # noqa: E402
    ChapterBrief,
    ComicBrief,
    ComicDetail,
    ComicListResult,
)
from comic_core.storage.mysql.comic_store import _content_changed  # noqa: E402

from comic_crawler.scheduling.sync import incremental_sync  # noqa: E402


def _detail(
    *, title="作品", author="作者", status="连载", category="热血", description="简介",
    latest_chapter_title="第 10 话", chapters=(),
) -> ComicDetail:
    return ComicDetail(
        source="fake", source_comic_id="c1", title=title, author=author,
        cover_url="https://img.example/c1.jpg", status=status, category=category,
        description=description, latest_chapter_title=latest_chapter_title,
        detail_url="",
        chapters=[ChapterBrief(source="fake", source_comic_id="c1", chapter_no=n,
                               title=f"第 {n} 话", source_chapter_id=f"ch{n}")
                  for n in chapters],
    )


class TestContentChanged(unittest.TestCase):
    """`_content_changed`：库里那一行 vs 本次抓到的详情。"""

    ROW = {
        "title": "作品", "author": "作者", "status": "连载", "category": "热血",
        "description": "简介", "latest_chapter_title": "第 10 话", "fingerprint": "fp",
    }

    def test_same_content_is_not_changed(self):
        self.assertFalse(_content_changed(self.ROW, _detail(), "fp"))

    def test_whitespace_only_is_not_changed(self):
        """源站偶尔多个空格，不该算内容变化（否则角标白刷）。"""
        self.assertFalse(_content_changed(self.ROW, _detail(title=" 作品 "), "fp"))

    def test_field_changes_are_detected(self):
        for kwargs in (
            {"title": "改名了"}, {"author": "换作者"}, {"status": "完结"},
            {"category": "冒险"}, {"description": "新简介"},
            {"latest_chapter_title": "第 11 话"},
        ):
            with self.subTest(**kwargs):
                self.assertTrue(_content_changed(self.ROW, _detail(**kwargs), "fp"))

    def test_fingerprint_change_is_detected(self):
        self.assertTrue(_content_changed(self.ROW, _detail(), "别的指纹"))

    def test_cover_url_is_ignored(self):
        """⚠️ 关键：库里存的是落盘后的**本地 key**，detail 给的是**源站外链** ——
        参与比较就会"每轮都算变化"、`sync_time` 每轮白刷（角标永远是"刚刚"）。
        """
        row = dict(self.ROW, cover_url="covers/1.jpg")
        detail = _detail()
        detail.cover_url = "https://img.example/1.jpg"
        self.assertFalse(_content_changed(row, detail, "fp"))


class _FakeAdapter:
    """最小适配器：一轮只返回一部作品，详情由外部给定（不联网）。"""

    source_name = "fake"

    def __init__(self, detail: ComicDetail) -> None:
        self._detail = detail

    def pre_fetch(self) -> None:
        pass

    def post_fetch(self) -> None:
        pass

    def fetch_comic_list(self, *, page=1, since=None):
        brief = ComicBrief(
            source=self._detail.source, source_comic_id=self._detail.source_comic_id,
            title=self._detail.title, author=self._detail.author,
        )
        return ComicListResult(items=[brief], page=page, has_next=False)

    def fetch_comic_detail(self, brief):
        return self._detail


class _FakeStorage:
    """内存存储：记录写入足迹，`upsert_comic` 的 `changed` 由用例给定。"""

    def __init__(self, *, is_new: bool, changed: bool, existing_chapters=(), new_chapters=()) -> None:
        self._is_new = is_new
        self._changed = changed
        self._existing = {n: {"chapter_no": n} for n in existing_chapters}
        self._new = list(new_chapters)
        self.touched: list[int] = []
        self.chapter_writes = 0

    # --- 采集流程用到的最小面 ---
    def upsert_comic(self, detail, fingerprint):
        return 7, self._is_new, self._changed

    def touch_comic_sync_time(self, comic_id, when=None) -> None:
        self.touched.append(comic_id)

    def get_chapters(self, comic_id):
        return list(self._existing.values())

    def upsert_chapters(self, comic_id, chapters):
        self.chapter_writes += 1
        out = []
        for ch in chapters:
            is_new = ch.chapter_no in self._new
            out.append((100 + ch.chapter_no, is_new))
        return out

    def set_comic_cover(self, comic_id, key) -> None:
        pass

    def get_last_sync_time(self, source):
        return None                     # 无水位：本轮按"首次"处理，不影响记账断言

    def log_sync(self, source, mode, stats) -> None:
        self.logged = (source, mode, stats)


class TestUpdatedCounting(unittest.TestCase):
    """记账口径：新增 = 首次收录；更新 = **本次真有新章节**。"""

    def _run(self, *, is_new, changed, existing=(), new=()):
        detail = _detail(chapters=sorted(set(existing) | set(new)))
        adapter = _FakeAdapter(detail)
        storage = _FakeStorage(
            is_new=is_new, changed=changed, existing_chapters=existing, new_chapters=new,
        )
        stats = incremental_sync(adapter, storage)
        return stats, storage

    def test_new_comic_counts_as_new_only(self):
        stats, _ = self._run(is_new=True, changed=True, new=(1, 2))
        self.assertEqual((stats.total_seen, stats.new_comics, stats.updated_comics), (1, 1, 0))
        self.assertEqual(stats.new_chapters, 2)

    def test_existing_comic_with_new_chapters_counts_as_updated(self):
        stats, storage = self._run(is_new=False, changed=False, existing=(1,), new=(2,))
        self.assertEqual((stats.new_comics, stats.updated_comics), (0, 1))
        self.assertEqual(stats.new_chapters, 1)
        # 元数据没变、但来了新章节 → 补刷 sync_time（否则角标停在旧时间）
        self.assertEqual(storage.touched, [7])

    def test_existing_comic_without_new_chapters_is_not_updated(self):
        """同一时间窗内第二次触发：没有新章节 → **更新 0**（本次改动的核心）。"""
        stats, storage = self._run(is_new=False, changed=False, existing=(1, 2), new=())
        self.assertEqual((stats.total_seen, stats.new_comics, stats.updated_comics), (1, 0, 0))
        self.assertEqual(stats.new_chapters, 0)
        self.assertEqual(storage.touched, [], "没变化就不该刷 sync_time")

    def test_metadata_change_refreshes_sync_time_via_upsert(self):
        """元数据变了：`upsert_comic` 内部已刷 sync_time → 这里不该重复 touch；
        但它**不算更新**（更新只看新章节）。"""
        stats, storage = self._run(is_new=False, changed=True, existing=(1, 2), new=())
        self.assertEqual(stats.updated_comics, 0)
        self.assertEqual(storage.touched, [])


class TestUpdatedDetail(unittest.TestCase):
    """`updated` 明细（供「通知收藏者」用，见 comic_core.fanout）—— 与 `updated_comics` 同口径同来源。"""

    def _run(self, *, is_new, changed, existing=(), new=()):
        detail = _detail(chapters=sorted(set(existing) | set(new)))
        stats = incremental_sync(_FakeAdapter(detail), _FakeStorage(
            is_new=is_new, changed=changed, existing_chapters=existing, new_chapters=new,
        ))
        return stats

    def test_detail_matches_counting(self):
        stats = self._run(is_new=False, changed=False, existing=(1,), new=(2, 3))
        self.assertEqual(stats.updated_comics, 1)
        self.assertEqual(len(stats.updated), 1)
        item = stats.updated[0]
        self.assertEqual(item["comic_id"], 7)
        self.assertEqual(item["source"], "fake")
        self.assertEqual(item["new_chapters"], 2)
        self.assertEqual(sorted(item["titles"]), ["第 2 话", "第 3 话"])

    def test_no_detail_when_nothing_new(self):
        stats = self._run(is_new=False, changed=False, existing=(1, 2), new=())
        self.assertEqual(stats.updated, [])

    def test_new_comic_has_no_detail(self):
        """首收不进明细：刚收录的作品没人收藏过它（通知收藏者时也无从可发）。"""
        stats = self._run(is_new=True, changed=True, new=(1, 2))
        self.assertEqual(stats.updated, [])


if __name__ == "__main__":
    unittest.main()
