"""存储层契约：`Storage`（漫画侧）+ `UserStore`（用户中心）。

对应架构方案 §3.1：表结构（comic / chapter / page / sync_log / tag / comic_tag）
与 MySQL 版一致。本项目唯一实现为 `storage.mysql`。

**扩展点**：新增存储后端（PostgreSQL / 内存 Mock / 分库）只需实现这两个 ABC，
采集层、调度层与 API 层均无需改动 —— 上层只认本文件的接口。

去重约定：
- comic.fingerprint UNIQUE          —— 跨站合并（标题指纹+作者）
- comic (source, source_comic_id) UNIQUE —— 站内唯一
- chapter (comic_id, chapter_no) UNIQUE —— 章节唯一
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import ChapterBrief, ComicDetail, PageInfo


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
    def get_last_sync_time(self, source: str) -> datetime | None:
        """查该源最近一次同步完成时间（`sync_log.finished_at`，DATETIME），无记录返回 None。

        用作增量水位：None=首次（采集当天全部），否则采集 [finished_at, now] 窗口内更新的漫画。
        返回 naive datetime（naive 按本机时区解释，与适配器的时间比较语义一致）。
        """

    @abstractmethod
    def stats(self) -> dict[str, int]:
        """库内作品/章节计数。"""

    @abstractmethod
    def list_uncached_pages(
        self, limit: int | None = None, since=None, until=None, source=None
    ) -> list:
        """未转存页面，用于懒转存。

        limit：本次最多取多少页；None/<=0 = 不限制（取窗口内全部）。
        since/until：按所属章节 `sync_time`（DATETIME，≈该批入库时刻）过滤，
        用于「只转存某次增量采集新入库的页」。边界**双端含**：只给日期时
        `until` 含当天全天。None 表示不限制该侧边界。
        source：按数据源过滤（如 'zaimanhua'）；None = 不限制。
        """

    @abstractmethod
    def mark_page_cached(self, page_id: int, oss_url: str) -> None:
        """标记页面已转存并回填转存 URL。"""

    @abstractmethod
    def mark_page_invalid(self, page_id: int) -> None:
        """标记页面失效。"""

    @abstractmethod
    def list_pages(
        self, after_id: int = 0, limit: int = 1000, source: str | None = None
    ) -> list:
        """按 id 升序**键集分页**取页（巡检遍历全表用，**不是"取全部"**）。

        ⚠️ 语义是「一批」而非「全部」：调用方须用返回行的最大 `page_id` 推进
        `after_id` 反复调用，直到某批不足 `limit` 条为止 —— 这样才能覆盖全表。
        旧实现是 `list_pages(limit=500)` 一把取 500 条，而 SQL 又是 `ORDER BY id`，
        于是巡检**每轮都只校验 id 最小的同一批 500 页**，其余已转存页从未被校验/恢复。

        after_id：只返回 id > after_id 的行（键集分页游标；0 = 从头开始）。
        limit：单批条数上限（控制内存）。
        source：只取该数据源的页；None = 全部源。
        """

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


class UserStore(ABC):
    """用户中心契约：账号 + 收藏 + 阅读历史（被 api-service 调用）。"""

    @abstractmethod
    def get_user_by_username(self, username: str) -> dict | None:
        """按用户名查用户（含 password_hash），用于注册去重与登录校验。"""

    @abstractmethod
    def create_user(self, username: str, password_hash: str, nickname: str) -> dict:
        """创建用户并返回完整记录。"""

    @abstractmethod
    def get_user(self, user_id: str) -> dict | None:
        """按 ID 查用户（鉴权依赖用它还原当前用户）。"""

    @abstractmethod
    def list_favorites(self, user_id: str) -> list[int]:
        """用户收藏的作品 ID（按收藏时间倒序）。"""

    @abstractmethod
    def is_favorite(self, user_id: str, comic_id: int) -> bool:
        """是否已收藏。"""

    @abstractmethod
    def set_favorite(self, user_id: str, comic_id: int, fav: bool) -> None:
        """添加/取消收藏（幂等）。"""

    @abstractmethod
    def list_history(self, user_id: str) -> list[dict]:
        """阅读历史（按最后阅读时间倒序，含章节标题）。"""

    @abstractmethod
    def upsert_history(
        self, user_id: str, comic_id: int, chapter_id: int, page_no: int
    ) -> None:
        """写入/更新阅读进度：每用户每作品只保留一条**最新**进度。"""

    @abstractmethod
    def delete_history(self, user_id: str, comic_id: int) -> None:
        """删除某作品的阅读历史。"""
