"""图片懒转存服务。

对应架构方案 §2.2「图片转存：懒触发 + 热点预取」与 §3.3：
- 不预抓全量图片：同步入库时 page.cached_status = '未转存'，只存源站 URL；
- 用户访问某章节时（或定时巡检时）触发 lazy_transfer，按需转存到 OSS；
- 转存成功 → 回填 oss_url、状态置 '已转存'；失败重试，仍失败置 '失效'。

下载器说明：
- 真实源站：source_url 为 http(s)，走 httpx 下载；
- 演示/离线：source_url 为占位路径，download_stub 返回占位字节，
  同样能验证「状态机迁移 + OSS 写入 + 巡检恢复」的完整链路。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import httpx

from .image_store import ImageStore
from .storage import Storage

logger = logging.getLogger(__name__)


def build_image_key(comic_id: int, chapter_id: int, page_no: int) -> str:
    """OSS 对象键：comic/<comic_id>/<chapter_id>/<page_no>（架构方案 §3.3 分目录）。"""
    return f"comic/{comic_id}/{chapter_id}/{page_no:03d}.jpg"


def default_downloader(source_url: str, key: str) -> bytes:
    """下载源站图片字节。http(s) 走网络；其他路径返回占位字节（离线演示）。"""
    if source_url.startswith(("http://", "https://")):
        resp = httpx.get(source_url, timeout=10.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    # 离线演示占位：内容含 key，便于在巡检中验证「对象内容与 key 一致」
    return b"FAKE-IMAGE:" + key.encode("utf-8")


def ensure_cover_local(
    storage: Storage, image_store: ImageStore, comic_id: int, cover_url: str
) -> bool:
    """外链封面落盘为图库内相对 key（covers/{comic_id}.jpg）。

    - 已是本地 key / 占位路径 / 空 → 跳过（True）；
    - http(s) 外链 → 下载写图库并回填相对 key（幂等，每轮同步自愈）；
    - 下载失败 → 保留外链，记录告警返回 False，下次同步重试。
    与 lazy_transfer 同一约定：DB 只存图库内相对 key，与机器/项目路径解耦。
    """
    if not cover_url or not cover_url.startswith(("http://", "https://")):
        return True
    key = f"covers/{comic_id}.jpg"
    try:
        resp = httpx.get(cover_url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
        data = resp.content
        if not data:
            return False
        image_store.put(key, data)
        storage.set_comic_cover(comic_id, key)
        logger.info("封面落盘 comic_id=%s -> %s (%dB)", comic_id, key, len(data))
        return True
    except Exception as exc:
        logger.warning("封面落盘失败 comic_id=%s %s: %s", comic_id, cover_url, exc)
        return False


def lazy_transfer(
    storage: Storage,
    image_store: ImageStore,
    downloader: Callable[[str, str], bytes] | None = None,
    limit: int = 200,
) -> dict[str, int]:
    """转存所有「未转存」页，返回统计。可被阅读服务在用户访问时调用（限流参数可选）。"""
    downloader = downloader or default_downloader
    stats = {"checked": 0, "transferred": 0, "failed": 0}

    rows = storage.list_uncached_pages(limit=limit)
    for row in rows:
        stats["checked"] += 1
        key = build_image_key(row["comic_id"], row["chapter_id"], row["page_no"])
        try:
            data = downloader(row["source_url"], key)
            image_store.put(key, data)  # 上传对象；put 返回的 URL 不落库
            # DB 回填图库内相对 key（OSS 对象键语义），与机器/项目路径解耦，
            # 读取端（api-service）按运行时定位的图库根拼接。
            storage.mark_page_cached(row["page_id"], key)
            stats["transferred"] += 1
        except Exception as exc:
            stats["failed"] += 1
            logger.warning(
                "转存失败 page_id=%s source=%s: %s", row["page_id"], row["source_url"], exc
            )

    logger.info("懒转存完成: %s", stats)
    return stats


def transfer_latest_first_page(
    storage: Storage,
    image_store: ImageStore,
    comic_id: int,
    latest_chapter_id: int,
    downloader: Callable[[str, str], bytes] | None = None,
) -> bool:
    """采集入库后自动转存「最新一话的第 1 页」图片。

    用于通量验证：入库时不下载全部分页图（慢、易被源站限流），只把
    每部漫画最新一章的第 1 页转存到图库、回填 oss_url 标记已转存，
    其余页面保持「未转存」（访问时显示占位符）。

    参数:
        latest_chapter_id: 最新一话的章节 id（DB 内 id，须先 upsert_pages 入库）

    返回:
        True 表示成功转存；False 表示无页可转 / 下载失败。
    """
    rows = storage.get_pages(latest_chapter_id)
    if not rows:
        return False
    first = rows[0]  # get_pages 按 page_no ASC，第 1 页在最前，且带 page_id
    page_id, page_no = int(first["page_id"]), int(first["page_no"])
    key = build_image_key(comic_id, latest_chapter_id, page_no)
    downloader = downloader or default_downloader
    try:
        data = downloader(str(first["source_url"]), key)
        image_store.put(key, data)
        storage.mark_page_cached(page_id, key)
        logger.info(
            "自动转存最新章第1页 comic_id=%s chapter_id=%s page_no=%s -> %s (%dB)",
            comic_id, latest_chapter_id, page_no, key, len(data),
        )
        return True
    except Exception as exc:
        logger.warning(
            "自动转存最新章第1页失败 comic_id=%s chapter_id=%s page_no=%s: %s",
            comic_id, latest_chapter_id, page_no, exc,
        )
        return False
