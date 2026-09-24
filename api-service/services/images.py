"""图片读取、占位图生成，以及**图片响应的取数决策**。

- 读取端：已转存的真实文件优先，按**魔数**判定类型（不信任扩展名）；
  读不到则回退生成 SVG 占位图（与前端视觉一致），保证页面不出现裂图。
- 写入端：`admin_image_store()` 给懒转存用，**与读取端同源**（同一图库根）。
- 决策端：`resolve_cover_image()` / `resolve_page_image()` 把「封面 / 正文图该返回什么」
  算成与框架无关的 `ImagePayload`（字节 + MIME + 缓存头 + 可选 ETag）。

⚠️ **为什么决策也在这里**（2026-09-24 调整）：正文图是**三级兜底**（本地图库 → 源站
穿透 → SVG 占位图，**顺序不能变**），三级各自还带不同的缓存语义 —— 这套规则原先散在
`routers/public.py` 的路由函数里，与 HTTP 层混在一起。下沉到这里后，路由只负责把
`ImagePayload` 拼成 `Response`（含 `If-None-Match` → 304 的 HTTP 语义），**不 import
FastAPI 的响应类型**，因此本模块仍是纯逻辑、可直接单测。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core import bootstrap  # noqa: F401  —— 先完成 sys.path 引导（使 comic_crawler 可导入）

_IMG_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # 简化：WEBP 以 RIFF 开头
]

#: 封面可以被「管理台 · 封面自愈（force=True）」换掉，所以只给 1 小时 ——
#: 换图后最多 1 小时全站生效；1 小时内的重复请求由 ETag 条件请求兜住（304 空体，不重传）。
COVER_MAX_AGE = 3600
#: 正文页按 `(comic, chapter, page)` 落盘后内容即固定 → 7 天长缓存。两条命中路径的
#: 缓存语义略有差别（都够用）：**本地命中**带 ETag（过期后条件请求换 304，不重传）；
#: **穿透命中**直接给 `immutable`（字节就在手上，不值得为它多读一次刚写好的文件去算 ETag）。
PAGE_MAX_AGE = 7 * 24 * 3600
#: 占位图 = 临时兜底（源站没取到），**绝不能缓存**：否则源站恢复了用户还看旧图。
NO_STORE: dict[str, str] = {"Cache-Control": "no-store"}


@dataclass(frozen=True)
class ImagePayload:
    """与框架无关的图片响应载荷（由路由层拼成 `Response`）。"""

    data: bytes
    mime: str
    headers: dict[str, str]
    #: 仅**本地命中**才有；有它路由层才能做 `If-None-Match` → 304 的条件请求。
    etag: str | None = None


def sniff_image(data: bytes) -> str | None:
    """按**魔数**判断图片 MIME（不信任扩展名）；不是已知图片格式返回 None。

    读本地文件与「穿透取图」从源站拿回的字节都走这里判型 —— 源站扩展名常与
    实际格式不符（如 weebcentral 的 `.png` 实为 JPEG）。
    """
    for magic, mime in _IMG_MAGIC:
        if data.startswith(magic):
            return mime
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or head.startswith(b"<?xml"):
        return "image/svg+xml"
    return None


def resolve_image_root() -> Path:
    """定位图库根目录 —— 直接采用采集器的**唯一真源** `default_store_root()`。

    ⚠️ **刻意保持"零兜底"**，下面两件事都不做：

    1. **不做 `is_dir()` 判断**：图库根尚未创建（首次部署、首次转存之前）也必须返回它，
       写入端 `LocalImageStore` 会 `mkdir` 出来，读取端按约定去同一处找。
    2. **不做 import 失败的兜底**：`comic_crawler`（经其对外契约面 `facade`）是 api-service 的硬依赖，import 失败
       必须在**进程启动时立即暴露**，绝不能静默退到另一个目录。历史事故（DB 有
       `oss_url`、文件也落了盘、接口却只返回 SVG 占位图）根因就是"两端各自解析、
       结果不一致"；若在这里 `except → APP_DIR/image_store`，读端就会悄悄退回
       `api-service/image_store`（那个已被废弃的目录），把同一个坑原样接回来。

    env `COMIC_IMAGE_ROOT` 的优先级由 `default_store_root()` 统一处理，此处不重复实现。
    """
    from comic_core.images.store import default_store_root

    return default_store_root().resolve()


IMAGE_ROOT = resolve_image_root()


def read_image_file(candidate: str) -> tuple[bytes, str, str] | None:
    """从本地路径、file:// URI 或图库内相对 key 读图片字节；仅接受真正的图片内容。

    返回 `(字节, MIME, ETag)`，读不到 / 不是图片时返回 `None`。

    **ETag 由「文件 mtime + 大小」构成**（不哈希内容）：图库里的图按
    `comic/chapter/page` 落盘后内容即固定，换内容必然改 mtime —— 用它做条件请求
    （命中 `If-None-Match` 直接 304 空体）比每次重传整张图便宜得多，
    也顺带让「管理台强制刷新封面」在浏览器侧最多存活一个 max-age 周期。
    """
    if not candidate:
        return None
    p = candidate
    if p.startswith("file://"):
        p = p[len("file://"):]
        if os.name == "nt" and p.startswith("/") and len(p) > 2 and p[2] == ":":
            p = p[1:]
    elif not p.startswith(("http://", "https://")) and not os.path.isabs(p):
        # 图库内相对 key（如 covers/26.jpg、comic/26/34/001.jpg）：按图库根拼接
        p = str(IMAGE_ROOT / p.lstrip("/"))
    path = Path(p)
    if not path.is_file():
        return None
    data = path.read_bytes()
    mime = sniff_image(data)          # 与「穿透取图」共用同一套魔数判定
    if not mime:
        return None
    stat = path.stat()
    return (data, mime, f'"{int(stat.st_mtime)}-{stat.st_size}"')


def admin_image_store():
    """懒转存落盘位置：直接复用读取端 `IMAGE_ROOT`，保证写入与读取同源。

    `IMAGE_ROOT` 恒为绝对路径（`resolve_image_root()` 零兜底），故无需再判断 None。
    """
    from comic_core.images.store import LocalImageStore

    return LocalImageStore(root=IMAGE_ROOT)


def _cache_headers(max_age: int, etag: str) -> dict[str, str]:
    """图库命中时的缓存头：可长缓存 + ETag（供条件请求）。"""
    return {"Cache-Control": f"public, max-age={max_age}", "ETag": etag}


def resolve_cover_image(row: dict) -> ImagePayload:
    """封面：图库命中 → 带 ETag 的长缓存；否则 → SVG 占位图（`no-store`）。"""
    img = read_image_file(row.get("cover_url") or "")
    if img:
        data, mime, etag = img
        return ImagePayload(data, mime, _cache_headers(COVER_MAX_AGE, etag), etag)
    svg = make_cover_svg(row["title"], row["author"])
    return ImagePayload(svg.encode("utf-8"), "image/svg+xml", dict(NO_STORE))


def resolve_page_image(row: dict, page_no: int) -> ImagePayload:
    """正文图**三级兜底**（顺序不能变）：本地图库 → 源站穿透 → SVG 占位图。

    `row` 是 `db.get_page_context(chapter_id, page_no)` 的结果 —— 源 URL / 已转存 key /
    作品与章节标题 / 本章总页数都在里面，三级各自需要的东西一个不缺（故这里不再查库）。
    """
    # 1) 本地图库命中（已转存的文件 / 图库内相对 key）—— 最快路径
    img = read_image_file(row.get("oss_url") or "") or read_image_file(row.get("source_url") or "")
    if img:
        data, mime, etag = img
        return ImagePayload(data, mime, _cache_headers(PAGE_MAX_AGE, etag), etag)

    # 2) 穿透取图：本地没有 → 现场从源站取**这一张**，顺手落盘（下次访问走本地）。
    #    用户等待 = 源站响应一张图的时间，而不是「整话下载完」；签名过期会自动重签。
    #    并发闸门 / 同图去重 / 失败负缓存都在 crawler 侧（见 images/transfer.py）。
    #    ⚠️ 延迟导入：`services.ondemand` 在模块级 import 本模块，这里若模块级反向 import 会成环。
    from services.ondemand import fetch_page_online

    data = fetch_page_online(int(row["chapter_id"]), page_no, row=row)
    if data:
        return ImagePayload(
            data,
            sniff_image(data) or "image/jpeg",
            {"Cache-Control": f"public, max-age={PAGE_MAX_AGE}, immutable"},
        )

    # 3) 兜底：源站也取不到 → 占位图（保证不裂图），状态保持「未转存」待下次重试
    svg = make_page_svg(
        row.get("comic_title") or "漫画",
        row.get("chapter_title") or "",
        page_no,
        int(row.get("total_pages") or 0) or page_no,
    )
    return ImagePayload(svg.encode("utf-8"), "image/svg+xml", dict(NO_STORE))


def _hue(seed: str) -> int:
    h = 0
    for ch in seed:
        h = (h * 31 + ord(ch)) % 360
    return h


def make_cover_svg(title: str, author: str) -> str:
    hue = _hue(title)
    hue2 = (hue + 40) % 360
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400" viewBox="0 0 300 400">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="hsl({hue},72%,46%)"/><stop offset="1" stop-color="hsl({hue2},70%,30%)"/>
</linearGradient></defs>
<rect width="300" height="400" fill="url(#g)"/>
<circle cx="230" cy="80" r="70" fill="hsl({hue2},70%,60%)" opacity="0.35"/>
<circle cx="60" cy="330" r="90" fill="hsl({hue},80%,70%)" opacity="0.25"/>
<rect x="24" y="290" width="252" height="4" rx="2" fill="#fff" opacity="0.7"/>
<text x="150" y="340" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="30" font-weight="bold" fill="#fff">{title}</text>
<text x="150" y="372" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="14" fill="#ffe9e0" opacity="0.9">{author}</text>
</svg>'''


def make_page_svg(comic_title: str, chapter_title: str, page_no: int, total: int) -> str:
    hue = (_hue(comic_title) + page_no * 12) % 360
    panel = f"hsl({(hue + 20) % 360},30%,82%)"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1020" viewBox="0 0 720 1020">
<rect width="720" height="1020" fill="hsl({hue},22%,94%)"/>
<rect x="36" y="40" width="648" height="420" rx="8" fill="{panel}" stroke="hsl({hue},40%,55%)" stroke-width="4"/>
<rect x="60" y="64" width="200" height="260" rx="6" fill="hsl({(hue + 60) % 360},45%,78%)"/>
<rect x="288" y="64" width="372" height="160" rx="6" fill="hsl({(hue + 120) % 360},45%,80%)"/>
<rect x="288" y="240" width="372" height="84" rx="6" fill="hsl({(hue + 180) % 360},45%,76%)"/>
<rect x="36" y="486" width="648" height="250" rx="8" fill="{panel}" stroke="hsl({hue},40%,55%)" stroke-width="4"/>
<circle cx="500" cy="600" r="70" fill="hsl({(hue + 90) % 360},55%,70%)" opacity="0.8"/>
<rect x="60" y="560" width="180" height="120" rx="6" fill="hsl({(hue + 150) % 360},45%,80%)"/>
<rect x="36" y="762" width="648" height="190" rx="8" fill="{panel}" stroke="hsl({hue},40%,55%)" stroke-width="4"/>
<text x="360" y="900" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="26" fill="hsl({hue},50%,35%)">{page_no} / {total}</text>
<text x="360" y="970" text-anchor="middle" font-family="'Microsoft YaHei',sans-serif" font-size="15" fill="#888">{chapter_title} · 第 {page_no} 页（占位图）</text>
</svg>'''
