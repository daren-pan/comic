"""任务状态的持久化：SQLite 单表。

为什么不用内存：任务要跨重启存活（改代码可能几分钟，服务重启一次就全丢不可接受），
而且「进度 A7F3」是异步查询，必须能查到历史任务。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    action        TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    status        TEXT NOT NULL,
    allowed_paths TEXT NOT NULL DEFAULT '[]',
    branch        TEXT NOT NULL DEFAULT '',
    mode          TEXT NOT NULL DEFAULT 'code',
    answer        TEXT NOT NULL DEFAULT '',
    worktree      TEXT NOT NULL DEFAULT '',
    files         TEXT NOT NULL DEFAULT '[]',
    diff_stat     TEXT NOT NULL DEFAULT '',
    diff_text     TEXT NOT NULL DEFAULT '',
    log_tail      TEXT NOT NULL DEFAULT '',
    commit_hash   TEXT NOT NULL DEFAULT '',
    commit_msg    TEXT NOT NULL DEFAULT '',
    push_ok       INTEGER NOT NULL DEFAULT 1,
    push_error    TEXT NOT NULL DEFAULT '',
    error         TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""

#: 状态机：queued → running → awaiting_review → applying → applied
#:                                    ↘ discarded        ↘ failed
TERMINAL = {"applied", "discarded", "failed"}


class TaskStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """老库补列：SQLite 没有 IF NOT EXISTS 加列，先看表结构再决定。"""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(tasks)")}
        if "branch" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN branch TEXT NOT NULL DEFAULT ''")
        if "mode" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN mode TEXT NOT NULL DEFAULT 'code'")
        if "answer" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN answer TEXT NOT NULL DEFAULT ''")
        if "push_ok" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN push_ok INTEGER NOT NULL DEFAULT 1")
        if "push_error" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN push_error TEXT NOT NULL DEFAULT ''")

    # ---- 写 ----

    def create(
        self, action: str, prompt: str, allowed_paths: list[str], mode: str = "code"
    ) -> dict[str, Any]:
        task_id = uuid.uuid4().hex[:8].upper()
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO tasks (id, action, prompt, status, allowed_paths, mode, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (task_id, action, prompt, "queued", json.dumps(allowed_paths), mode, now, now),
            )
            self._conn.commit()
        return self.get(task_id)  # type: ignore[return-value]

    def update(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "files" in fields and not isinstance(fields["files"], str):
            fields["files"] = json.dumps(fields["files"], ensure_ascii=False)
        if "allowed_paths" in fields and not isinstance(fields["allowed_paths"], str):
            fields["allowed_paths"] = json.dumps(fields["allowed_paths"], ensure_ascii=False)
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE tasks SET {cols} WHERE id = ?", (*fields.values(), task_id))
            self._conn.commit()

    # ---- 读 ----

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def mark_interrupted(self) -> int:
        """进程启动时把上一次残留的 running/applying 标成失败（进程已死，任务不可能还在跑）。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status = 'failed', error = '服务重启，任务被中断', updated_at = ?"
                " WHERE status IN ('running', 'applying')",
                (time.time(),),
            )
            self._conn.commit()
            return cur.rowcount

    def next_queued(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
        return _row_to_dict(row) if row else None

    def latest(self, status: str) -> dict[str, Any] | None:
        """取某状态下最新的一条（用于「应用」「进度」不带任务号时）。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT 1", (status,)
            ).fetchone()
        return _row_to_dict(row) if row else None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("files", "allowed_paths"):
        try:
            d[key] = json.loads(d.get(key) or "[]")
        except json.JSONDecodeError:
            d[key] = []
    # diff 全文单独给，列表接口里用截断版即可
    d["diff_text_truncated"] = (d.get("diff_text") or "")[:4000]
    return d
