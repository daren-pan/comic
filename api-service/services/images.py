"""图片读取与占位图生成。

- 读取端：已转存的真实文件优先，按**魔数**判定类型（不信任扩展名）；
  读不到则回退生成 SVG 占位图（与前端视觉一致），保证页面不出现裂图。
- 写入端：`admin_image_store()` 给懒转存用，**与读取端同源**（同一图库根）。
"""
from __future__ import annotations

import os
from pathlib import Path

from core import config  # noqa: F401  —— 先完成 sys.path 引导（使 comic_crawler 可导入）

_IMG_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # 简化：WEBP 以 RIFF 开头
]


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
    2. **不做 import 失败的兜底**：`comic_crawler` 是 api-service 的硬依赖，import 失败
       必须在**进程启动时立即暴露**，绝不能静默退到另一个目录。历史事故（DB 有
       `oss_url`、文件也落了盘、接口却只返回 SVG 占位图）根因就是"两端各自解析、
       结果不一致"；若在这里 `except → APP_DIR/image_store`，读端就会悄悄退回
       `api-service/image_store`（那个已被废弃的目录），把同一个坑原样接回来。

    env `COMIC_IMAGE_ROOT` 的优先级由 `default_store_root()` 统一处理，此处不重复实现。
    """
    from comic_crawler.images.store import default_store_root

    return default_store_root().resolve()


IMAGE_ROOT = resolve_image_root()


def read_image_file(candidate: str) -> tuple[bytes, str] | None:
    """从本地路径、file:// URI 或图库内相对 key 读图片字节；仅接受真正的图片内容。"""
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
    return (data, mime) if mime else None


def admin_image_store():
    """懒转存落盘位置：直接复用读取端 `IMAGE_ROOT`，保证写入与读取同源。

    `IMAGE_ROOT` 恒为绝对路径（`resolve_image_root()` 零兜底），故无需再判断 None。
    """
    from comic_crawler.images.store import LocalImageStore

    return LocalImageStore(root=IMAGE_ROOT)


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
