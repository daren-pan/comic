"""内部消息知识接口（`services.messages.knowledge_feed`）单测。"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from fastapi import HTTPException  # noqa: E402

from core.security import require_service  # noqa: E402
from services import messages  # noqa: E402


class _FakeStore:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def list_all(self, *, after_id=0, limit=200):
        self.calls.append((after_id, limit))
        return [r for r in self.rows if r["id"] > after_id][:limit]


def _row(mid: int, **overrides) -> dict:
    row = {
        "id": mid,
        "kind": "sync",
        "level": "info",
        "title": f"消息 {mid}",
        "body": f"正文 {mid}",
        "params": '{"source": "zaimanhua"}',
        "task_id": f"task-{mid}",
        "source": "zaimanhua",
        "user_id": 7,
        "username": "alice",
        "to_user_id": None,
        "min_role": "admin",
        "created_at": datetime(2026, 11, 3, 12, 0, 0),
    }
    row.update(overrides)
    return row


class KnowledgeFeedTest(unittest.TestCase):
    def test_cursor_pagination_and_contract(self) -> None:
        fake = _FakeStore([_row(1), _row(2), _row(3)])
        with patch.object(messages, "_store", lambda: fake):
            page = messages.knowledge_feed(cursor=0, limit=2)
        self.assertEqual(page["nextCursor"], 2)
        self.assertTrue(page["hasMore"])
        self.assertEqual(page["schemaVersion"], 1)
        self.assertEqual([item["id"] for item in page["items"]], [1, 2])
        self.assertEqual(page["items"][0]["createdAt"], "2026-11-03T12:00:00")
        self.assertEqual(page["items"][0]["updatedAt"], "2026-11-03T12:00:00")
        self.assertEqual(page["items"][0]["params"], {"source": "zaimanhua"})
        self.assertFalse(page["items"][0]["deleted"])

        with patch.object(messages, "_store", lambda: fake):
            page2 = messages.knowledge_feed(cursor=2, limit=2)
        self.assertEqual([item["id"] for item in page2["items"]], [3])
        self.assertFalse(page2["hasMore"])
        self.assertEqual(page2["nextCursor"], 3)

    def test_empty_page_keeps_cursor(self) -> None:
        fake = _FakeStore([])
        with patch.object(messages, "_store", lambda: fake):
            page = messages.knowledge_feed(cursor=42, limit=10)
        self.assertEqual(page["items"], [])
        self.assertEqual(page["nextCursor"], 42)
        self.assertFalse(page["hasMore"])


class ServiceAuthTest(unittest.TestCase):
    def test_service_token(self) -> None:
        from comic_core.notify import make_service_token

        token = make_service_token("comic-demo-secret-change-me")
        self.assertEqual(require_service(service_token=token)["auth"], "service")

    def test_missing_or_invalid_token(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            require_service(service_token=None)
        self.assertEqual(ctx.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            require_service(service_token="bad.token")


if __name__ == "__main__":
    unittest.main()
