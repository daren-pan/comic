"""按需导入与「读时准备」（API 侧编排）。

把 crawler 的按需能力接到 HTTP 层，四件事：

1. `search()`              —— 搜源站（**只读不写库**），带进程内缓存、单源失败静默降级；
2. `import_one()`          —— 按需导入单部作品（搜索页「导入并阅读」/ 管理台）；
3. `ensure_chapter_pages()`—— 打开某话时若库内还没有页清单，现场登记；
4. `fetch_page_online()`   —— 读某页时本地没有图，穿透源站取回并顺手落盘。

三条与前端体验对应的设计约束：

- **搜索绝不写库**：库内统计（管理台「库内 N 部」）只反映"真的被收录的作品"，
  不被搜索行为污染；搜到不等于收录。
- **导入不下载正文图**：只写 1 行书目 + 全量章节 + 落盘封面；正文图一张不碰。
- **读图不等整话**：单张图从源站取回即返回给浏览器，落盘在同一次请求内完成
  （「边看边转」），用户等待只等于源站响应一张图的时间。
"""
from __future__ import annotations

import logging
import threading
import time

from core.db import db
from services.images import admin_image_store

logger = logging.getLogger(__name__)

# 源站搜索结果进程内缓存：同一关键词短时间内重复搜索（多次回车 / 多人搜同词）
# 不再打源站。TTL 内直接复用，源站礼仪与响应速度都受益。
_SEARCH_CACHE: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_SEARCH_TTL = 300.0
_SEARCH_MAX_ENTRIES = 200
_SEARCH_LOCK = threading.Lock()


def _adapter(source: str):
    """按源名取适配器实例（crawler 侧的工厂函数）。"""
    from comic_crawler.sources import create_adapter

    return create_adapter(source)


def searchable_sources() -> list[str]:
    """支持关键词搜索**且已启用**的源名（按 SOURCES 顺序，主源在前）。

    两个条件都要满足：
    - 适配器声明了 `capabilities` 含 "search"（各源能力不同，见 sources/base.py）；
    - 该源在管理台处于**启用**状态（`services.sources.is_enabled`）—— 关掉一个源
      意味着"别再碰它"，搜索也不该再去问它。
    """
    from comic_crawler.sources import SOURCES

    from services import sources as source_state

    names: list[str] = []
    for s in SOURCES:
        try:
            if not source_state.is_enabled(s.name):
                continue
            if "search" in getattr(_adapter(s.name), "capabilities", set()):
                names.append(s.name)
        except Exception:  # 适配器不可用不影响其他源
            continue
    return names


def _to_item(source: str, brief) -> dict:
    """ComicBrief → 前端契约。`comicId`/`inLibrary` 让前端能显示「已收录，直接打开」。"""
    comic_id = db.get_comic_id_by_source(source, brief.source_comic_id)
    return {
        "source": source,
        "sourceComicId": brief.source_comic_id,
        "title": brief.title,
        "author": brief.author,
        "cover": brief.cover_url,
        "status": brief.status,
        "latestChapterTitle": brief.latest_chapter_title,
        "tags": list(brief.tags or []),
        "comicId": comic_id,           # 非 None = 库内已收录
        "inLibrary": comic_id is not None,
    }


def _search_one(name: str, keyword: str, limit: int) -> list[dict]:
    key = (name, keyword.lower())
    now = time.time()
    with _SEARCH_LOCK:
        hit = _SEARCH_CACHE.get(key)
        if hit and now - hit[0] < _SEARCH_TTL:
            return hit[1]
    try:
        adapter = _adapter(name)
        if "search" not in getattr(adapter, "capabilities", set()):
            return []
        briefs = adapter.search_comics(keyword, limit=limit)
        items = [_to_item(name, b) for b in briefs]
    except Exception as exc:
        # 单源失败静默降级：前端仍能看到站内结果与其他源的结果
        logger.warning("源站搜索失败 source=%s keyword=%s: %s", name, keyword, exc)
        return []
    with _SEARCH_LOCK:
        if len(_SEARCH_CACHE) >= _SEARCH_MAX_ENTRIES:
            _SEARCH_CACHE.clear()
        _SEARCH_CACHE[key] = (now, items)
    return items


def search(keyword: str, source: str | None = None, limit: int = 20) -> list[dict]:
    """搜索源站，按源分组返回；**只读，不写库**。"""
    kw = (keyword or "").strip()
    if not kw:
        return []
    names = [source] if source else searchable_sources()
    results: list[dict] = []
    for name in names:
        items = _search_one(name, kw, limit)
        if items:
            results.append({"source": name, "items": items})
    return results


def import_one(
    source: str,
    *,
    keyword: str | None = None,
    ref: str | None = None,
    source_comic_id: str | None = None,
    first_chapters: int | None = None,
) -> dict:
    """按需导入一部作品（同步执行；管理台把它丢进后台线程）。"""
    from comic_crawler.scheduling import import_comic

    return import_comic(
        _adapter(source),
        db,
        keyword=keyword,
        ref=ref,
        source_comic_id=source_comic_id,
        first_chapters=first_chapters,
    )


def _chapter_brief(source: str, comic: dict, chapter: dict):
    from comic_crawler.models import ChapterBrief

    return ChapterBrief(
        source=source,
        source_comic_id=str(comic["source_comic_id"]),
        chapter_no=int(chapter["chapter_no"]),
        title=chapter.get("title") or "",
        source_chapter_id=str(chapter["source_chapter_id"]),
    )


def _detail_stub(source: str, comic: dict):
    """给 `fetch_chapter_pages` 用的最小详情壳（现有适配器只用 chapter 参数）。"""
    from comic_crawler.models import ComicDetail

    return ComicDetail(
        source=source,
        source_comic_id=str(comic["source_comic_id"]),
        title=comic.get("title") or "",
        author=comic.get("author") or "",
        cover_url=comic.get("cover_url") or "",
    )


def ensure_chapter_pages(chapter_id: int) -> int:
    """打开某话时若库内还没有页清单，就现场登记一次，返回登记后的页数。

    只有「按需导入」的作品会出现空清单（导入时刻意一页都不登记）；常规采集的作品
    最新一话已登记，所以这里是零额外请求的快路径。
    """
    rows = db.get_pages(chapter_id)
    if rows:
        return len(rows)
    chapter = db.get_chapter(chapter_id)
    if not chapter:
        return 0
    comic = db.get_comic(chapter["comic_id"])
    if not comic:
        return 0
    source = str(comic.get("source") or "")
    try:
        adapter = _adapter(source)
        pages = adapter.fetch_chapter_pages(
            _detail_stub(source, comic), _chapter_brief(source, comic, chapter)
        )
        if pages:
            db.upsert_pages(chapter_id, pages)
            logger.info(
                "读时登记页清单 chapter_id=%s source=%s 共 %d 页", chapter_id, source, len(pages)
            )
        return len(pages)
    except Exception as exc:
        logger.warning("读时登记页清单失败 chapter_id=%s: %s", chapter_id, exc)
        return 0


def fetch_page_online(chapter_id: int, page_no: int) -> bytes | None:
    """本地没有这张图 → 穿透源站取回并顺手落盘；失败返回 None（调用方给占位图）。"""
    from comic_crawler.images.transfer import fetch_page_bytes
    from comic_crawler.sources import create_adapter

    row = db.get_page_context(chapter_id, page_no)
    if not row:
        return None
    try:
        return fetch_page_bytes(db, admin_image_store(), row, adapter_provider=create_adapter)
    except Exception as exc:
        logger.warning("穿透取图失败 chapter=%s page=%s: %s", chapter_id, page_no, exc)
        return None


