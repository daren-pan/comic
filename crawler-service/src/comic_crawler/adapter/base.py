"""CrawlerAdapter 抽象接口 —— 新增源站的唯一接入点。

对应架构方案 §6.1「源站可插拔」：采集层只依赖本接口。
接入一个新源站只需要两步：
1. 实现一个 CrawlerAdapter 子类，覆盖三个抽象方法；
2. 在 registry.py 中注册（或由配置自动发现）。

业务层、存储层、调度层均不感知具体源站差异。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import ChapterBrief, ComicBrief, ComicDetail, ComicListResult, PageInfo


class CrawlerAdapter(ABC):
    """漫画源站适配器接口。

    属性约定：
    - source_name: 源站唯一标识，写入 comic.source / source 表；
    - base_url:    源站根地址（真实实现为 https 域名）；
    - robots_allowed: 该源是否允许抓取（预检 robots.txt 的结果）。
    """

    source_name: str = ""
    base_url: str = ""
    robots_allowed: bool = True

    def __init__(self, http: "HttpFetcher") -> None:
        self.http = http

    # ------------------------------------------------------------------
    # 生命周期钩子（可选覆盖）
    # ------------------------------------------------------------------
    def pre_fetch(self) -> None:
        """抓取前调用：可在此校验 robots.txt、初始化会话、加载 Cookie。"""

    def post_fetch(self) -> None:
        """一轮抓取结束后调用：可在此释放资源、更新源站状态。"""

    # ------------------------------------------------------------------
    # 三个核心抽象方法：任何源站都必须实现
    # ------------------------------------------------------------------
    @abstractmethod
    def fetch_comic_list(self, page: int = 1, since: "datetime | None" = None) -> ComicListResult:
        """抓取一页漫画列表。

        since: 增量时间窗口起点（None=全量/首次）。支持时间窗口的源站应
        只返回源站更新时间 > since 的漫画；不支持的可忽略此参数。
        增量轮询（只看"最近更新"）与全量扫描（逐页翻完）都通过
        ComicListResult.has_next 驱动翻页。
        """

    @abstractmethod
    def fetch_comic_detail(self, comic: ComicBrief) -> ComicDetail:
        """抓取漫画详情（简介 + 章节列表）。

        comic 来自 fetch_comic_list 的返回，子类用 comic.detail_url
        或 source_comic_id 定位详情页。
        """

    @abstractmethod
    def fetch_chapter_pages(self, detail: ComicDetail, chapter: ChapterBrief) -> list[PageInfo]:
        """抓取章节的图片页列表。

        返回按 page_no 升序的图片列表；图片地址为源站原图，
        转存到 OSS 由图片服务（架构方案 §3.3）另行完成。
        """

    # ------------------------------------------------------------------
    # 可选接口：签名时效源的图片 URL 现场重拉（懒转存重试用）
    # ------------------------------------------------------------------
    def fetch_source_page_urls(
        self, source_comic_id: str, source_chapter_id: str
    ) -> list[str] | None:
        """按源站 id 现场重拉整章最新图片 URL（懒转存遇签名过期时重试）。

        默认不支持（返回 None）：URL 永久有效的源（guazi/pepper/demo 等）
        无需覆写——其 source_url 长期可直接下载。
        带 sign 短时效签名的源（如 zaimanhua）应覆写为「重新请求源站章节
        接口让其重新签发 URL」，并尽量做同批章级缓存避免重复请求。
        """
        return None

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} source={self.source_name} base={self.base_url}>"
