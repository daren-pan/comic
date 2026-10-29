"""服务入口：`python -m comic_chat`（容器里的 CMD 也是它）。

## 为什么 host 默认 0.0.0.0

容器内必须监听所有网卡，否则同网络的 `comic-api` 连不上（只监听 127.0.0.1 时，
健康检查从容器内部能通、从别的容器不通 —— 这种"看起来正常"的故障最难查）。

⚠️ 监听 0.0.0.0 **不等于对外暴露**：compose 里本服务没有 `ports:` 映射，
宿主和公网都访问不到，只有同一 `backend` 网络的容器能连。

本地开发想只给自己用时，设 `COMIC_CHAT_HOST=127.0.0.1`。
"""
from __future__ import annotations

import logging
import os

import uvicorn

from . import __version__


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.environ.get("COMIC_CHAT_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.environ.get("COMIC_CHAT_PORT", "8001"))
    logging.getLogger("comic.chat").info(
        "comic-chat %s 启动 → http://%s:%d", __version__, host, port
    )
    uvicorn.run("comic_chat.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
