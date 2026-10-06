"""命令行入口（**运维 / 排障用**，不是常规采集路径）。

用法：
    python -m comic_crawler.cli list          # 列出已注册的源站适配器
    python -m comic_crawler.cli show          # 展示库内数据
    python -m comic_crawler.cli inspect       # 失效巡检（转存未转存页 + 全表校验 + 恢复丢失）
    python -m comic_crawler.cli transfer-images  # 懒转存未转存页

⚠️ **`run` / `serve` 已删除**（2026-10-06）。常规采集只有两条路，别在这里再开第三个入口：

| 场景 | 走哪条 |
|---|---|
| 手动、看结果、要进度 | 管理台「触发采集」（api 进程内后台线程，`taskId` 轮询） |
| 定时、无人值守 | `comic-scheduler`（独立进程，读管理台配的 5 段 cron） |

一次性受控采集（比如新源冒烟）也不再单开命令：在管理台「触发采集」把**数量上限填 1** 即可
（等价于过去的 `--limit 1`）；真要无人值守跑一次，就给 `comic-scheduler` 配一条只命中一次的 cron。

存储：固定使用 MySQL（实现见 `comic_core.storage.mysql`），连接参数经 `COMIC_MYSQL_*` 环境变量配置。
"""

from __future__ import annotations

import argparse
import logging

from comic_core.images.store import LocalImageStore
from comic_core.storage.base import Storage
from comic_core.storage.mysql import MySQLStorage

from .sources import create_adapter, list_adapters
from .images.transfer import lazy_transfer
from .scheduling import inspect_sync

logger = logging.getLogger(__name__)


def _storage(_args: argparse.Namespace) -> Storage:
    """返回 MySQL 存储实现（本项目唯一存储方案）。"""
    return MySQLStorage()


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_list(_: argparse.Namespace) -> int:
    print("已注册的源站适配器:")
    for name in list_adapters():
        print(f"  - {name}")
    return 0


def cmd_show(_args: argparse.Namespace) -> int:
    storage = MySQLStorage()
    print(f"\n库内作品（MySQL: {storage.dsn['host']}:{storage.dsn['port']}/{storage.dsn['database']}）:")
    items, _ = storage.list_comics(page=1, page_size=1000)
    for row in items:
        print(
            f"  #{row['id']} [{row['source']}] {row['title']} - {row['author']} "
            f"({row['status']}/{row['category']}) 更新至:{row['latest_chapter_title']}"
        )
    return 0


def cmd_transfer_images(args: argparse.Namespace) -> int:
    """懒转存：把库内『未转存』页转存到图片存储。

    带适配器工厂：URL 签名过期（zaimanhua 等短时效源）时现场重拉新 URL 再下载。
    --since/--until：只转存该区间入库的页（配合增量采集联测：增量跑完后用
    同一 since 起止时间调本命令，只转本次增量新收的页）。
    """
    storage = _storage(args)
    store = LocalImageStore(root=args.store)
    stats = lazy_transfer(
        storage,
        store,
        limit=args.limit,
        adapter_provider=create_adapter,
        since=args.since,
        until=args.until,
    )
    print("==> 懒转存:", stats)
    print("==> 页面状态分布:", storage.count_pages_by_status())
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """失效巡检：转存未转存页 + **全表**校验已转存对象 + 恢复丢失。

    默认全库巡检；`--source` 只巡检指定源（同时限定转存范围），`--since/--until`
    限定「转存」部分的时间窗（校验始终是全表/全源，保证不留死角）。
    """
    storage = _storage(args)
    store = LocalImageStore(root=args.store)
    stats = inspect_sync(
        storage,
        image_store=store,
        source=args.source,
        since=args.since,
        until=args.until,
        adapter_provider=create_adapter,
    )
    print("==> 失效巡检:", stats)
    print("==> 页面状态分布:", storage.count_pages_by_status())
    return 0


def main() -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="comic_crawler", description="漫画聚合平台采集服务（运维/排障命令）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出已注册适配器").set_defaults(fn=cmd_list)
    sub.add_parser("show", help="展示库内数据").set_defaults(fn=cmd_show)

    p_transfer = sub.add_parser("transfer-images", help="懒转存未转存页面")
    p_transfer.add_argument(
        "--store", default=None, help="图片存储目录（本地模拟 OSS）；默认用统一图库根"
    )
    p_transfer.add_argument(
        "--limit", type=int, default=None,
        help="本次最多转存页数（可选兜底）；默认不限制，转存窗口内全部未转存页",
    )
    p_transfer.add_argument(
        "--since", default=None, help="只转存该时间（ISO，如 2026-09-07T16:25:00）之后入库的页"
    )
    p_transfer.add_argument(
        "--until", default=None, help="只转存该时间（ISO）之前入库的页（默认不限）"
    )
    p_transfer.set_defaults(fn=cmd_transfer_images)

    p_inspect = sub.add_parser("inspect", help="失效巡检（转存 + 全表校验 + 恢复）")
    p_inspect.add_argument("--store", default=None, help="图片存储目录；默认用统一图库根")
    p_inspect.add_argument("--source", default=None, help="只巡检指定源（默认全库）")
    p_inspect.add_argument("--since", default=None, help="只转存该时间（ISO）之后入库的页")
    p_inspect.add_argument("--until", default=None, help="只转存该时间（ISO）之前入库的页（默认不限）")
    p_inspect.set_defaults(fn=cmd_inspect)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
