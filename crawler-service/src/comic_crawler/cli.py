"""命令行入口。

用法：
    python -m comic_crawler.cli run --source demo_source [--mode incremental|full]
    python -m comic_crawler.cli transfer-images [--store image_store]
    python -m comic_crawler.cli inspect [--store image_store]
    python -m comic_crawler.cli list          # 列出已注册的源站适配器
    python -m comic_crawler.cli show          # 展示库内数据

存储：固定使用 MySQL（见 mysql_storage.py），连接参数经 COMIC_MYSQL_* 环境变量配置。
"""

from __future__ import annotations

import argparse
import logging
import time

from .adapter import create_adapter, list_adapters
from .image_service import lazy_transfer
from .image_store import LocalImageStore
from .mysql_storage import MySQLStorage
from .scheduler import SyncScheduler, full_sync, incremental_sync, inspect_sync
from .storage import Storage


def _storage(_args: argparse.Namespace) -> Storage:
    """返回 MySQL 存储实现（本项目唯一存储方案）。"""
    return MySQLStorage()


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_run(args: argparse.Namespace) -> int:
    # HttpFetcher 同时支持 http(s) 与本地路径（fixture 离线联调），demo 源无需特判
    adapter = create_adapter(args.source)
    storage = _storage(args)

    if args.mode == "full":
        stats = full_sync(adapter, storage)
    else:
        stats = incremental_sync(adapter, storage)
    print("\n==> " + stats.summary())
    print("==> 库内数据:", storage.stats())
    return 0


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
    """失效巡检：转存未转存页 + 校验已转存对象 + 恢复丢失。"""
    storage = _storage(args)
    store = LocalImageStore(root=args.store)
    stats = inspect_sync(storage, image_store=store)
    print("==> 失效巡检:", stats)
    print("==> 页面状态分布:", storage.count_pages_by_status())
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """调度守护：按配置轮询执行 增量同步 / 每日全量 / 失效巡检。"""
    from .config import SOURCES

    storage = _storage(args)
    sources = [s for s in SOURCES if s.enabled]
    if args.source:
        sources = [s for s in sources if s.name == args.source]
        if not sources:
            print(f"未找到已启用的源站: {args.source}")
            return 1

    adapters = {s.name: create_adapter(s.name) for s in sources}
    sched = SyncScheduler(adapters, storage, sources)
    print(
        f"==> 调度服务启动: {[s.name for s in sources]} | "
        f"检查间隔 {args.interval}s | 巡检间隔 3600s | Ctrl+C 退出",
        flush=True,
    )
    while True:
        try:
            for task in sched.tick():
                print(f"==> 已执行: {task}", flush=True)
        except KeyboardInterrupt:
            print("\n==> 调度服务已停止", flush=True)
            return 0
        except Exception:
            logger.exception("调度循环异常")
        time.sleep(args.interval)


def main() -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="comic_crawler", description="漫画聚合平台采集服务")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="执行一次同步")
    p_run.add_argument("--source", default="demo_source", help="源站名（见 list）")
    p_run.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    p_run.set_defaults(fn=cmd_run)

    sub.add_parser("list", help="列出已注册适配器").set_defaults(fn=cmd_list)

    p_transfer = sub.add_parser("transfer-images", help="懒转存未转存页面")
    p_transfer.add_argument("--store", default="image_store", help="图片存储目录（本地模拟 OSS）")
    p_transfer.add_argument(
        "--limit", type=int, default=200, help="每批最多转存页数（默认 200）"
    )
    p_transfer.add_argument(
        "--since", default=None, help="只转存该时间（ISO，如 2026-09-07T16:25:00）之后入库的页"
    )
    p_transfer.add_argument(
        "--until", default=None, help="只转存该时间（ISO）之前入库的页（默认不限）"
    )
    p_transfer.set_defaults(fn=cmd_transfer_images)

    p_inspect = sub.add_parser("inspect", help="失效巡检（转存 + 校验 + 恢复）")
    p_inspect.add_argument("--store", default="image_store")
    p_inspect.set_defaults(fn=cmd_inspect)

    p_show = sub.add_parser("show", help="展示库内数据")
    p_show.set_defaults(fn=cmd_show)

    p_serve = sub.add_parser("serve", help="定时调度守护（增量/全量/巡检）")
    p_serve.add_argument("--source", default="", help="仅调度指定源站（默认全部已启用源）")
    p_serve.add_argument("--interval", type=int, default=30, help="轮询检查间隔秒数（默认 30）")
    p_serve.set_defaults(fn=cmd_serve)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
