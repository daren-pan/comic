"""公开接口：健康检查、分类、作品、章节、封面与正文图（无需登录）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from core.db import db
from core.responses import ok
from serializers import attach_tags, to_chapter, to_comic, to_page
from services.images import make_cover_svg, make_page_svg, read_image_file, sniff_image
from services.ondemand import ensure_chapter_pages, fetch_page_online
from services.ondemand import search as search_sources

router = APIRouter(tags=["public"])


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
    # 按需导入的作品导入时刻意不登记页清单 → 首次打开这一话时现场补登一次
    # （常规采集的作品已有清单，这里是零额外请求的快路径）
    ensure_chapter_pages(chapter_id)
    rows = db.get_pages(chapter_id)
    return ok([to_page(r, ch["comic_id"], chapter_id) for r in rows])


@router.get("/api/covers/{comic_id}")
def cover(comic_id: int):
    row = db.get_comic(comic_id)
    if not row:
        raise HTTPException(status_code=404, detail="comic not found")
    img = read_image_file(row.get("cover_url") or "")
    if img:
        return Response(content=img[0], media_type=img[1])
    return Response(content=make_cover_svg(row["title"], row["author"]), media_type="image/svg+xml")


@router.get("/api/images/{comic_id}/{chapter_id}/{page_no}")
def page_image(comic_id: int, chapter_id: int, page_no: int):
    ch = db.get_chapter(chapter_id)
    if not ch or ch["comic_id"] != comic_id:
        raise HTTPException(status_code=404, detail="chapter not found")
    rows = db.get_pages(chapter_id)
    row = next((p for p in rows if p["page_no"] == page_no), None)
    if not row:
        raise HTTPException(status_code=404, detail="page not found")

    # 1) 本地图库命中（已转存的文件 / 图库内相对 key）—— 最快路径
    img = read_image_file(row.get("oss_url") or "") or read_image_file(row.get("source_url") or "")
    if img:
        return Response(content=img[0], media_type=img[1])

    # 2) 穿透取图：本地没有 → 现场从源站取**这一张**，顺手落盘（下次访问走本地）。
    #    用户等待 = 源站响应一张图的时间，而不是「整话下载完」；签名过期会自动重签。
    data = fetch_page_online(chapter_id, page_no)
    if data:
        return Response(content=data, media_type=sniff_image(data) or "image/jpeg")

    # 3) 兜底：源站也取不到 → 占位图（保证不裂图），状态保持「未转存」待下次重试
    comic = db.get_comic(comic_id)
    return Response(
        content=make_page_svg(comic["title"] if comic else "漫画", ch["title"], page_no, len(rows)),
        media_type="image/svg+xml",
    )
