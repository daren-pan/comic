"""图片懒转存服务（业务动作层）。

对应架构方案 §2.2「图片转存：懒触发 + 热点预取」与 §3.3：
- 不预抓全量图片：同步入库时 page.cached_status = '未转存'，只存源站 URL；
- 用户访问某章节时（或定时巡检时）触发 lazy_transfer，按需转存到对象存储；
- 转存成功 → 回填 oss_url、状态置 '已转存'；失败重试，仍失败置 '失效'。

下载器说明：
- 真实源站：source_url 为 http(s)，走 httpx 下载；
- 演示/离线：source_url 为占位路径，default_downloader 返回占位字节，
  同样能验证「状态机迁移 + 对象写入 + 巡检恢复」的完整链路。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx

from ..storage.base import Storage
from .store import ImageStore

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
    """对象键：comic/<comic_id>/<chapter_id>/<page_no>（架构方案 §3.3 分目录）。"""
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

    无 t 参数（永久有效，如 weebcentral）或 t 在未来 → False（可直接下载）；
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


def _fresh_url(adapter: object, row: dict) -> tuple[str | None, str]:
    """现场重拉整章 URL，按 page_no 取出这一页 → `(新地址, 失败原因)`。

    失败原因（供日志直接说明"为什么转不了"）：
    - `该源不支持重拉` / `重拉接口报错（异常类型）` / `重拉返回 0 页（源站侧无内容）`
      / `重拉只返回 N 页，不足第 M 页`。
    注意：**不在本函数里写日志**，由调用方汇总成一行（避免逐页刷屏，见 `lazy_transfer`）。
    """
    fn = getattr(adapter, "fetch_source_page_urls", None)
    if fn is None:
        return None, "该源不支持重拉"
    try:
        urls = fn(row.get("source_comic_id"), row.get("source_chapter_id"))
    except Exception as exc:
        return None, f"重拉接口报错（{type(exc).__name__}: {exc}）"
    if not urls:
        return None, "重拉返回 0 页（源站侧无内容）"
    try:
        no = int(row["page_no"])
    except (TypeError, ValueError):
        no = 1
    if not (1 <= no <= len(urls)):
        return None, f"重拉只返回 {len(urls)} 页，不足第 {no} 页"
    return urls[no - 1], ""


def _endpoint_of(adapter: object | None, row: dict) -> str:
    """重拉时实际调用的源站章节接口路径（适配器可选用 `chapter_api_path` 提供）。

    适配器没提供时返回空串（日志里显示 `-`）—— 不影响功能，只是少一列定位信息。
    """
    fn = getattr(adapter, "chapter_api_path", None)
    if not callable(fn):
        return ""
    try:
        return str(fn(row.get("source_comic_id"), row.get("source_chapter_id")) or "")
    except Exception:
        return ""


def _fail_body(row: dict, adapter: object | None, reason: str, count_label: str) -> str:
    """失败日志正文，固定列序：`源 | 接口 | 漫画 | 章节 | 页数 | 原因`。

    为什么要这么排：原先只写 `page_id=xxx source=xxx`，光看日志**定位不到是哪部作品哪一话**
    —— 出了 99 条失败也说不清影响面。时间由日志格式器统一加（见 api-service/main.py），
    故正文里不重复写时间。
    """
    comic = str(row.get("comic_title") or f"comic#{row.get('comic_id')}")
    chapter = str(row.get("chapter_title") or f"chapter#{row.get('chapter_id')}")
    return " | ".join(
        [
            str(row.get("source") or "?"),
            _endpoint_of(adapter, row) or "-",
            f"《{comic}》",
            chapter,
            count_label,
            reason,
        ]
    )


def _build_adapter(adapter_provider: Callable[[str], object] | None, source: str) -> object | None:
    """按源名取适配器实例；没有 provider 或创建失败则返回 None（退化为"只能直接下载"）。"""
    if not adapter_provider or not source:
        return None
    try:
        return adapter_provider(source)
    except Exception as exc:
        logger.warning("创建适配器失败 source=%s: %s", source, exc)
        return None


def _host_allowed(url: str, adapter: object | None) -> bool:
    """图片域名白名单校验（防止把库里的 URL 当任意请求跳板）。

    适配器未声明 ``image_hosts`` 时不校验（沿用「库内数据可信」的既有约定）；
    声明了的源只允许下载白名单域名，避免重定向/篡改 URL 打到内网地址。

    白名单条目支持两种写法：
    - **精确域名**：``images.zaimanhua.com``；
    - **通配一级子域**：``*.mangafunb.fun`` —— 给**分片图床**用。拷贝漫画的图床是
      ``sa…sz`` + ``s0`` 共 24 个分片域名（同一部作品的封面与正文图同分片），
      分片由作品路径散列得出、集合可能新增，穷举必然漏；故按后缀放行。
      只匹配**恰好一级**子域：``a.b.mangafunb.fun``（多一级）与
      ``evilmangafunb.fun``（没有点分隔）都不放行。
    """
    hosts = getattr(adapter, "image_hosts", None) or set()
    if not hosts:
        return True
    try:
        host = httpx.URL(url).host or ""
    except Exception:
        return False
    if host in hosts:
        return True
    for entry in hosts:
        if entry.startswith("*.") and host.count(".") == entry.count("."):
            if host.endswith(entry[1:]):
                return True
    return False


def fetch_page_bytes(
    storage: Storage,
    image_store: ImageStore,
    row: dict,
    *,
    adapter_provider: Callable[[str], object] | None = None,
    downloader: Callable[[str, str], bytes] | None = None,
) -> bytes | None:
    """读某页时本地还没有图 → 现场从源站取回，**顺手落盘**后再返回（「边看边转」）。

    用户等待时间因此只等于「源站响应一张图」，而不是「整话下载完」：

    - 成功：写入图库 + 回填 `cached_status='已转存'` → 返回字节（下次访问走本地）；
    - 失败：返回 None（调用方回退 SVG 占位图），状态保持「未转存」，下次访问再试。

    下载策略与 `lazy_transfer` 完全一致（复用同一套函数）：登记 URL 未过期就直接用；
    已过期或下载失败 → 现场重拉整章 URL 让源站重新签发 → 再试一次。
    """
    downloader = downloader or default_downloader
    key = build_image_key(row["comic_id"], row["chapter_id"], row["page_no"])
    adapter = _build_adapter(adapter_provider, str(row.get("source") or ""))

    data, reason = _download_one(row.get("source_url"), key, adapter, row, downloader)
    if data is None:
        logger.warning(
            "穿透取图失败 | %s",
            _fail_body(row, adapter, reason, f"第 {row.get('page_no')} 页"),
            extra={"log_fields": {
                "event": "read.fail",
                "source": row.get("source"),
                "comic_id": row.get("comic_id"),
                "comic_title": row.get("comic_title"),
                "chapter_id": row.get("chapter_id"),
                "chapter_title": row.get("chapter_title"),
                "endpoint": _endpoint_of(adapter, row),
                "pages": 1,
                "reason": reason,
            }},
        )
        return None

    try:
        image_store.put(key, data)
        storage.mark_page_cached(row["page_id"], key)
    except Exception as exc:
        # 落盘/回填失败不应影响本次阅读：图片字节照常返回给用户，状态留给下次重试
        logger.warning("穿透取图落盘失败 page_id=%s: %s", row.get("page_id"), exc)
    return data


def _download_one(
    url: str | None,
    key: str,
    adapter: object | None,
    row: dict,
    downloader: Callable[[str, str], bytes],
) -> tuple[bytes | None, str]:
    """单页下载 → `(字节, 失败原因)`（成功时原因为空串）。

    未过期且域名合规 → 直接用登记 URL；失败（多为 403，签名被判失效）或已过期
    → 现场重拉整章让源站重新签发，再试一次。失败原因逐层拼起来交给调用方写日志。
    """
    if not url:
        first = "该页无登记 URL"
    elif _url_expired(url):
        first = "登记 URL 已过期"
    elif not _host_allowed(url, adapter):
        return None, "登记 URL 不在图床白名单内"
    else:
        try:
            return downloader(url, key), ""
        except Exception as exc:  # 落到重拉分支：多为 403
            first = f"登记 URL 下载失败（{type(exc).__name__}: {exc}）"
    if adapter is None:
        return None, f"{first}；且无重拉能力（适配器不可用）"
    fresh, why = _fresh_url(adapter, row)
    if not fresh:
        return None, f"{first}；{why}"
    if not _host_allowed(fresh, adapter):
        return None, f"{first}；重拉地址不在图床白名单内"
    try:
        return downloader(fresh, key), ""
    except Exception as exc:
        return None, f"重拉后下载仍失败（{type(exc).__name__}: {exc}）"


def lazy_transfer(
    storage: Storage,
    image_store: ImageStore,
    downloader: Callable[[str, str], bytes] | None = None,
    limit: int | None = None,
    adapter_provider: Callable[[str], object] | None = None,
    since=None,
    until=None,
    source=None,
) -> dict[str, int]:
    """转存「未转存」页到图片存储，返回统计。

    转存语义：**把 since/until/source 所选范围内的所有未转存页都转掉**，
    `limit` 只是可选的兜底阀门（None/<=0 = 不限制）。

    下载策略（解决签名时效源 URL 过期问题）：
    1. 本地解析 source_url 的 t：已过期 → 跳过直接下载，走现场重拉；
    2. 未过期 → 直接下载；失败（403/网络）→ 同样走现场重拉兜底；
    3. 重拉：调用 adapter_provider(source) 拿适配器实例，经
       CrawlerAdapter.fetch_source_page_urls 让源站重新签发整章 URL，
       再按 page_no 取新地址下载（对无签名源适配器默认不支持，直接失败记日志）。

    参数:
        limit: 本次最多转存页数；None 或 <=0 表示不限制（范围内全部未转存页）。
        adapter_provider: 按源名返回适配器实例的可调用对象（懒转存重拉用）；
            为 None 时不具备重拉能力（旧 URL 过期则转存失败）。
        since/until: 只转存该时间范围内入库的页（按章节 `sync_time` 过滤），
            用于「增量采集后只转存本次增量新收的页」；None 表示不限制。
            **边界双端含**：`until` 只给日期时含当天全天。
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

    # 失败明细**按「源 / 作品 / 章节 / 原因」聚合**后再写日志：一话失败往往是整话几十页
    # 一起失败（同一原因），逐页刷屏的话 99 条里看不出是哪部作品哪一话。
    fails: dict[tuple, dict] = {}
    lock = threading.Lock()

    def _record_fail(row: dict, adapter: object | None, reason: str) -> None:
        key = (
            str(row.get("source") or ""),
            str(row.get("comic_id")),
            str(row.get("chapter_id")),
            reason,
        )
        no = row.get("page_no") or 0
        with lock:
            rec = fails.get(key)
            if rec is None:
                fails[key] = {
                    "row": row, "adapter": adapter, "reason": reason,
                    "pages": 1, "min_no": no, "max_no": no,
                }
                return
            rec["pages"] += 1
            rec["min_no"] = min(rec["min_no"], no)
            rec["max_no"] = max(rec["max_no"], no)

    def _transfer_one(row: dict) -> str:
        """处理单张页：判断过期 -> 下载（必要时现场重拉）-> 写图库/回填状态。

        返回 'ok'/'fail'。并发安全：MySQLStorage 每方法独立连接(autocommit)，
        httpx 共享 client 用连接池(线程安全)，put 为独立文件写。
        """
        try:
            stats["checked"] += 1
            key = build_image_key(row["comic_id"], row["chapter_id"], row["page_no"])
            ad = _adapter(str(row.get("source") or ""))
            data, reason = _download_one(row.get("source_url"), key, ad, row, downloader)
            if data is None:
                stats["failed"] += 1
                _record_fail(row, ad, reason)
                return "fail"
            image_store.put(key, data)  # 上传对象；put 返回的 URL 不落库
            # DB 回填图库内相对 key（对象键语义），与机器/项目路径解耦，
            # 读取端（api-service）按运行时定位的图库根拼接。
            storage.mark_page_cached(row["page_id"], key)
            stats["transferred"] += 1
            return "ok"
        except Exception as exc:
            stats["failed"] += 1
            _record_fail(row, None, f"处理异常（{type(exc).__name__}: {exc}）")
            return "fail"

    rows = storage.list_uncached_pages(limit=limit, since=since, until=until, source=source)
    # 并发转存：默认 CONCURRENCY 路（MangaDex 等境外图床单张耗时长，串行会拖满；
    # 适度并发解耦网络 IO，同时对源站保持低频合规）。
    workers = max(1, int(CONCURRENCY))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_transfer_one, rows))

    # 失败明细：每次运行**每章每原因各一行**（不再逐页刷屏）
    # 同时带上结构化字段（extra）—— 落进 log_record 表后，管理台能按
    # 作品 / 章节 / 源站 / 原因 直接筛，而不是让人拿关键字去 message 里捞。
    for rec in fails.values():
        row = rec["row"]
        span = (
            f"{rec['pages']} 页（第 {rec['min_no']}~{rec['max_no']} 页）"
            if rec["min_no"] != rec["max_no"]
            else f"{rec['pages']} 页"
        )
        logger.warning(
            "转存失败 | %s",
            _fail_body(row, rec["adapter"], rec["reason"], span),
            extra={"log_fields": {
                "event": "transfer.fail",
                "source": row.get("source"),
                "comic_id": row.get("comic_id"),
                "comic_title": row.get("comic_title"),
                "chapter_id": row.get("chapter_id"),
                "chapter_title": row.get("chapter_title"),
                "endpoint": _endpoint_of(rec["adapter"], row),
                "pages": rec["pages"],
                "reason": rec["reason"],
            }},
        )

    logger.info(
        "懒转存完成: %s（失败章节 %d 个）",
        stats,
        len(fails),
        extra={"log_fields": {
            "event": "transfer.done",
            "source": source or "",
            "pages": stats["transferred"],
        }},
    )
    return stats
