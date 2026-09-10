"""图片存储抽象：OSS 统一接口 + 本地模拟实现。

对应架构方案 §3.3「图片资源（OSS + CDN）」与 §6.1「存储抽象」：
- 二进制不落 MySQL，全部走对象存储；
- 统一 ImageStore 接口，OSS / COS / MinIO / 本地目录可随时替换；
- LocalImageStore 用文件系统模拟 OSS（file:// URL），本地离线可跑通全链路。
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


def default_store_root() -> Path:
    """图库根目录的**唯一真源**（写入端与读取端必须一致）。

    优先级：env COMIC_IMAGE_ROOT > 本包所在仓库根下 image_store。

    刻意**不**提供「相对进程 cwd 的 image_store」兜底：那种解析会随启动目录漂移
    —— api-service 里以 cwd=api-service 起 uvicorn 时，封面被写到 api-service/image_store，
    而转存走显式 root 写到 crawler-service/image_store，读取端又只认其中一个，
    于是 DB 里 oss_url 有值、文件也确实落了盘，接口却读不到、只能返回占位图。
    """
    env = os.environ.get("COMIC_IMAGE_ROOT")
    if env:
        return Path(env)
    # image_store.py 位于 <repo>/crawler-service/src/comic_crawler/ 或 <repo>/comic-deploy/comic_crawler/
    # 向上两级即仓库根（crawler-service / comic-deploy），image_store 在其下。
    return Path(__file__).resolve().parents[2] / "image_store"


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
        self.root = Path(root) if root is not None else default_store_root()
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
