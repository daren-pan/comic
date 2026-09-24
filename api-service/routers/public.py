"""公开接口：健康检查、分类、作品、章节、封面与正文图（无需登录）。

图片端点三级兜底（**顺序不能变**，见 `page_image`）：本地图库 → 源站穿透 → SVG 占位图。
三级各自带**正确的缓存语义**：前两级可长缓存，占位图必须 `no-store` ——
否则"当时取不到"的兜底图会被浏览器缓存住，源站恢复了用户还看旧图。

⚠️ 图片缓存是 2026-09-21 补的：此前这些响应**一个缓存头都没有**（`Response(content=...)`），
于是每次翻页 / 回列表 / 刷新都在重下整张封面与整话正文图 —— 而它们的字节几乎从不变。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from core.db import db
from core.responses import ok
from serializers import to_chapter, to_comic, to_page
from services.images import make_cover_svg, make_page_svg, read_image_file, sniff_image
from services.ondemand import ensure_chapter_pages, fetch_page_online
from services.ondemand import search as search_sources
from services.tags import attach_tags

router = APIRouter(tags=["public"])

#: 封面可以被「管理台 · 封面自愈（force=True）」换掉，所以只给 1 小时 ——
#: 换图后最多 1 小时全站生效；1 小时内的重复请求由 ETag 条件请求兜住（304 空体，不重传）。
COVER_MAX_AGE = 3600
#: 正文页按 `(comic, chapter, page)` 落盘后内容即固定 → 7 天长缓存。两条命中路径的
#: 缓存语义略有差别（都够用）：**本地命中**带 ETag（过期后条件请求换 304，不重传）；
#: **穿透命中**直接给 `immutable`（字节就在手上，不值得为它多读一次刚写好的文件去算 ETag）。
PAGE_MAX_AGE = 7 * 24 * 3600
#: 占位图 = 临时兜底（源站没取到），**绝不能缓存**。
NO_STORE = {"Cache-Control": "no-store"}


def _etag_hit(request: Request, etag: str) -> bool:
    """`If-None-Match` 是否命中（支持 `*` 与逗号分隔的多值）。"""
    raw = request.headers.get("if-none-match")
    if not raw:
        return False
    return raw.strip() == "*" or etag in [t.strip() for t in raw.split(",")]


def _file_response(request: Request, img: tuple[bytes, str, str], max_age: int) -> Response:
    """图库命中：带 ETag 的图片响应（条件请求命中则返回 304 空体）。"""
    data, mime, etag = img
    headers = {"Cache-Control": f"public, max-age={max_age}", "ETag": etag}
    if _etag_hit(request, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=mime, headers=headers)


def _passthrough_response(data: bytes) -> Response:
    """穿透取图成功：把**刚落盘**的这张图直接返回，并带上与本地命中一致的长缓存。

    这里刻意不带 ETag：正文页用 `immutable`（7 天内浏览器不回头问），
    既然不打算再验证，就没必要为它多读一次刚写好的文件去算 ETag。
    """
    return Response(
        content=data,
        media_type=sniff_image(data) or "image/jpeg",
        headers={"Cache-Control": f"public, max-age={PAGE_MAX_AGE}, immutable"},
    )


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
    img = read_image_file(row.get("cover_url") or "")
    if img:
        return _file_response(request, img, COVER_MAX_AGE)
    return Response(
        content=make_cover_svg(row["title"], row["author"]),
        media_type="image/svg+xml",
        headers=NO_STORE,
    )


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

    # 1) 本地图库命中（已转存的文件 / 图库内相对 key）—— 最快路径
    img = read_image_file(row.get("oss_url") or "") or read_image_file(row.get("source_url") or "")
    if img:
        return _file_response(request, img, PAGE_MAX_AGE)

    # 2) 穿透取图：本地没有 → 现场从源站取**这一张**，顺手落盘（下次访问走本地）。
    #    用户等待 = 源站响应一张图的时间，而不是「整话下载完」；签名过期会自动重签。
    #    并发闸门 / 同图去重 / 失败负缓存都在 crawler 侧（见 images/transfer.py）。
    data = fetch_page_online(chapter_id, page_no, row=row)
    if data:
        return _passthrough_response(data)

    # 3) 兜底：源站也取不到 → 占位图（保证不裂图），状态保持「未转存」待下次重试
    comic = db.get_comic(comic_id)
    return Response(
        content=make_page_svg(
            comic["title"] if comic else "漫画",
            ch["title"],
            page_no,
            int(row.get("total_pages") or 0) or page_no,
        ),
        media_type="image/svg+xml",
        headers=NO_STORE,
    )
