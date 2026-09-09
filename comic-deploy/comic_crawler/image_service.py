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
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import httpx

from .image_store import ImageStore
from .storage import Storage

logger = logging.getLogger(__name__)

# 共享 httpx.Client：keep-alive 复用连接，避免每张图都重建 TCP/TLS 握手
# （曾实测：新建连接下载 ~6s/张，复用连接 ~2s/张；无并发，天然贴合源站低频约定）
_client: httpx.Client | None = None

# 懒转存并发路数（默认 2）：境外图床（如 MangaDex）单张耗时长，适度并发解耦网络 IO，
# 同时对源站保持低频合规（MangaDex AUP 约 5 req/s，2 路远低于该值）。
CONCURRENCY = 2


def _shared_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30.0, follow_redirects=True)
    return _client


def build_image_key(comic_id: int, chapter_id: int, page_no: int) -> str:
    """OSS 对象键：comic/<comic_id>/<chapter_id>/<page_no>（架构方案 §3.3 分目录）。"""
    return f"comic/{comic_id}/{chapter_id}/{page_no:03d}.jpg"


def default_downloader(source_url: str, key: str) -> bytes:
    """下载源站图片字节。http(s) 走网络；其他路径返回占位字节（离线演示）。"""
    if source_url.startswith(("http://", "https://")):
        resp = _shared_client().get(source_url)
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


def _url_expired(source_url: str, now: float | None = None) -> bool:
    """本地判断签名 URL 是否已过期：解析 query 里的 t 参数（过期时间戳）。

    无 t 参数（永久有效，如 pepper）或 t 在未来 → False（可直接下载）；
    t 已过 → True（必然 403，应现场重拉）。纯本地解析，零网络开销。
    """
    if not source_url:
        return True
    m = re.search(r"[?&]t=(\d+)", source_url)
    if not m:
        return False
    try:
        expires = float(m.group(1))
    except ValueError:
        return False
    return expires < (time.time() if now is None else now)


def lazy_transfer(
    storage: Storage,
    image_store: ImageStore,
    downloader: Callable[[str, str], bytes] | None = None,
    limit: int = 200,
    adapter_provider: Callable[[str], object] | None = None,
    since=None,
    until=None,
    source=None,
) -> dict[str, int]:
    """转存「未转存」页到图片存储，返回统计。

    下载策略（解决签名时效源 URL 过期问题）：
    1. 本地解析 source_url 的 t：已过期 → 跳过直接下载，走现场重拉；
    2. 未过期 → 直接下载；失败（403/网络）→ 同样走现场重拉兜底；
    3. 重拉：调用 adapter_provider(source) 拿适配器实例，经
       CrawlerAdapter.fetch_source_page_urls 让源站重新签发整章 URL，
       再按 page_no 取新地址下载（对无签名源适配器默认不支持，直接失败记日志）。

    参数:
        adapter_provider: 按源名返回适配器实例的可调用对象（懒转存重拉用）；
            为 None 时不具备重拉能力（旧 URL 过期则转存失败）。
        since/until: 只转存该时间范围内入库的页（按章节 sync_time 过滤），
            用于「增量采集后只转存本次增量新收的页」；None 表示不限制。
        source: 只转存指定数据源的页（如 'zaimanhua'）；None 表示不限制。
    """
    downloader = downloader or default_downloader
    stats = {"checked": 0, "transferred": 0, "failed": 0}
    ad_cache: dict[str, object] = {}  # source -> 适配器实例（None 表示创建失败/不支持）

    def _adapter(source: str) -> object | None:
        if source not in ad_cache:
            try:
                ad_cache[source] = adapter_provider(source) if adapter_provider else None
            except Exception:
                ad_cache[source] = None
        return ad_cache[source]

    def _fresh_url(ad: object, row: dict) -> str | None:
        """现场重拉整章 URL 后按 page_no 取新地址。"""
        fn = getattr(ad, "fetch_source_page_urls", None)
        if fn is None:
            return None
        try:
            urls = fn(row.get("source_comic_id"), row.get("source_chapter_id"))
        except Exception as exc:
            logger.warning("重拉章节 URL 失败 source=%s: %s", row.get("source"), exc)
            return None
        if not urls:
            return None
        try:
            no = int(row["page_no"])
        except (TypeError, ValueError):
            no = 1
        return urls[no - 1] if 1 <= no <= len(urls) else None

    def _try_download(url: str | None, key: str) -> bytes | None:
        if not url:
            return None
        try:
            return downloader(url, key)
        except Exception:
            return None

    def _transfer_one(row: dict) -> str:
        """处理单张页：判断过期 -> 下载（必要时现场重拉）-> 写图库/回填状态。

        返回 'ok'/'fail'。并发安全：MySQLStorage 每方法独立连接(autocommit)，
        httpx 共享 client 用连接池(线程安全)，put 为独立文件写。
        """
        try:
            stats["checked"] += 1
            key = build_image_key(row["comic_id"], row["chapter_id"], row["page_no"])
            # 1) t 未过期才直接用登记 URL 下载
            data = None if _url_expired(row.get("source_url") or "") else _try_download(row.get("source_url"), key)
            # 2) 过期或下载失败 -> 现场重拉兜底
            if data is None:
                ad = _adapter(str(row.get("source") or ""))
                if ad is not None:
                    data = _try_download(_fresh_url(ad, row), key)
            if data is None:
                stats["failed"] += 1
                logger.warning(
                    "转存失败 page_id=%s source=%s（URL 过期且无法重拉）", row["page_id"], row.get("source")
                )
                return "fail"
            image_store.put(key, data)  # 上传对象；put 返回的 URL 不落库
            # DB 回填图库内相对 key（OSS 对象键语义），与机器/项目路径解耦，
            # 读取端（api-service）按运行时定位的图库根拼接。
            storage.mark_page_cached(row["page_id"], key)
            stats["transferred"] += 1
            return "ok"
        except Exception as exc:
            stats["failed"] += 1
            logger.warning("转存失败 page_id=%s: %s", row["page_id"], exc)
            return "fail"

    rows = storage.list_uncached_pages(limit=limit, since=since, until=until, source=source)
    # 并发转存：默认 CONCURRENCY 路（MangaDex 等境外图床单张耗时长，串行会拖满；
    # 适度并发解耦网络 IO，同时对源站保持低频合规）。
    workers = max(1, int(CONCURRENCY))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_transfer_one, rows))

    logger.info("懒转存完成: %s", stats)
    return stats
