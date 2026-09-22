"""读时穿透取图的**闸门 / 去重 / 负缓存**（`images/transfer.fetch_page_bytes`）。

纯逻辑测试：内存 Fake 存储/图库/下载器，不连数据库、不发网络、不写文件。

为什么单独守这三条（2026-09-21 补）：批量转存一直有 `CONCURRENCY` 闸门，而**读时穿透没有** ——
阅读器一话就是浏览器并发 N 张图，冷章节等于 N 个出站请求同时打源站，而触发者可以只是
一个匿名用户（`GET /api/images/...` 公开无鉴权）。三条断言分别卡住：

1. 同图并发**只下载一次**（多标签页 / 快速重试不该翻倍打源站）；
2. 失败后短时间内**不再打源站**（否则"刷新一次打一次"，可以无限重试）；
3. 闸门排满时**排队超时即放弃**，且**不写负缓存**（拥挤不等于这一页坏了）。

运行：python -m unittest discover -s tests（需 PYTHONPATH=src）
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from comic_crawler.images import transfer  # noqa: E402
from comic_crawler.images.transfer import build_image_key, fetch_page_bytes  # noqa: E402


def _row(**over) -> dict:
    base = {
        "page_id": 1,
        "page_no": 1,
        # 非空且无 `t=` 参数 → `_download_one` 会直接走 downloader（不判过期、不重拉）
        "source_url": "http://img.test/1.jpg",
        "oss_url": "",
        "cached_status": "未转存",
        "comic_id": 10,
        "chapter_id": 20,
        "source_chapter_id": "200",
        "source": "fake",
        "source_comic_id": "100",
    }
    base.update(over)
    return base


class FakeStorage:
    def __init__(self) -> None:
        self.cached: list[tuple[int, str]] = []

    def mark_page_cached(self, page_id: int, oss_url: str) -> None:
        self.cached.append((page_id, oss_url))


class FakeImageStore:
    """内存图库：key 就是 `comic/<cid>/<chid>/<pno>.jpg`。"""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> str:
        self.files[key] = data
        return f"file:///{key}"

    def get(self, key: str) -> bytes | None:
        return self.files.get(key)

    def exists(self, key: str) -> bool:
        return key in self.files

    def delete(self, key: str) -> None:
        self.files.pop(key, None)


class TestPassthrough(unittest.TestCase):
    def setUp(self) -> None:
        # 模块级状态是**跨用例共享**的（负缓存 / 同图登记），每个用例都要清干净
        transfer._fail_until.clear()
        transfer._inflight.clear()
        self.storage = FakeStorage()
        self.store = FakeImageStore()

    def _fetch(self, downloader, row=None):
        return fetch_page_bytes(self.storage, self.store, row or _row(), downloader=downloader)

    # ---------------- 成功路径 ----------------

    def test_success_writes_store_and_backfills(self):
        """成功：落盘 + 回填 `cached_status`，并把字节返回给本次阅读。"""
        data = self._fetch(lambda url, key: b"IMG")
        self.assertEqual(data, b"IMG")
        key = build_image_key(10, 20, 1)
        self.assertEqual(self.store.files[key], b"IMG")
        self.assertEqual(self.storage.cached, [(1, key)])

    # ---------------- 负缓存 ----------------

    def test_failure_is_negatively_cached(self):
        """失败后在 TTL 内**不再打源站**（此前是"用户每刷新一次就重试一次"）。"""
        calls: list[str] = []

        def boom(url, key):
            calls.append(key)
            raise OSError("connection refused")

        self.assertIsNone(self._fetch(boom))
        self.assertIsNone(self._fetch(boom))
        self.assertIsNone(self._fetch(boom))

        self.assertEqual(len(calls), 1, "TTL 内应只打源站一次")
        self.assertEqual(self.storage.cached, [])

    def test_negative_cache_expires(self):
        """TTL 一过就允许重试（坏页不能永久黑掉）。"""
        calls: list[str] = []

        def boom(url, key):
            calls.append(key)
            raise OSError("boom")

        self.assertIsNone(self._fetch(boom))
        # 把到期时刻拨到过去 = 模拟"已经过了 TTL"
        for k in list(transfer._fail_until):
            transfer._fail_until[k] = time.monotonic() - 1
        self.assertIsNone(self._fetch(boom))
        self.assertEqual(len(calls), 2)

    # ---------------- 同图去重 ----------------

    def test_concurrent_same_page_downloads_once(self):
        """同一页被并发请求 → 只下载一次，两个调用方都拿到字节。"""
        calls: list[str] = []
        entered = threading.Event()

        def slow(url, key):
            calls.append(key)
            entered.set()
            time.sleep(0.2)          # 拉长窗口，保证第二个线程一定落在"下载中"
            return b"IMG"

        results: list[bytes | None] = []
        worker = lambda: results.append(self._fetch(slow))  # noqa: E731

        first = threading.Thread(target=worker)
        first.start()
        self.assertTrue(entered.wait(3), "领先者没能进入下载")
        second = threading.Thread(target=worker)
        second.start()
        first.join(5)
        second.join(5)

        self.assertEqual(len(calls), 1, "并发同一页只应下载一次")
        self.assertEqual(results, [b"IMG", b"IMG"])

    # ---------------- 闸门 ----------------

    def test_gate_timeout_gives_up_without_poisoning_cache(self):
        """闸门满 → 排队超时后放弃（返回 None = 前端给占位图），且**不写负缓存**。

        拥挤是**临时的过载**，不是"这一页坏了" —— 若写进负缓存，等于把一批好页黑掉一分钟。
        """
        calls: list[str] = []
        holder = threading.Semaphore(1)
        holder.acquire()             # 占住唯一额度，模拟并发已满

        with patch.object(transfer, "_passthrough_gate", holder), patch.object(
            transfer, "PASSTHROUGH_WAIT_SECONDS", 0.2
        ):
            self.assertIsNone(self._fetch(lambda url, key: (calls.append(key), b"IMG")[1]))
            self.assertEqual(calls, [], "闸门满时不该发起下载")
            self.assertEqual(transfer._fail_until, {}, "闸门超时不应写负缓存")

        # 额度释放后同一页应能正常取到（证明上一步没把它黑掉）
        holder.release()
        self.assertEqual(self._fetch(lambda url, key: b"IMG"), b"IMG")

    def test_different_pages_are_not_deduplicated(self):
        """去重只按"同一页"生效 —— 不同页必须各自下载，不能被误合并。"""
        calls: list[str] = []

        def dl(url, key):
            calls.append(key)
            return b"IMG"

        self._fetch(dl, _row(page_id=1, page_no=1))
        self._fetch(dl, _row(page_id=2, page_no=2))
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
