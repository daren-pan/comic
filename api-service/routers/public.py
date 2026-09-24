"""公开接口：健康检查、分类、作品、章节、封面与正文图（无需登录）。

图片端点只做 HTTP 那部分：把 `services.images` 算好的 `ImagePayload` 拼成响应，
并处理 `If-None-Match` → 304 的条件请求。**取数决策（三级兜底、缓存语义）在
`services.images`** —— 见 `resolve_cover_image` / `resolve_page_image`。

⚠️ 图片缓存是 2026-09-21 补的：此前这些响应**一个缓存头都没有**（`Response(content=...)`），
于是每次翻页 / 回列表 / 刷新都在重下整张封面与整话正文图 —— 而它们的字节几乎从不变。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from core.db import db
from core.responses import ok
from serializers import to_chapter, to_comic, to_page
from services.images import ImagePayload, resolve_cover_image, resolve_page_image
from services.ondemand import ensure_chapter_pages
from services.ondemand import search as search_sources
from services.tags import attach_tags

router = APIRouter(tags=["public"])


def _etag_hit(request: Request, etag: str) -> bool:
    """`If-None-Match` 是否命中（支持 `*` 与逗号分隔的多值）。"""
    raw = request.headers.get("if-none-match")
    if not raw:
        return False
    return raw.strip() == "*" or etag in [t.strip() for t in raw.split(",")]


def _image_response(request: Request, payload: ImagePayload) -> Response:
    """`ImagePayload` → 响应；带 ETag 时支持条件请求（命中则 304 空体）。"""
    if payload.etag and _etag_hit(request, payload.etag):
        return Response(status_code=304, headers=payload.headers)
    return Response(content=payload.data, media_type=payload.mime, headers=payload.headers)


@router.get("/api/health")
def health():
    return ok({**db.stats(), "categories": len(db.get_categories())})


@router.get("/api/categories")
def categories():
    items = db.get_categories()
    return ok([{"name": "全部", "count": sum(i["count"] for i in items)}] + items)


@router.get("/api/sources/search")
def sources_search(q: str, source: str | None = None, limit: int = 20):
    """搜索**源站**（只读、不写库）—— 站内搜不到时去「其他来源」找。

    返回按源分组 `[{source, items:[...]}]`：只含支持搜索的源，单源失败静默跳过，
    因此它慢或失败都不会影响站内结果的展示。命中的作品带 `inLibrary` /
    `comicId`，前端据此显示「已收录，直接打开」或「导入并阅读」。
    """
    return ok(search_sources(q, source=source, limit=min(max(1, limit), 50)))


@router.get("/api/comics")
def comics(category: str | None = None, keyword: str | None = None, sort: str = "updated", page: int = 1, page_size: int = 12):
    """作品列表。`sort`：updated=最新更新（默认）/ views=热度倒序 / favorites=收藏数倒序。"""
    page = max(1, page)
    page_size = min(max(1, page_size), 50)
    rows, total = db.list_comics(category=category, keyword=keyword, sort=sort, page=page, page_size=page_size)
    # 批量注入 tags：避免 to_comic 对每行单独查一次（列表接口的主要耗时来源）
    items = [to_comic(r) for r in attach_tags(rows)]
    return ok({"items": items, "total": total, "page": page, "pageSize": page_size})


@router.get("/api/comics/{comic_id}")
def comic_detail(comic_id: int):
    # 浏览 +1 先落库，再重新读取：这样返回热度含本次访问（热度 = 1000 + 浏览 + 2×收藏）
    if not db.increment_comic_views(comic_id):
        raise HTTPException(status_code=404, detail="comic not found")
    row = db.get_comic(comic_id)
    attach_tags([row])   # 标签不在 comic 行上：单条也走同一入口注入（见 services.tags）
    return ok(to_comic(row))


@router.get("/api/comics/{comic_id}/chapters")
def chapters(comic_id: int):
    rows = db.get_chapters(comic_id)
    return ok([to_chapter(r) for r in rows])


@router.get("/api/chapters/{chapter_id}/pages")
def chapter_pages(chapter_id: int):
    ch = db.get_chapter(chapter_id)
    if not ch:
        raise HTTPException(status_code=404, detail="chapter not found")
    # 采集 / 按需导入都不登记页清单（2026-09-21 决策）→ 首次打开这一话时现场补登一次；
    # 已登记过的话这里直接命中库内行，零额外请求。
    ensure_chapter_pages(chapter_id)
    rows = db.get_pages(chapter_id)
    return ok([to_page(r, ch["comic_id"], chapter_id) for r in rows])


@router.get("/api/covers/{comic_id}")
def cover(comic_id: int, request: Request):
    row = db.get_comic(comic_id)
    if not row:
        raise HTTPException(status_code=404, detail="comic not found")
    return _image_response(request, resolve_cover_image(row))


@router.get("/api/images/{comic_id}/{chapter_id}/{page_no}")
def page_image(comic_id: int, chapter_id: int, page_no: int, request: Request):
    ch = db.get_chapter(chapter_id)
    if not ch or ch["comic_id"] != comic_id:
        raise HTTPException(status_code=404, detail="chapter not found")

    # 一条 `get_page_context` 就够：源 URL / 已转存 key / 作品与章节标题 / 本章总页数都在里面。
    # ⚠️ 此前是 `db.get_pages(chapter_id)` 取**整话页清单**再线性找这一页 —— 一话 40 页
    #    就等于读一遍漫画产生 40 次「40 行」的查询，而这里每次只需要一行。
    row = db.get_page_context(chapter_id, page_no)
    if not row:
        raise HTTPException(status_code=404, detail="page not found")

    return _image_response(request, resolve_page_image(row, page_no))
