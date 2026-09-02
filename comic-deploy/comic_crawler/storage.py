"""存储层：Storage 抽象 + SQLite 实现。

对应架构方案 §3.1：表结构与 MySQL 版保持一致
（comic / chapter / page / sync_log），演示用 SQLite 落库，
生产环境实现 SQLAlchemy/MySQL 版替换本模块即可，接口不变。

去重约定：
- comic.fingerprint UNIQUE          —— 跨站合并（标题指纹+作者）
- comic (source, source_comic_id) UNIQUE —— 站内唯一
- chapter (comic_id, chapter_no) UNIQUE —— 章节唯一
"""

from __future__ import annotations

import logging
import sqlite3
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from .models import ChapterBrief, ComicDetail, PageInfo

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    cover_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '连载',
    category TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    fingerprint TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_comic_id TEXT NOT NULL,
    latest_chapter_title TEXT NOT NULL DEFAULT '',
    sync_time TEXT NOT NULL,
    UNIQUE (source, source_comic_id)
);

CREATE TABLE IF NOT EXISTS chapter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comic_id INTEGER NOT NULL REFERENCES comic(id),
    chapter_no INTEGER NOT NULL,
    title TEXT NOT NULL,
    source_chapter_id TEXT NOT NULL,
    sync_time TEXT NOT NULL,
    UNIQUE (comic_id, chapter_no)
);

CREATE TABLE IF NOT EXISTS page (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER NOT NULL REFERENCES chapter(id),
    page_no INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    oss_url TEXT NOT NULL DEFAULT '',
    cached_status TEXT NOT NULL DEFAULT '未转存'
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    mode TEXT NOT NULL,
    total_seen INTEGER NOT NULL DEFAULT 0,
    new_comics INTEGER NOT NULL DEFAULT 0,
    updated_comics INTEGER NOT NULL DEFAULT 0,
    new_chapters INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
"""


class Storage(ABC):
    """存储抽象：采集层只依赖本接口，底层实现可替换。"""

    @abstractmethod
    def get_comic_id_by_fingerprint(self, fingerprint: str) -> int | None:
        """跨站指纹查作品 ID，None 表示新作品。"""

    @abstractmethod
    def upsert_comic(self, detail: ComicDetail, fingerprint: str) -> tuple[int, bool]:
        """写入/更新作品，返回 (comic_id, is_new)。"""

    @abstractmethod
    def upsert_chapter(self, comic_id: int, chapter: ChapterBrief) -> tuple[int, bool]:
        """写入/更新章节，返回 (chapter_id, is_new)。"""

    @abstractmethod
    def upsert_pages(self, chapter_id: int, pages: list[PageInfo]) -> int:
        """写入分页图片（按 chapter_id 先清后插），返回页数。"""

    @abstractmethod
    def log_sync(self, source: str, mode: str, stats) -> None:
        """记录同步日志（审计与版权存证，见架构方案 §6.2）。"""

    @abstractmethod
    def stats(self) -> dict[str, int]:
        """库内作品/章节计数。"""

    @abstractmethod
    def list_uncached_pages(self, limit: int = 200) -> list:
        """未转存页面，用于懒转存。"""

    @abstractmethod
    def mark_page_cached(self, page_id: int, oss_url: str) -> None:
        """标记页面已转存并回填转存 URL。"""

    @abstractmethod
    def mark_page_invalid(self, page_id: int) -> None:
        """标记页面失效。"""

    @abstractmethod
    def list_pages(self, limit: int = 500) -> list:
        """全部页面（含已转存），供巡检校验。"""

    @abstractmethod
    def count_pages_by_status(self) -> dict[str, int]:
        """按 cached_status 统计页面数。"""

    # ------------------------------------------------------------------
    # 只读查询（供 HTTP API 服务使用，见 ../api-service/main.py）
    # ------------------------------------------------------------------
    @abstractmethod
    def list_comics(
        self,
        category: str | None = None,
        keyword: str | None = None,
        sort: str = "updated",
        page: int = 1,
        page_size: int = 12,
    ) -> tuple[list[dict], int]:
        """作品列表，支持分类/关键词/排序(updated|views)/分页，返回 (items, total)。"""

    @abstractmethod
    def get_comic(self, comic_id: int) -> dict | None:
        """作品详情。"""

    @abstractmethod
    def get_chapters(self, comic_id: int) -> list[dict]:
        """章节列表（orderNo 升序）。"""

    @abstractmethod
    def get_chapter(self, chapter_id: int) -> dict | None:
        """单章（用于校验/取页）。"""

    @abstractmethod
    def get_pages(self, chapter_id: int) -> list[dict]:
        """章节分页图片。"""

    @abstractmethod
    def get_categories(self) -> list[dict]:
        """分类与作品数。"""

    @abstractmethod
    def set_comic_cover(self, comic_id: int, cover_url: str) -> None:
        """回填作品封面（图库内相对 key，如 covers/1.jpg）。"""


class SQLiteStorage(Storage):
    """SQLite 实现。线程安全：每个调用使用独立连接，开启 WAL。"""

    def __init__(self, db_path: str = "comic_demo.db") -> None:
        self.db_path = db_path
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """连接上下文：提交后关闭连接（Windows 下避免文件句柄占用）。"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    def get_comic_id_by_fingerprint(self, fingerprint: str) -> int | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM comic WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
        return row["id"] if row else None

    def upsert_comic(self, detail: ComicDetail, fingerprint: str) -> tuple[int, bool]:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM comic WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE comic SET title=?, author=?, status=?, category=?,
                       description=?, latest_chapter_title=?, sync_time=? WHERE id=?""",
                    (
                        detail.title, detail.author, detail.status, detail.category,
                        detail.description, detail.latest_chapter_title, now, row["id"],
                    ),
                )
                return int(row["id"]), False

            # 站内唯一（同源同 ID 但指纹规则变化时兜底更新）
            row = conn.execute(
                "SELECT id FROM comic WHERE source=? AND source_comic_id=?",
                (detail.source, detail.source_comic_id),
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE comic SET title=?, author=?, cover_url=?, status=?, category=?,
                       description=?, fingerprint=?, latest_chapter_title=?, sync_time=? WHERE id=?""",
                    (
                        detail.title, detail.author, detail.cover_url, detail.status,
                        detail.category, detail.description, fingerprint,
                        detail.latest_chapter_title, now, row["id"],
                    ),
                )
                return int(row["id"]), False

            cur = conn.execute(
                """INSERT INTO comic (title, author, cover_url, status, category,
                       description, fingerprint, source, source_comic_id,
                       latest_chapter_title, sync_time)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    detail.title, detail.author, detail.cover_url, detail.status,
                    detail.category, detail.description, fingerprint, detail.source,
                    detail.source_comic_id, detail.latest_chapter_title, now,
                ),
            )
            return int(cur.lastrowid), True

    def upsert_chapter(self, comic_id: int, chapter: ChapterBrief) -> tuple[int, bool]:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM chapter WHERE comic_id=? AND chapter_no=?",
                (comic_id, chapter.chapter_no),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE chapter SET title=?, source_chapter_id=?, sync_time=? WHERE id=?",
                    (chapter.title, chapter.source_chapter_id, now, row["id"]),
                )
                return int(row["id"]), False
            cur = conn.execute(
                """INSERT INTO chapter (comic_id, chapter_no, title, source_chapter_id, sync_time)
                   VALUES (?,?,?,?,?)""",
                (comic_id, chapter.chapter_no, chapter.title, chapter.source_chapter_id, now),
            )
            return int(cur.lastrowid), True

    def upsert_pages(self, chapter_id: int, pages: list[PageInfo]) -> int:
        with self._conn() as conn:
            conn.execute("DELETE FROM page WHERE chapter_id = ?", (chapter_id,))
            conn.executemany(
                """INSERT INTO page (chapter_id, page_no, source_url, oss_url, cached_status)
                   VALUES (?,?,?,?,?)""",
                [
                    (chapter_id, p.page_no, p.source_url, p.oss_url, p.cached_status)
                    for p in pages
                ],
            )
        return len(pages)

    def log_sync(self, source: str, mode: str, stats) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sync_log (source, mode, total_seen, new_comics,
                       updated_comics, new_chapters, failed, started_at, finished_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    source, mode, stats.total_seen, stats.new_comics,
                    stats.updated_comics, stats.new_chapters, stats.failed,
                    stats.started_at, now,
                ),
            )

    def stats(self) -> dict[str, int]:
        with self._conn() as conn:
            comics = conn.execute("SELECT COUNT(*) AS c FROM comic").fetchone()["c"]
            chapters = conn.execute("SELECT COUNT(*) AS c FROM chapter").fetchone()["c"]
            pages = conn.execute("SELECT COUNT(*) AS c FROM page").fetchone()["c"]
        return {"comics": comics, "chapters": chapters, "pages": pages}

    # ------------------------------------------------------------------
    # 图片转存 / 失效巡检支持（见 image_service.py）
    # ------------------------------------------------------------------
    def list_uncached_pages(self, limit: int = 200) -> list[sqlite3.Row]:
        """未转存页面（cached_status = '未转存'），用于懒转存。"""
        with self._conn() as conn:
            return conn.execute(
                """SELECT p.id AS page_id, p.page_no, p.source_url, p.oss_url, p.cached_status,
                          c.comic_id, c.id AS chapter_id
                   FROM page p JOIN chapter c ON p.chapter_id = c.id
                   WHERE p.cached_status = '未转存'
                   ORDER BY p.id LIMIT ?""",
                (limit,),
            ).fetchall()

    def mark_page_cached(self, page_id: int, oss_url: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE page SET oss_url=?, cached_status='已转存' WHERE id=?",
                (oss_url, page_id),
            )

    def mark_page_invalid(self, page_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE page SET cached_status='失效' WHERE id=?",
                (page_id,),
            )

    def list_pages(self, limit: int = 500) -> list[sqlite3.Row]:
        """全部页面（含已转存），供巡检校验文件是否存在。"""
        with self._conn() as conn:
            return conn.execute(
                """SELECT p.id AS page_id, p.page_no, p.source_url, p.oss_url, p.cached_status,
                          c.comic_id, c.id AS chapter_id
                   FROM page p JOIN chapter c ON p.chapter_id = c.id
                   ORDER BY p.id LIMIT ?""",
                (limit,),
            ).fetchall()

    def count_pages_by_status(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT cached_status AS s, COUNT(*) AS c FROM page GROUP BY cached_status"
            ).fetchall()
        return {row["s"]: row["c"] for row in rows}

    # ------------------------------------------------------------------
    # 只读查询（HTTP API 服务）
    # ------------------------------------------------------------------
    def list_comics(
        self,
        category: str | None = None,
        keyword: str | None = None,
        sort: str = "updated",
        page: int = 1,
        page_size: int = 12,
    ) -> tuple[list[dict], int]:
        sql = """SELECT c.*, COUNT(ch.id) AS chapter_count
                 FROM comic c LEFT JOIN chapter ch ON ch.comic_id = c.id"""
        conds: list[str] = []
        params: list = []
        if category and category != "全部":
            conds.append("c.category = ?")
            params.append(category)
        if keyword:
            conds.append(
                "(c.title LIKE ? OR c.author LIKE ? OR c.category LIKE ?)"
            )
            k = f"%{keyword.strip()}%"
            params.extend([k, k, k])
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " GROUP BY c.id"
        if sort == "views":
            sql += " ORDER BY c.id DESC"  # 视图计数由 API 层维护，此处按入库序
        else:
            sql += " ORDER BY c.sync_time DESC"
        total = 0
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM (" + sql + ")",
                params,
            ).fetchone()
            total = row["c"]
            rows = conn.execute(sql + f" LIMIT ? OFFSET ?", params + [page_size, (page - 1) * page_size]).fetchall()
        return [dict(r) for r in rows], total

    def get_comic(self, comic_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT c.*, COUNT(ch.id) AS chapter_count
                   FROM comic c LEFT JOIN chapter ch ON ch.comic_id = c.id
                   WHERE c.id = ? GROUP BY c.id""",
                (comic_id,),
            ).fetchone()
        return dict(row) if row else None

    def set_comic_cover(self, comic_id: int, cover_url: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE comic SET cover_url=? WHERE id=?", (cover_url, comic_id))

    def get_chapters(self, comic_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT ch.*, COUNT(p.id) AS page_count
                   FROM chapter ch LEFT JOIN page p ON p.chapter_id = ch.id
                   WHERE ch.comic_id = ?
                   GROUP BY ch.id ORDER BY ch.chapter_no ASC""",
                (comic_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_chapter(self, chapter_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT ch.*, c.title AS comic_title, c.id AS comic_id, COUNT(p.id) AS page_count
                   FROM chapter ch
                   JOIN comic c ON c.id = ch.comic_id
                   LEFT JOIN page p ON p.chapter_id = ch.id
                   WHERE ch.id = ? GROUP BY ch.id""",
                (chapter_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_pages(self, chapter_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id AS page_id, page_no, source_url, oss_url, cached_status
                   FROM page WHERE chapter_id = ? ORDER BY page_no ASC""",
                (chapter_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_categories(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT category AS name, COUNT(*) AS count FROM comic GROUP BY category ORDER BY count DESC"
            ).fetchall()
        return [dict(r) for r in rows]
