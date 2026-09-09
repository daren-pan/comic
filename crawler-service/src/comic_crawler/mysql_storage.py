"""存储层 MySQL 唯一实现（Storage 契约）。

对应架构方案 §3.1/§6.1：生产环境用 MySQL。连接参数通过环境变量配置。

连接参数（环境变量，均有默认值）：
    COMIC_MYSQL_HOST    默认 127.0.0.1
    COMIC_MYSQL_PORT    默认 3307 （Docker ruoyi-mysql 映射端口）
    COMIC_MYSQL_USER    默认 root
    COMIC_MYSQL_PASSWORD 默认 password
    COMIC_MYSQL_DB      默认 comic
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor

from .models import ChapterBrief, ComicDetail, PageInfo
from .storage import Storage

logger = logging.getLogger(__name__)

_DSN = {
    "host": os.environ.get("COMIC_MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("COMIC_MYSQL_PORT", "3307")),
    "user": os.environ.get("COMIC_MYSQL_USER", "root"),
    "password": os.environ.get("COMIC_MYSQL_PASSWORD", "password"),
    "database": os.environ.get("COMIC_MYSQL_DB", "comic"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
    "autocommit": True,
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class MySQLStorage(Storage):
    """MySQL 实现（Storage 契约）。每个调用使用独立连接（线程安全），autocommit 提交。"""

    def __init__(self, dsn: dict | None = None) -> None:
        self.dsn = dsn or _DSN
        # 惰性校验连接（避免 import 时数据库未就绪）
        try:
            with self._conn():
                pass
        except Exception as e:  # pragma: no cover
            logger.warning("MySQL 连接校验失败（稍后重试）: %s", e)

    @contextmanager
    def _conn(self) -> Iterator[pymysql.connections.Connection]:
        conn = pymysql.connect(**self.dsn)
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    def get_comic_id_by_fingerprint(self, fingerprint: str) -> int | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM comic WHERE fingerprint = %s", (fingerprint,))
                row = cur.fetchone()
        return int(row["id"]) if row else None

    @staticmethod
    def _tags_from(detail: ComicDetail) -> list[str]:
        """取标签列表：优先 detail.tags；为空则用 category 拆分（兼容未填 tags 的源）。

        分隔符优先级（2026-09-05 修复）：斜杠 > 全角逗号 > 半角逗号 > 顿号 > 间隔号 > 空格。
        原实现把"空格"排在斜杠前，导致「连载 / 国漫」先被空格切开，`/` 成为孤儿标签
        （如 tag 表出现 `/`、漫画被错误关联 33 部）。
        """
        tags = [t.strip() for t in (detail.tags or []) if t and t.strip()]
        if not tags and detail.category:
            _SEPS = ("/", "，", ",", "、", "·", " ")
            for sep in _SEPS:
                if sep in detail.category:
                    tags = [s.strip() for s in detail.category.split(sep) if s.strip()]
                    break
            else:
                tags = [detail.category.strip()]
        return tags

    @staticmethod
    def _sync_tags(cur, comic_id: int, tags: list[str]) -> None:
        """重建漫画-标签关联：先清空旧关联，再逐个标签 upsert 进 tag 字典表并写关联表。

        规范化结构：tag(name) 字典表每唯一标签一行；comic_tag(comic_id, tag_id) 只存引用。
        """
        cur.execute("DELETE FROM comic_tag WHERE comic_id = %s", (comic_id,))
        seen: set[str] = set()
        for t in tags:
            t = t.strip()
            # 防御：跳过空串、纯符号/空白片段（如 '/'、'·'）——避免孤儿标签
            if not t or t in seen or not re.search(r"[\w\u4e00-\u9fff]", t):
                continue
            seen.add(t)
            # upsert 标签字典表：name 唯一，已存在则取回 id
            cur.execute("INSERT IGNORE INTO tag (name) VALUES (%s)", (t,))
            cur.execute("SELECT id FROM tag WHERE name = %s", (t,))
            row = cur.fetchone()
            if not row:
                continue
            cur.execute(
                "INSERT IGNORE INTO comic_tag (comic_id, tag_id) VALUES (%s, %s)",
                (comic_id, row["id"]),
            )

    def upsert_comic(self, detail: ComicDetail, fingerprint: str) -> tuple[int, bool]:
        now = _now()
        tags = self._tags_from(detail)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM comic WHERE fingerprint = %s", (fingerprint,))
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """UPDATE comic SET title=%s, author=%s, status=%s, category=%s,
                           description=%s, latest_chapter_title=%s, sync_time=%s WHERE id=%s""",
                        (
                            detail.title, detail.author, detail.status, detail.category,
                            detail.description, detail.latest_chapter_title, now, row["id"],
                        ),
                    )
                    self._sync_tags(cur, row["id"], tags)
                    return int(row["id"]), False

                cur.execute(
                    "SELECT id FROM comic WHERE source=%s AND source_comic_id=%s",
                    (detail.source, detail.source_comic_id),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """UPDATE comic SET title=%s, author=%s, cover_url=%s, status=%s,
                           category=%s, description=%s, fingerprint=%s,
                           latest_chapter_title=%s, sync_time=%s WHERE id=%s""",
                        (
                            detail.title, detail.author, detail.cover_url, detail.status,
                            detail.category, detail.description, fingerprint,
                            detail.latest_chapter_title, now, row["id"],
                        ),
                    )
                    self._sync_tags(cur, row["id"], tags)
                    return int(row["id"]), False

                # 首次收录：addtime 与 sync_time 均为当前时刻；后续增量只刷新 sync_time（见上方 UPDATE）
                cur.execute(
                    """INSERT INTO comic (title, author, cover_url, status, category,
                           description, fingerprint, source, source_comic_id,
                           latest_chapter_title, sync_time, addtime)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        detail.title, detail.author, detail.cover_url, detail.status,
                        detail.category, detail.description, fingerprint, detail.source,
                        detail.source_comic_id, detail.latest_chapter_title, now, now,
                    ),
                )
                comic_id = int(cur.lastrowid)
                self._sync_tags(cur, comic_id, tags)
                return comic_id, True

    def upsert_chapter(self, comic_id: int, chapter: ChapterBrief) -> tuple[int, bool]:
        now = _now()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM chapter WHERE comic_id=%s AND chapter_no=%s",
                    (comic_id, chapter.chapter_no),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "UPDATE chapter SET title=%s, source_chapter_id=%s, sync_time=%s WHERE id=%s",
                        (chapter.title, chapter.source_chapter_id, now, row["id"]),
                    )
                    return int(row["id"]), False
                cur.execute(
                    """INSERT INTO chapter (comic_id, chapter_no, title, source_chapter_id, sync_time)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (comic_id, chapter.chapter_no, chapter.title, chapter.source_chapter_id, now),
                )
                return int(cur.lastrowid), True

    def upsert_pages(self, chapter_id: int, pages: list[PageInfo]) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM page WHERE chapter_id = %s", (chapter_id,))
                cur.executemany(
                    """INSERT INTO page (chapter_id, page_no, source_url, oss_url, cached_status)
                       VALUES (%s,%s,%s,%s,%s)""",
                    [
                        (chapter_id, p.page_no, p.source_url, p.oss_url, p.cached_status)
                        for p in pages
                    ],
                )
        return len(pages)

    def update_chapter_no(self, comic_id: int, chapter_id: int, old_no: int, new_no: int) -> bool:
        """把某章节的 chapter_no（唯一键 comic_id+chapter_no）改为 new_no。

        语义迁移场景：把 chapter_no 从"话数"改为"源站 chapter_order"，用于正确排序
        分卷小话（第153.5话）。两步法避免唯一键瞬时冲突：
        1. 先把该行 chapter_no 临时改为与任何现有值都不冲突的临时值；
        2. 再改为目标 new_no。
        仅当目标值 new_no 已被本漫画其他章节占用时返回 False（调用方跳过）。
        """
        tmp = -(chapter_id + 1)  # 负临时值，保证不与正号 order 冲突（chapter_id 唯一）
        with self._conn() as conn:
            with conn.cursor() as cur:
                # 目标是否已被同一漫画的其他章节占用（排除本行）
                cur.execute(
                    "SELECT id FROM chapter WHERE comic_id=%s AND chapter_no=%s AND id<>%s",
                    (comic_id, new_no, chapter_id),
                )
                if cur.fetchone() is not None:
                    return False
                cur.execute(
                    "UPDATE chapter SET chapter_no=%s WHERE id=%s",
                    (tmp, chapter_id),
                )
                cur.execute(
                    "UPDATE chapter SET chapter_no=%s WHERE id=%s",
                    (new_no, chapter_id),
                )
        return True

    def log_sync(self, source: str, mode: str, stats) -> None:
        now = _now()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sync_log (source, mode, total_seen, new_comics,
                           updated_comics, new_chapters, failed, started_at, finished_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        source, mode, stats.total_seen, stats.new_comics,
                        stats.updated_comics, stats.new_chapters, stats.failed,
                        stats.started_at, now,
                    ),
                )

    def get_last_sync_time(self, source: str) -> str | None:
        """查该源最近一次同步完成时间（finished_at），用作增量水位；无记录返回 None。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT finished_at FROM sync_log WHERE source=%s ORDER BY id DESC LIMIT 1",
                    (source,),
                )
                row = cur.fetchone()
        return str(row["finished_at"]) if row else None

    def stats(self) -> dict[str, int]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM comic")
                comics = cur.fetchone()["c"]
                cur.execute("SELECT COUNT(*) AS c FROM chapter")
                chapters = cur.fetchone()["c"]
                cur.execute("SELECT COUNT(*) AS c FROM page")
                pages = cur.fetchone()["c"]
        return {"comics": comics, "chapters": chapters, "pages": pages}

    # ------------------------------------------------------------------
    # 图片转存 / 失效巡检支持
    # ------------------------------------------------------------------
    def list_uncached_pages(
        self, limit: int = 200, since=None, until=None, source=None
    ) -> list[dict]:
        """未转存页；since/until 按章节 sync_time（≈入库时刻）过滤，用于增量后只转新页。

        source：按数据源过滤（如 'zaimanhua'）；None 表示不限制。
        """
        conds = ["p.cached_status = '未转存'"]
        params: list[object] = []
        if since is not None:
            conds.append("c.sync_time >= %s")
            params.append(str(since))
        if until is not None:
            conds.append("c.sync_time < %s")
            params.append(str(until))
        if source:
            conds.append("co.source = %s")
            params.append(str(source))
        params.append(limit)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT p.id AS page_id, p.page_no, p.source_url, p.oss_url, p.cached_status,
                              c.comic_id, c.id AS chapter_id, c.source_chapter_id,
                              co.source, co.source_comic_id
                       FROM page p
                       JOIN chapter c ON p.chapter_id = c.id
                       JOIN comic co ON c.comic_id = co.id
                       WHERE {" AND ".join(conds)}
                       ORDER BY p.id LIMIT %s""",
                    params,
                )
                return list(cur.fetchall())

    def mark_page_cached(self, page_id: int, oss_url: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE page SET oss_url=%s, cached_status='已转存' WHERE id=%s",
                    (oss_url, page_id),
                )

    def mark_page_invalid(self, page_id: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE page SET cached_status='失效' WHERE id=%s",
                    (page_id,),
                )

    def list_pages(self, limit: int = 500) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT p.id AS page_id, p.page_no, p.source_url, p.oss_url, p.cached_status,
                              c.comic_id, c.id AS chapter_id
                       FROM page p JOIN chapter c ON p.chapter_id = c.id
                       ORDER BY p.id LIMIT %s""",
                    (limit,),
                )
                return list(cur.fetchall())

    def count_pages_by_status(self) -> dict[str, int]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cached_status AS s, COUNT(*) AS c FROM page GROUP BY cached_status"
                )
                rows = list(cur.fetchall())
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
        sql = """SELECT c.*, COUNT(DISTINCT ch.id) AS chapter_count
                 FROM comic c
                 LEFT JOIN chapter ch ON ch.comic_id = c.id
                 LEFT JOIN comic_tag ct ON ct.comic_id = c.id
                 LEFT JOIN tag t ON t.id = ct.tag_id"""
        conds: list[str] = []
        params: list = []
        if category and category != "全部":
            conds.append("t.name = %s")
            params.append(category)
        if keyword:
            conds.append("(c.title LIKE %s OR c.author LIKE %s OR c.category LIKE %s OR t.name LIKE %s)")
            k = f"%{keyword.strip()}%"
            params.extend([k, k, k, k])
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " GROUP BY c.id"
        if sort == "views":
            sql += " ORDER BY c.id DESC"
        else:
            sql += " ORDER BY c.sync_time DESC"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM (" + sql + ") AS t", params)
                total = cur.fetchone()["c"]
                cur.execute(
                    sql + " LIMIT %s OFFSET %s", params + [page_size, (page - 1) * page_size]
                )
                rows = list(cur.fetchall())
        return rows, total

    def get_comic(self, comic_id: int) -> dict | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT c.*, COUNT(ch.id) AS chapter_count
                       FROM comic c LEFT JOIN chapter ch ON ch.comic_id = c.id
                       WHERE c.id = %s GROUP BY c.id""",
                    (comic_id,),
                )
                row = cur.fetchone()
        return row

    def set_comic_cover(self, comic_id: int, cover_url: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE comic SET cover_url=%s WHERE id=%s", (cover_url, comic_id)
                )

    def get_chapters(self, comic_id: int) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ch.*, COUNT(p.id) AS page_count
                       FROM chapter ch LEFT JOIN page p ON p.chapter_id = ch.id
                       WHERE ch.comic_id = %s
                       GROUP BY ch.id ORDER BY ch.chapter_no ASC""",
                    (comic_id,),
                )
                return list(cur.fetchall())

    def get_chapter(self, chapter_id: int) -> dict | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ch.*, c.title AS comic_title, c.id AS comic_id,
                              COUNT(p.id) AS page_count
                       FROM chapter ch
                       JOIN comic c ON c.id = ch.comic_id
                       LEFT JOIN page p ON p.chapter_id = ch.id
                       WHERE ch.id = %s GROUP BY ch.id""",
                    (chapter_id,),
                )
                return cur.fetchone()

    def get_pages(self, chapter_id: int) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id AS page_id, page_no, source_url, oss_url, cached_status
                       FROM page WHERE chapter_id = %s ORDER BY page_no ASC""",
                    (chapter_id,),
                )
                return list(cur.fetchall())

    def get_categories(self) -> list[dict]:
        # 基于关联表 JOIN 标签字典表聚合：每个标签计为"分类"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT t.name AS name, COUNT(DISTINCT ct.comic_id) AS count
                       FROM comic_tag ct JOIN tag t ON t.id = ct.tag_id
                       GROUP BY t.id ORDER BY count DESC"""
                )
                return list(cur.fetchall())

    def get_comic_tags(self, comic_id: int) -> list[str]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT t.name AS name FROM comic_tag ct
                       JOIN tag t ON t.id = ct.tag_id
                       WHERE ct.comic_id = %s ORDER BY t.name ASC""",
                    (comic_id,),
                )
                return [r["name"] for r in cur.fetchall()]


# ---------------- 用户中心（favorite / history，对应 api-service UserStore） ----------------

class MySQLUserStore:
    """用户中心 MySQL 实现：接口与 api-service/main.py 的 UserStore 一致。"""

    def __init__(self, dsn: dict | None = None) -> None:
        self.dsn = dsn or _DSN

    @contextmanager
    def _conn(self) -> Iterator[pymysql.connections.Connection]:
        conn = pymysql.connect(**self.dsn)
        try:
            yield conn
        finally:
            conn.close()

    def list_favorites(self, user_id: str) -> list[int]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT comic_id FROM favorite WHERE user_id=%s ORDER BY created_at DESC",
                    (user_id,),
                )
                return [int(r["comic_id"]) for r in cur.fetchall()]

    # ---- 用户账户（登录/注册） ----
    def get_user_by_username(self, username: str) -> dict | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user WHERE username=%s", (username,))
                row = cur.fetchone()
                return dict(row) if row else None

    def create_user(self, username: str, password_hash: str, nickname: str) -> dict:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO user (username, password_hash, nickname, created_at)
                       VALUES (%s,%s,%s,%s)""",
                    (username, password_hash, nickname, _now()),
                )
                conn.commit()
                cur.execute("SELECT * FROM user WHERE id=%s", (cur.lastrowid,))
                return dict(cur.fetchone())

    def get_user(self, user_id: str) -> dict | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM user WHERE id=%s", (user_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def is_favorite(self, user_id: str, comic_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM favorite WHERE user_id=%s AND comic_id=%s",
                    (user_id, comic_id),
                )
                return cur.fetchone() is not None

    def set_favorite(self, user_id: str, comic_id: int, fav: bool) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                if fav:
                    cur.execute(
                        "INSERT IGNORE INTO favorite (user_id, comic_id, created_at) VALUES (%s,%s,%s)",
                        (user_id, comic_id, _now()),
                    )
                else:
                    cur.execute(
                        "DELETE FROM favorite WHERE user_id=%s AND comic_id=%s",
                        (user_id, comic_id),
                    )

    def list_history(self, user_id: str) -> list[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT h.comic_id, h.chapter_id, h.page_no, h.read_at,
                              ch.title AS chapter_title
                       FROM history h LEFT JOIN chapter ch ON ch.id = h.chapter_id
                       WHERE h.user_id=%s ORDER BY h.read_at DESC LIMIT 50""",
                    (user_id,),
                )
                return list(cur.fetchall())

    def upsert_history(self, user_id: str, comic_id: int, chapter_id: int, page_no: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO history (user_id, comic_id, chapter_id, page_no, read_at)
                       VALUES (%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE
                           chapter_id=VALUES(chapter_id), page_no=VALUES(page_no),
                           read_at=VALUES(read_at)""",
                    (user_id, comic_id, chapter_id, page_no, _now()),
                )

    def delete_history(self, user_id: str, comic_id: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM history WHERE user_id=%s AND comic_id=%s",
                    (user_id, comic_id),
                )
