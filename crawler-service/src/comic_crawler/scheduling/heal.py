"""失效巡检与封面自愈（架构方案 §2.2「第三类任务」）。

- `inspect_sync` —— 每小时巡检：未转存页触发懒转存（带 adapter_provider 时对签名过期
  URL 现场重拉）；已转存页校验对象是否存在，缺失则标记失效并尝试恢复。
- `heal_covers` —— 封面自愈：外链未落盘 / 本地文件缺失的封面按状态修复。
  **由转存任务在结束后自动调用**（管理台「触发转存」→ 无需单独按钮）。
"""
from __future__ import annotations

import logging

from ..sources.base import CrawlerAdapter
from ..storage.base import Storage

logger = logging.getLogger(__name__)

# 巡检校验（第 2 步）的键集分页批大小：内存里一次处理这么多页，
# 用返回行的最大 page_id 推进游标，直到扫完全表为止（不再被固定条数截断）。
SCAN_BATCH = 1000

def inspect_sync(
    storage: Storage,
    image_store=None,
    adapter_provider=None,
    source: str | None = None,
    since=None,
    until=None,
) -> dict[str, int]:
    """失效巡检（架构方案 §2.2 第三类任务，每小时）：

    1. 未转存页 → 触发懒转存（带 adapter_provider 时可对签名过期 URL 现场重拉）；
    2. 已转存页 → 校验 OSS 对象是否存在，缺失则标记失效并尝试恢复；
    3. 恢复失败的失效页保持 '失效'，由下次巡检或人工处理。

    ⚠️ **第 2 步是「全表遍历」，不再截断**：按 `id` 键集分页（每次 `SCAN_BATCH` 条）
    逐批推进游标直到扫完。旧实现 `list_pages()` 只取 500 条且 SQL 是 `ORDER BY id`，
    导致**每轮都只校验 id 最小的同一批页**，其余已转存页从未被校验/恢复。

    source/since/until：只作用于**第 1 步**（未转存页转存），语义与管理台「转存」一致
    （窗口内全部，无 limit）；`source` 同时限定第 2 步的校验范围；None = 不限制。

    返回统计：{checked, transferred, verified, recovered, invalid}
    """
    if image_store is None:
        from ..images.store import LocalImageStore

        image_store = LocalImageStore()

    from ..images.transfer import build_image_key, default_downloader, lazy_transfer

    stats = {"checked": 0, "transferred": 0, "verified": 0, "recovered": 0, "invalid": 0}

    # 1) 未转存 → 转存（URL 过期时经 adapter_provider 现场重拉再下载）
    transfer_stats = lazy_transfer(
        storage,
        image_store,
        adapter_provider=adapter_provider,
        since=since,
        until=until,
        source=source,
    )
    stats["transferred"] = transfer_stats["transferred"]

    # 2) 已转存 → 校验对象是否存在（键集分页遍历全表）
    after_id = 0
    while True:
        rows = storage.list_pages(after_id=after_id, limit=SCAN_BATCH, source=source)
        if not rows:
            break
        for row in rows:
            stats["checked"] += 1
            # 推进游标（对**所有**行推进，包括下面 continue 跳过的，避免死循环）
            after_id = max(after_id, int(row["page_id"]))
            oss_url = row["oss_url"]
            if not oss_url or row["cached_status"] != "已转存":
                continue
            key = oss_url  # file:// 或 http(s) URL；本地模拟直接比对路径
            if image_store.exists(key):
                stats["verified"] += 1
                continue
            # 对象丢失：先标记失效，再尝试用源 URL 恢复（演示中重转即恢复）
            storage.mark_page_invalid(row["page_id"])
            stats["invalid"] += 1

            key = build_image_key(row["comic_id"], row["chapter_id"], row["page_no"])
            try:
                data = image_store.get(key)
            except Exception:
                data = None
            if data is None:
                data = default_downloader(row["source_url"], key)
            image_store.put(key, data)
            # 回填图库内相对 key（与 lazy_transfer 一致），保持 oss_url 全库统一形态
            storage.mark_page_cached(row["page_id"], key)
            stats["recovered"] += 1
        # 本批不足一整批 → 已到表尾
        if len(rows) < SCAN_BATCH:
            break

    logger.info("失效巡检完成: %s", stats)
    return stats


def heal_covers(storage: Storage, image_store=None, adapter_provider=None) -> dict[str, int]:
    """封面自愈（管理台触发「懒转存」后自动执行）：修复图库中缺失/未落盘的封面。

    逐部漫画判断（封面统一存「图库内相对 key」，见 image_service.ensure_cover_local）：
    - 封面仍是外链（http/https，此前下载失败留下的）→ 直接重试下载落盘；
    - 封面是本地 key（covers/xx.jpg）且图库文件存在 → 健康，跳过；
    - 封面为空 / 本地 key 但文件缺失 → 经 adapter_provider 按 source_comic_id
      回源站重抓一次详情，取其最新 cover_url 再落盘（best-effort，取不到则跳过）；
    - 其余非空非外链（如演示占位路径）→ 按源站自身约定，跳过（不发起无谓回源）。

    返回统计：{checked, healed, failed, skipped}
    """
    if image_store is None:
        from ..images.store import LocalImageStore

        image_store = LocalImageStore()

    from ..images.transfer import ensure_cover_local

    stats = {"checked": 0, "healed": 0, "failed": 0, "skipped": 0}
    rows, _ = storage.list_comics(page=1, page_size=10000)
    need_refetch: dict[str, list[dict]] = {}  # source -> 需回源取封面的漫画行

    for row in rows:
        stats["checked"] += 1
        cover = str(row.get("cover_url") or "").strip()

        # 仍是外链（此前下载失败）：直接重试下载落盘
        if cover.startswith(("http://", "https://")):
            if ensure_cover_local(storage, image_store, int(row["id"]), cover):
                stats["healed"] += 1
            else:
                stats["failed"] += 1
            continue

        # 本地 key：文件在 → 健康；文件缺失 → 需回源
        if cover.startswith("covers/"):
            if image_store.exists(cover):
                stats["skipped"] += 1
                continue
        # 空封面 → 需回源；非空非外链非本地（占位路径）→ 跳过
        elif cover != "":
            stats["skipped"] += 1
            continue

        if adapter_provider is None:
            stats["skipped"] += 1
            continue
        need_refetch.setdefault(str(row.get("source") or ""), []).append(row)

    # 回源取封面：按源分组，每源只做一次 pre_fetch / post_fetch
    for src, srows in need_refetch.items():
        adapter = adapter_provider(src)
        if adapter is None:
            stats["skipped"] += len(srows)
            continue
        try:
            adapter.pre_fetch()
        except Exception:
            logger.exception("封面自愈 pre_fetch 失败 source=%s", src)
        try:
            for row in srows:
                url = _refetch_cover_url(adapter, row)
                if not url.startswith(("http://", "https://")):
                    stats["skipped"] += 1
                    continue
                if ensure_cover_local(storage, image_store, int(row["id"]), url):
                    stats["healed"] += 1
                else:
                    stats["failed"] += 1
        finally:
            try:
                adapter.post_fetch()
            except Exception:
                logger.exception("封面自愈 post_fetch 失败 source=%s", src)

    logger.info("封面自愈完成: %s", stats)
    return stats


def _refetch_cover_url(adapter: CrawlerAdapter, row: dict) -> str:
    """回源站重抓详情，取其封面外链（本地封面文件丢失、DB 只存相对 key 时用）。"""
    from ..models import ComicBrief

    brief = ComicBrief(
        source=str(row.get("source") or ""),
        source_comic_id=str(row.get("source_comic_id") or ""),
        title=str(row.get("title") or ""),
    )
    try:
        detail = adapter.fetch_comic_detail(brief)
        return detail.cover_url or ""
    except Exception:
        logger.warning("封面回源失败 comic_id=%s source=%s", row.get("id"), row.get("source"), exc_info=True)
        return ""

