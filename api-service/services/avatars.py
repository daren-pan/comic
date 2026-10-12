"""用户头像的存取（2026-10-12，个人中心「换头像」）。

存哪：**运行时数据根**下的 `avatar_store/<user_id>.<ext>` —— 与图库（image_store）同级。
为什么不自己推导 `comic_core.paths.DATA_ROOT`：容器里整个 `/data` 是 bind 挂载，
而 `DATA_ROOT` 在容器态指向 bundle 内部（见该文件注释）；真正可靠的是**图库根** ——
env `COMIC_IMAGE_ROOT` 在本地 / 容器两种形态下都指向「两边共享的那块盘」。
故直接取 `IMAGE_ROOT.parent / "avatar_store"`：
    本地   <repo>/crawler-service/data/avatar_store
    容器   /data/avatar_store（bind 到宿主，重新部署不丢）

约定：
- 只接受 **JPG / PNG / WebP / GIF**（按魔数判定，不信任扩展名 —— 复用 `services.images.sniff_image`）；
  **刻意不收 SVG**：SVG 可携带脚本，作为用户内容直出是 XSS 面。
- 单文件 ≤ 2MB；一个用户同时只保留一个文件（换格式时先清旧的）。
- 输出走 `GET /api/avatars/{id}`（`routers/public.py`），`no-cache + ETag`：
  换头像后 URL 不变，必须每次向服务端复核（命中 304 才省流量）。
"""
from __future__ import annotations

from services.images import IMAGE_ROOT, ImagePayload, sniff_image

#: 头像目录（与图库同级；见模块头）
AVATAR_ROOT = IMAGE_ROOT.parent / "avatar_store"

#: 单文件上限
MAX_AVATAR_BYTES = 2 * 1024 * 1024

#: 允许的格式（MIME → 落盘扩展名）
_ALLOWED: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _uid(user_id) -> int | None:
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def save_avatar(user_id, data: bytes) -> str:
    """校验并落盘头像，返回可写库的 URL；校验不过抛 `ValueError`（路由转 400）。"""
    if len(data) > MAX_AVATAR_BYTES:
        raise ValueError("图片不能超过 2MB")
    mime = sniff_image(data)
    ext = _ALLOWED.get(mime or "")
    if not ext:
        raise ValueError("只支持 JPG / PNG / WebP / GIF 图片")
    uid = _uid(user_id)
    if uid is None:
        raise ValueError("无效的用户")
    AVATAR_ROOT.mkdir(parents=True, exist_ok=True)
    clear_avatar(uid)  # 先清旧文件（换格式时去掉别的扩展名）
    (AVATAR_ROOT / f"{uid}.{ext}").write_bytes(data)
    return f"/api/avatars/{uid}"


def clear_avatar(user_id) -> bool:
    """删除该用户的所有头像文件；返回是否删到了东西。"""
    uid = _uid(user_id)
    if uid is None:
        return False
    hit = False
    for p in AVATAR_ROOT.glob(f"{uid}.*"):
        try:
            p.unlink()
            hit = True
        except OSError:
            pass
    return hit


def read_avatar(user_id: int) -> ImagePayload | None:
    """读头像字节（带 ETag）；没有 / 不是图片 → None。"""
    uid = _uid(user_id)
    if uid is None:
        return None
    for p in sorted(AVATAR_ROOT.glob(f"{uid}.*")):
        if not p.is_file():
            continue
        data = p.read_bytes()
        mime = sniff_image(data)
        if not mime:
            continue
        stat = p.stat()
        etag = f'"{int(stat.st_mtime)}-{stat.st_size}"'
        return ImagePayload(
            data=data,
            mime=mime,
            headers={"Cache-Control": "no-cache", "ETag": etag},
            etag=etag,
        )
    return None
