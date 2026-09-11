"""图片存储抽象（契约）+ 本地文件系统实现。

对应架构方案 §3.3「图片资源（OSS + CDN）」与 §6.1「存储抽象」：
- 二进制不落 MySQL，全部走对象存储；
- 统一 `ImageStore` 接口 —— OSS / COS / MinIO / 本地目录可随时替换（扩展点）；
- `LocalImageStore` 用文件系统模拟 OSS（file:// URL），本地离线跑通全链路。

⚠️ 图库根只此一处定义（`default_store_root()`）：写入端与读取端必须同源。
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..paths import IMAGE_STORE_ROOT

logger = logging.getLogger(__name__)


# env `COMIC_IMAGE_ROOT` 的哨兵值：这类值语义是「不设置」，绝不能当成目录名。
# （历史上 `COMIC_IMAGE_ROOT=none` 直接造出了一个 `./none/` 垃圾目录）
_ENV_SENTINELS = {"none", "null", "false", "true", "0", "-", "off", "no"}


def _env_store_root() -> Path | None:
    """读取并**校验** env `COMIC_IMAGE_ROOT`；不合法则告警并按"未设置"处理。

    三条硬约束：
    - 空串 / 哨兵值（none、false、0 …）→ 视为未设置；
    - **必须是绝对路径** —— 相对路径会随进程 cwd 漂移（写端在 crawler-service/、
      读端在 api-service/ 时会各自解析出不同目录，正是"文件落了盘、接口却只返回
      占位图"那类事故的根因）；
    - 其余情况才采用。
    """
    raw = os.environ.get("COMIC_IMAGE_ROOT")
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if value.lower() in _ENV_SENTINELS:
        logger.warning(
            "COMIC_IMAGE_ROOT=%r 是哨兵值（非目录名），已忽略，改用默认图库根", raw
        )
        return None
    path = Path(value)
    if not path.is_absolute():
        logger.warning(
            "COMIC_IMAGE_ROOT=%r 不是绝对路径（会随进程 cwd 漂移），已忽略，改用默认图库根 %s",
            raw,
            IMAGE_STORE_ROOT,
        )
        return None
    return path


def default_store_root() -> Path:
    """图库根目录的**唯一真源**（写入端与读取端必须一致）。

    优先级：env `COMIC_IMAGE_ROOT`（**必须是绝对路径、且非哨兵值**）> `paths.IMAGE_STORE_ROOT`
    （服务根下 image_store）。env 值不合法时**告警并回落默认根**，见 `_env_store_root()`。

    刻意**不**提供「相对进程 cwd 的 image_store」兜底：那种解析会随启动目录漂移
    —— api-service 里以 cwd=api-service 起 uvicorn 时，封面被写到 api-service/image_store，
    而转存走显式 root 写到 crawler-service/image_store，读取端又只认其中一个，
    于是 DB 里 oss_url 有值、文件也确实落了盘，接口却读不到、只能返回占位图。
    """
    env_root = _env_store_root()
    return env_root if env_root is not None else IMAGE_STORE_ROOT


class ImageStore(ABC):
    """对象存储统一接口。"""

    @abstractmethod
    def put(self, key: str, data: bytes) -> str:
        """上传对象，返回可访问 URL。"""

    @abstractmethod
    def get(self, key: str) -> bytes | None:
        """读取对象内容（巡检/校验用）。"""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """判断对象是否存在。"""

    @abstractmethod
    def delete(self, key: str) -> None:
        """删除对象。"""


class LocalImageStore(ImageStore):
    """本地文件系统模拟 OSS。key 即相对路径，URL 为 file:// 形式。"""

    def __init__(self, root: str | Path | None = None) -> None:
        # 不传 root 时用统一真源，避免随进程 cwd 漂移到别的 image_store
        if root is None:
            self.root = default_store_root()
        else:
            # 显式传入也要求绝对路径：相对路径会随 cwd 漂移（曾造出 ./none/ 这类垃圾目录）。
            # 不直接抛错（CLI --store 传相对路径是常见手滑），但**按调用时 cwd 固化为绝对路径**
            # 并告警，确保后续写入位置明确、可追溯。
            resolved = Path(root)
            if not resolved.is_absolute():
                resolved = resolved.resolve()
                logger.warning("图库根 %r 是相对路径，已按当前工作目录解析为 %s", root, resolved)
            self.root = resolved
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # 兼容 file:// URI（巡检时传入 oss_url）与相对 key（写入时）
        if key.startswith("file://"):
            path_str = unquote(urlparse(key).path)
            # Windows: file:///D:/... 的 path 为 /D:/...，去掉多余前导斜杠
            if os.name == "nt" and path_str.startswith("/") and len(path_str) > 2 and path_str[2] == ":":
                path_str = path_str[1:]
            return Path(path_str)
        # 防目录穿越：只允许相对路径
        p = self.root / key.lstrip("/")
        p.resolve().relative_to(self.root.resolve())
        return p

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        # Windows 下相对路径无法 as_uri，先 resolve 为绝对路径
        return path.resolve().as_uri()

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.exists() else None

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()
