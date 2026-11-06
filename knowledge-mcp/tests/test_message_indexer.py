"""message 索引器的纯逻辑单测（不连 API / Chroma）。"""
from __future__ import annotations

import unittest

from comic_rag_mcp.message_indexer import item_to_document


class MessageDocumentTest(unittest.TestCase):
    def test_doc_id_and_metadata(self) -> None:
        doc = item_to_document({
            "id": 42,
            "kind": "sync",
            "level": "error",
            "title": "采集失败",
            "body": "zaimanhua 超时",
            "taskId": "task-42",
            "source": "zaimanhua",
            "username": "alice",
            "minRole": "admin",
            "toUserId": None,
            "createdAt": "2026-11-03T12:00:00",
        })
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc["id"], "message:42")
        self.assertIn("采集失败", doc["text"])
        self.assertIn("zaimanhua 超时", doc["text"])
        self.assertEqual(doc["metadata"]["source"], "message")
        self.assertEqual(doc["metadata"]["level"], "error")
        self.assertEqual(doc["metadata"]["targeted"], 0)
        self.assertEqual(doc["metadata"]["read_mode"], "chunk")

    def test_empty_message_is_skipped(self) -> None:
        self.assertIsNone(item_to_document({"id": 1, "title": "", "body": ""}))

    def test_bad_id_is_skipped(self) -> None:
        self.assertIsNone(item_to_document({"id": "not-int", "title": "x"}))


if __name__ == "__main__":
    unittest.main()
