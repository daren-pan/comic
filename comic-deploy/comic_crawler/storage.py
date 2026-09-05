"""存储层抽象：Storage 契约（采集层/调度层只依赖本接口）。

对应架构方案 §3.1：表结构（comic / chapter / page / sync_log / tag / comic_tag）
与 MySQL 版一致。本项目唯一实现为 mysql_storage.MySQLStorage。

去重约定：
- comic.fingerprint UNIQUE          —— 跨站合并（标题指纹+作者）
- comic (source, source_comic_id) UNIQUE —— 站内唯一
- chapter (comic_id, chapter_no) UNIQUE —— 章节唯一
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import ChapterBrief, ComicDetail, PageInfo


class Storage(ABC):
    """存储抽象：采集层只依赖本接口，底层实现可替换（当前唯一实现 MySQL）。"""

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
    def get_last_sync_time(self, source: str) -> str | None:
        """查该源最近一次同步完成时间（sync_log.finished_at），无记录返回 None。

        用作增量水位：None=首次（采集当天全部），否则采集 [finished_at, now] 窗口内更新的漫画。
        """

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
    def get_comic_tags(self, comic_id: int) -> list[str]:
        """作品标签列表（按 comic_tag 表）。"""

    @abstractmethod
    def set_comic_cover(self, comic_id: int, cover_url: str) -> None:
        """回填作品封面（图库内相对 key，如 covers/1.jpg）。"""
