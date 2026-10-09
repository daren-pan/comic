"""收藏更新通知（`comic_core/fanout.py`）—— 组装与分发，**纯逻辑、不联网、不连库**。

两个采集触发方（api 手动采集 / `comic-scheduler` 定时轮次）共用这一份分发逻辑，
所以这里钉住三件事：

1. **组装**：每（更新作品 × 收藏者）一条、文案形状固定（`《X》更新了` + `新增 N 话`）；
2. **投递**：一条失败不影响其他条（网络抖动不该吞掉整批通知）；
3. **失败语义**：查库失败 / 投递全败都**不抛异常**（消息是可观测性，不该拖累采集）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comic_core.fanout import build_payloads, notify_favorite_updates  # noqa: E402


def _up(comic_id=44, title="标题，有用吗？", source="zaimanhua", n=2, titles=("第28话", "第29话")):
    return {"comic_id": comic_id, "title": title, "source": source,
            "new_chapters": n, "titles": list(titles)}


class _FakeStore:
    """假收藏者查询：记录调用（断言"一次批量查"），返回给定映射。"""

    def __init__(self, fans: dict) -> None:
        self.fans = fans
        self.calls: list[list[int]] = []

    def list_favoriters(self, comic_ids):
        self.calls.append(list(comic_ids))
        return self.fans


class TestBuildPayloads(unittest.TestCase):
    """每（更新作品 × 收藏者）一条；文案形状固定；脏数据跳过。"""

    def test_one_message_per_fan(self):
        ps = build_payloads([_up()], {44: [4, 10]})
        self.assertEqual(len(ps), 2)
        self.assertEqual({p["toUserId"] for p in ps}, {4, 10})

    def test_payload_shape(self):
        p = build_payloads([_up()], {44: [10]})[0]
        self.assertEqual(p["kind"], "update")
        self.assertEqual(p["level"], "info")
        self.assertEqual(p["title"], "《标题，有用吗？》更新了")
        self.assertEqual(p["body"], "新增 2 话：第28话、第29话")
        self.assertEqual(p["params"], {"comicId": 44, "newChapters": 2, "source": "zaimanhua"})
        self.assertEqual(p["minRole"], "", "定向靠 toUserId，min_role 不设门槛")

    def test_no_fans_no_payload(self):
        self.assertEqual(build_payloads([_up()], {}), [])

    def test_over_max_titles_uses_ellipsis(self):
        p = build_payloads([_up(n=5, titles=["a", "b", "c", "d", "e"])], {44: [1]})[0]
        self.assertEqual(p["body"], "新增 5 话：a、b、c…")

    def test_dirty_comic_id_is_skipped(self):
        ps = build_payloads([{"comic_id": None}, {"comic_id": "abc"}, _up()], {44: [4]})
        self.assertEqual(len(ps), 1, "认不出 comic_id 的明细直接跳过，不让一条脏数据中断整批")

    def test_blank_title_falls_back_to_id(self):
        p = build_payloads([{"comic_id": 7, "title": "  "}], {7: [1]})[0]
        self.assertEqual(p["title"], "《作品 7》更新了")


class TestNotifyFavoriteUpdates(unittest.TestCase):
    """分发编排：批量查、逐条投、失败不抛。"""

    def test_empty_updates_short_circuits(self):
        sent: list = []
        self.assertEqual(notify_favorite_updates([], publish=sent.append, store=_FakeStore({})), 0)
        self.assertEqual(notify_favorite_updates(None, publish=sent.append, store=_FakeStore({})), 0)
        self.assertEqual(sent, [], "没有更新就不该查库、更不该发消息")

    def test_sends_and_counts(self):
        sent: list = []
        store = _FakeStore({44: [4, 10]})
        n = notify_favorite_updates([_up()], publish=sent.append, store=store)
        self.assertEqual(n, 2)
        self.assertEqual(len(sent), 2)
        self.assertEqual(store.calls, [[44]], "收藏者必须一次批量查（不是每部作品查一次）")

    def test_store_failure_is_swallowed(self):
        class _Boom:
            def list_favoriters(self, comic_ids):
                raise RuntimeError("db down")

        self.assertEqual(
            notify_favorite_updates([_up()], publish=lambda p: None, store=_Boom()), 0,
            "查库失败只记日志、返回 0，不抛给采集方",
        )

    def test_publish_failure_does_not_stop_others(self):
        sent: list = []

        def flaky(payload):
            if payload["toUserId"] == 4:
                raise RuntimeError("http 500")
            sent.append(payload)

        n = notify_favorite_updates([_up()], publish=flaky, store=_FakeStore({44: [4, 10]}))
        self.assertEqual(n, 1, "一条投递失败不影响后面的")
        self.assertEqual([p["toUserId"] for p in sent], [10])


if __name__ == "__main__":
    unittest.main()
