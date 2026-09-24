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

from comic_core.images.store import ImageStore
from comic_core.storage.base import Storage

logger = logging.getLogger(__name__)

# 共享 httpx.Client：keep-alive 复用连接，避免每张图都重建 TCP/TLS 握手
# （曾实测：新建连接下载 ~6s/张，复用连接 ~2s/张；无并发，天然贴合源站低频约定）
_client: httpx.Client | None = None

# 懒转存并发路数（默认 2）：境外图床（如 MangaDex）单张耗时长，适度并发解耦网络 IO，
# 同时对源站保持低频合规（MangaDex AUP 约 5 req/s，2 路远低于该值）。
CONCURRENCY = 2

# ---------------------------------------------------------------------------
# 读时穿透的闸门 / 去重 / 负缓存（2026-09-21 补）
#
# 背景：批量转存（`lazy_transfer`）一直有 `CONCURRENCY` 这道闸门，而**读时穿透没有** ——
# 阅读器一话就是浏览器并发 N 张图，冷章节 = N 个出站请求同时打源站（一话 40 页就是 40 路），
# 正是本项目反复强调要避免的源站风控场景；而且触发者可以只是**一个匿名用户**
# （`GET /api/images/...` 公开、无鉴权、无限流）。三件事分别解决三个问题：
#
#   ① 闸门   —— 限制**同时**出站的数量（只约束下载；落盘 / 回填不占额度）；
#   ② 去重   —— 同一页被并发请求（多标签页 / 快速重试）时只下载一次，其余等结果；
#   ③ 负缓存 —— 失败后短时间内不再打源站。没有它时，失败页的 `cached_status` 仍是
#               「未转存」，于是"用户每刷新一次就打一次源站"，可以无限重试。
# ---------------------------------------------------------------------------

#: 穿透取图的并发上限（出站下载路数）。
PASSTHROUGH_CONCURRENCY = 4
#: 等闸门 / 等同图下载的最长时间；等不到就返回 None（调用方给占位图），不无限占住请求线程。
PASSTHROUGH_WAIT_SECONDS = 15.0
#: 失败负缓存时长：同一页在此期间不再打源站。
PASSTHROUGH_FAIL_TTL = 60.0
#: 负缓存条目上限（防止字典无限增长；满了整体清空 —— 比 LRU 简单，效果足够）。
PASSTHROUGH_FAIL_MAX = 2000

_passthrough_gate = threading.Semaphore(PASSTHROUGH_CONCURRENCY)
_inflight_lock = threading.Lock()
#: page key -> 该页正在下载的信号（下载结束 set()，等待者据此醒来读落盘结果）
_inflight: dict[str, threading.Event] = {}
#: page key -> 负缓存到期时刻（time.monotonic 基准）
_fail_until: dict[str, float] = {}


def _fail_cached(key: str) -> bool:
    """该页是否处于失败负缓存期内（顺带回收过期项）。"""
    with _inflight_lock:
        until = _fail_until.get(key)
        if until is None:
            return False
        if until > time.monotonic():
            return True
        del _fail_until[key]
        return False


def _remember_fail(key: str) -> None:
    """记一次失败（进入负缓存期）。"""
    with _inflight_lock:
        if len(_fail_until) >= PASSTHROUGH_FAIL_MAX:
            _fail_until.clear()
        _fail_until[key] = time.monotonic() + PASSTHROUGH_FAIL_TTL


def _inflight_enter(key: str) -> tuple[bool, threading.Event | None]:
    """登记"我要下载这一页"。

    返回 `(True, None)` = 我是领先者，下载完必须调 `_inflight_leave(key)`；
    返回 `(False, event)` = **已有请求在下载同一页**，调用方应等这个 event 再读落盘结果。
    """
    with _inflight_lock:
        ev = _inflight.get(key)
        if ev is not None:
            return False, ev
        _inflight[key] = threading.Event()
        return True, None


def _inflight_leave(key: str) -> None:
    """领先者结束（无论成败）：摘掉登记并唤醒所有等待者。"""
    with _inflight_lock:
        ev = _inflight.pop(key, None)
    if ev is not None:
        ev.set()


def _read_stored(image_store: ImageStore, key: str) -> bytes | None:
    """从图库读刚落的盘（同图去重的等待者用；读失败按"没有"处理）。"""
    try:
        return image_store.get(key)
    except Exception:
        return None


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


def comic_label(comic_id: object, title: object = "") -> str:
    """日志里的作品标识：`36「惡女只想安靜地生活！」`；没有名字时退化成 `36`。

    为什么要带上名字：只写 `comic_id=36` 的话，看日志的人还得回库里查一次才知道是哪部作品
    （用户 2026-09-18 提：「消息中要显示具体漫画 id 和名称」）。与 `_fail_body` 同属"日志正文
    拼装"，故放在本模块；`scheduling/heal.py` 的封面回源失败也复用它。
    """
    name = str(title or "").strip()
    return f"{comic_id}「{name}」" if name else str(comic_id)


def _short_reason(exc: Exception) -> str:
    """把下载异常压成一行可读原因（封面失败日志用）。

    ⚠️ **不要直接用 `str(exc)`**：httpx 的异常文案自带完整 URL 加一句
    "For more information check: https://developer.mozilla.org/..."，落进日志页就是
    两百多字符的噪音，真正有用的「谁失败了 / 为什么」反被冲掉
    （用户 2026-09-18 举的就是这种：`封面落盘失败 comic_id=36 https://…: Client error '404 …'`）。
    """
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    if status is not None:
        phrase = str(getattr(resp, "reason_phrase", "") or "")
        return f"HTTP {status}{f' {phrase}' if phrase else ''}"
    if isinstance(exc, httpx.TimeoutException):
        return "请求超时"
    if isinstance(exc, httpx.TransportError):
        return f"网络错误（{type(exc).__name__}）"
    return f"{type(exc).__name__}: {str(exc)[:80]}"


def _cover_log_fields(
    *, event: str, source: object, comic_id: int, comic_title: object, url: str, reason: str
) -> dict:
    """封面落盘的 `extra={"log_fields": …}`（落进 `log_record` 的**结构化**列）。

    结构化之后，管理台「日志查询」页的作品 / 源站 / 事件 / 原因四列都能直接显示与筛选，
    不必再去 message 里捞关键字。

    ⚠️ **下载地址刻意塞进 `endpoint`**（原本只给"源站章节接口"用）：它是"这次失败请求的远端
    端点"，且该列在详情面板里按等宽字体 + 断行渲染，正好适合放 URL；这样 message 才能保持
    干净（只留 id / 名称 / 原因），又不丢排查线索。
    """
    return {
        "log_fields": {
            "event": event,
            "source": source,
            "comic_id": comic_id,
            "comic_title": comic_title,
            "endpoint": url,
            "reason": reason,
        }
    }


def ensure_cover_local(
    storage: Storage,
    image_store: ImageStore,
    comic_id: int,
    cover_url: str,
    *,
    comic_title: object = "",
    source: object = "",
    force: bool = False,
) -> bool:
    """外链封面落盘为图库内相对 key（covers/{comic_id}.jpg）。

    - **图库里已有这张封面 → 直接返回（True），不重复下载**；
    - 已是本地 key / 占位路径 / 空 → 跳过（True）；
    - http(s) 外链且本地还没有 → 下载写图库并回填相对 key；
    - 下载失败 → 保留外链，记录告警返回 False，下次同步重试。
    与 lazy_transfer 同一约定：DB 只存图库内相对 key，与机器/项目路径解耦。

    ⚠️ **为什么必须先看本地**：采集每轮都会调这里，而传进来的 `cover_url` 是**源站外链**
    （`detail.cover_url`，每轮都一样），只判"是不是 http(s)"的话就会**每轮把封面重下一遍**
    （实测同一部在日志里出现多次「封面落盘」）。封面 key 由 comic_id 唯一确定，
    所以"文件在"就等于"已落盘"，没必要再回源。

    代价（用户 2026-09-18 明确接受）：**源站换封面时不会自动刷新** —— 想强制刷新就删掉
    图库里那张 `covers/{id}.jpg`，下一次管理台「触发转存」跑完的封面自愈
    （`scheduling.heal.heal_covers`）会回源重取。⚠️ 注意：**定时巡检（`inspect_sync`）不碰封面**，
    所以删了文件后不会自动被修，必须有转存 / 重新导入这类动作把它带一遍。

    `force=True`（2026-09-20 新增，供「按作品强制自愈」用）：**跳过"文件在即健康"的早返回**，
    只要 `cover_url` 是 http(s) 就重新下载并**覆盖**图库文件 —— 用于修复"文件在但内容是错的"
    封面（判据只看文件在不在，不看内容，故普通自愈永远修不到错图）。仍非 http(s) 时照旧跳过。

    `comic_title` / `source` 是**可选**的补充信息，只用于日志（调用方手上有就传，
    传了日志里才会显示作品名、管理台才筛得到）；不传不影响任何落盘行为。
    """
    key = f"covers/{comic_id}.jpg"
    if image_store.exists(key) and not force:
        # 文件在：本地已落盘。若库里还记着外链（此前下载成功但回填失败等），顺手补回填 ——
        # 否则接口会一直按外链取图，白存了这份本地文件。
        if cover_url.startswith(("http://", "https://")):
            storage.set_comic_cover(comic_id, key)
        return True
    if not cover_url or not cover_url.startswith(("http://", "https://")):
        return True
    try:
        resp = httpx.get(cover_url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
        data = resp.content
        if not data:
            return False
        image_store.put(key, data)
        storage.set_comic_cover(comic_id, key)
        logger.info(
            "封面落盘 comic_id=%s -> %s (%dB)", comic_label(comic_id, comic_title), key, len(data),
            extra=_cover_log_fields(
                event="cover.ok", source=source, comic_id=comic_id,
                comic_title=comic_title, url=cover_url, reason="",
            ),
        )
        return True
    except Exception as exc:
        reason = _short_reason(exc)
        logger.warning(
            "封面落盘失败 comic_id=%s｜%s", comic_label(comic_id, comic_title), reason,
            extra=_cover_log_fields(
                event="cover.fail", source=source, comic_id=comic_id,
                comic_title=comic_title, url=cover_url, reason=reason,
            ),
        )
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


def _fetch_as_leader(
    storage: Storage,
    image_store: ImageStore,
    row: dict,
    key: str,
    adapter_provider: Callable[[str], object] | None,
    downloader: Callable[[str, str], bytes],
) -> bytes | None:
    """领先者路径：抢出站闸门 → 下载（必要时重拉）→ 落盘 + 回填 → 返回字节。"""
    adapter = _build_adapter(adapter_provider, str(row.get("source") or ""))

    # ③ 出站闸门：**只**约束这次下载（落盘与 DB 回填不占额度）
    if not _passthrough_gate.acquire(timeout=PASSTHROUGH_WAIT_SECONDS):
        # 闸门拥挤 ≠ 这一页坏了，故**刻意不写负缓存** —— 写进去会把好页也黑掉一分钟
        logger.warning(
            "穿透取图排队超时（并发上限 %d，已等 %.0fs）page_id=%s",
            PASSTHROUGH_CONCURRENCY, PASSTHROUGH_WAIT_SECONDS, row.get("page_id"),
            extra={"log_fields": {
                "event": "read.fail", "source": row.get("source"),
                "comic_id": row.get("comic_id"), "comic_title": row.get("comic_title"),
                "chapter_id": row.get("chapter_id"), "chapter_title": row.get("chapter_title"),
                "pages": 1, "reason": "取图并发已满，排队超时",
            }},
        )
        return None
    try:
        data, reason = _download_one(row.get("source_url"), key, adapter, row, downloader)
    finally:
        _passthrough_gate.release()

    if data is None:
        _remember_fail(key)   # ① 进负缓存：短时间内不再为这一页打源站
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
    - 失败：返回 None（调用方回退 SVG 占位图），状态保持「未转存」；
    - **同一页并发只下一次**，失败后 `PASSTHROUGH_FAIL_TTL` 秒内不再打源站
      （闸门 / 去重 / 负缓存三个常量的来龙去脉见本模块上方的常量块）。

    下载策略与 `lazy_transfer` 完全一致（复用同一套函数）：登记 URL 未过期就直接用；
    已过期或下载失败 → 现场重拉整章 URL 让源站重新签发 → 再试一次。
    """
    downloader = downloader or default_downloader
    key = build_image_key(row["comic_id"], row["chapter_id"], row["page_no"])

    # ① 负缓存：这一页刚失败过 → 直接跳过，不打源站
    #    日志用 debug：短时间内重复访问同一坏页会刷屏，而失败本身已 warning 过一次
    if _fail_cached(key):
        logger.debug(
            "穿透取图跳过（%.0fs 内已失败过）page_id=%s", PASSTHROUGH_FAIL_TTL, row.get("page_id")
        )
        return None

    # ② 同图去重：已有请求在下载这一页 → 等它，再直接读落盘结果（不再打第二次源站）
    leader, pending = _inflight_enter(key)
    if not leader:
        if pending is not None:
            pending.wait(PASSTHROUGH_WAIT_SECONDS)
        return _read_stored(image_store, key)

    try:
        return _fetch_as_leader(storage, image_store, row, key, adapter_provider, downloader)
    finally:
        _inflight_leave(key)   # 无论成败都要唤醒等待者，否则它们会一直等到超时


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
        since/until: 只转存「**章节入库时间**」落在该窗口内的未转存页（按 `chapter.sync_time`
            过滤，不是页的登记时间 —— `page` 表无时间列）；None 表示不限制。
            ⚠️ 页清单是**读时**才登记的（2026-09-21 决策）：窗口内某章若还没被人打开过，
            就压根没有 page 行可转 —— 要兜全库请把起止**留空**。
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
