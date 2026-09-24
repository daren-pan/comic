"""MySQL 连接池 —— **存储层取连接的唯一入口**。

## 为什么要有它（2026-09-21）

此前三个 store（`MySQLStorage` / `MySQLUserStore` / `MySQLLogStore`）各自
`pymysql.connect()`，**每次方法调用都建一条新连接**（TCP + 认证握手，项目自己的注释
估过"约 20ms 量级"）。而一次 HTTP 请求常常要 3~5 次存储调用：

- 详情页 = `increment_comic_views` + `get_comic` + `get_chapters` + `get_comic_tags`；
- 阅读页每张图 = `get_page_context`（命中未转存时还要 +2）；
- 巡检的键集分页循环 = 每批一次。

这些握手时间纯浪费，且连接数随并发**线性上涨**，`max_connections`（`deploy/mysql/my.cnf`
= 200）就是硬顶 —— 打满后是「Too many connections」，整站报错而不是变慢。

## 为什么自己写而不是引入 DBUtils / SQLAlchemy

依赖清单刻意保持精简（crawler 侧只有 `httpx` / `pymysql`），加一个包要同步 wheel、
requirements 与镜像；而这里需要的只是「LIFO 复用 + 上限 + 探活 + 出错不复用」，够简单。

## 行为约定

- **复用优先**：空闲连接 LIFO 取用（最近用过的更可能还活着）；
- **取用即探活**：`ping(reconnect=False)` 一条轻量往返（本地 <1ms，远低于重连的 20ms）。
  **刻意不 reconnect**：坏连接直接丢弃重建，不把"半死连接"上的会话状态带进下一个请求；
- **满额即排队**：已达上限则阻塞等待归还，等不到抛 `PoolTimeout`（宁可报错，不无限挂住请求线程）；
- **出错不还池**：上下文里抛异常（含 `BaseException`：超时取消也算）时连接直接关闭，
  未知状态绝不留给下一个请求；
- `autocommit` 等会话参数由 **DSN** 决定（本项目恒为 True），池本身不碰事务。
"""

from __future__ import annotations

import atexit
import logging
import queue
import threading
import time
from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.connections import Connection

logger = logging.getLogger(__name__)

#: 单进程连接数上限。依据：`max_connections = 200`，而同一实例上可能同时有
#: `comic-app` 与 `comic-scheduler` 两个进程，各 20 仍留足余量；超过的部分在池上排队
#: （表现为等连接），而不是把 MySQL 打满后集体报 1040。
POOL_SIZE = 20

#: 等连接的最长时间。超时说明库或某个慢查询卡住了 —— 此时快速失败比无限期占住
#: 请求线程更健康（uvicorn 的同步端点线程池是有限的）。
ACQUIRE_TIMEOUT = 10.0


class PoolTimeout(RuntimeError):
    """池已满且等待超时（数据库可能卡住或压力过高）。"""


class ConnectionPool:
    """按 DSN 维度的连接池（线程安全）。"""

    def __init__(self, dsn: dict, size: int = POOL_SIZE, timeout: float = ACQUIRE_TIMEOUT) -> None:
        self._dsn = dict(dsn)
        self._size = max(1, int(size))
        self._timeout = float(timeout)
        self._idle: queue.LifoQueue = queue.LifoQueue(maxsize=self._size)
        self._lock = threading.Lock()
        self._total = 0        # 已建立且未关闭的连接数（空闲 + 借出）
        self._closed = False

    # ---------------- 内部 ----------------
    def _reserve(self) -> bool:
        """占一个额度（未超上限才成功）。"""
        with self._lock:
            if self._closed or self._total >= self._size:
                return False
            self._total += 1
            return True

    def _forget(self, conn: Connection) -> None:
        """关闭连接并归还额度。"""
        with self._lock:
            self._total -= 1
        try:
            conn.close()
        except Exception:  # 关连接失败不影响调用方
            logger.debug("关闭 MySQL 连接失败", exc_info=True)

    @staticmethod
    def _alive(conn: Connection) -> bool:
        """轻量探活：不重连，坏了就返回 False 交给调用方丢弃。"""
        try:
            conn.ping(reconnect=False)
            return True
        except Exception:
            return False

    def _acquire(self) -> Connection:
        deadline = time.monotonic() + self._timeout
        while True:
            # 1) 优先复用空闲连接
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                conn = None
            if conn is not None:
                if self._alive(conn):
                    return conn
                self._forget(conn)          # 空闲期间被服务端断开 → 丢弃重建
                continue

            # 2) 没有空闲且未到上限 → 新建
            if self._reserve():
                try:
                    return pymysql.connect(**self._dsn)
                except Exception:
                    with self._lock:
                        self._total -= 1     # 建连失败要还回额度，否则池会越用越"假满"
                    raise

            # 3) 已到上限 → 等别人归还
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PoolTimeout(
                    f"等待 MySQL 连接超过 {self._timeout:g}s（池上限 {self._size}）"
                )
            try:
                conn = self._idle.get(timeout=remaining)
            except queue.Empty:
                raise PoolTimeout(
                    f"等待 MySQL 连接超过 {self._timeout:g}s（池上限 {self._size}）"
                )
            if self._alive(conn):
                return conn
            self._forget(conn)

    def _release(self, conn: Connection) -> None:
        if self._closed:
            self._forget(conn)
            return
        try:
            self._idle.put_nowait(conn)
        except queue.Full:                  # 理论上到不了（total <= size），保守关掉
            self._forget(conn)

    # ---------------- 对外 ----------------
    @contextmanager
    def acquire(self) -> Iterator[Connection]:
        """借一条连接；正常结束归还池，出异常则关闭丢弃。"""
        conn = self._acquire()
        try:
            yield conn
        except BaseException:
            self._forget(conn)
            raise
        else:
            self._release(conn)

    def close(self) -> None:
        """关闭全部空闲连接（测试/进程收尾用）。借出的连接会在归还时被关掉。"""
        with self._lock:
            self._closed = True
        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                break
            self._forget(conn)

    def stats(self) -> dict[str, int]:
        """池状态（排查用）：`size` 上限 / `total` 已建 / `idle` 空闲。"""
        return {"size": self._size, "total": self._total, "idle": self._idle.qsize()}


# ---------------- 进程内共享的池（按 DSN 去重） ----------------
_pools: dict[tuple, ConnectionPool] = {}
_pools_lock = threading.Lock()


def _dsn_key(dsn: dict) -> tuple:
    """DSN → 可哈希的键（三个 store 用同一份 `_DSN` 时因此**共用同一个池**）。"""
    return tuple(sorted((str(k), v) for k, v in dsn.items()))


def pool_for(dsn: dict) -> ConnectionPool:
    """取（或按需创建）该 DSN 的池。"""
    key = _dsn_key(dsn)
    with _pools_lock:
        pool = _pools.get(key)
        if pool is None:
            pool = ConnectionPool(dsn)
            _pools[key] = pool
        return pool


@contextmanager
def pooled_conn(dsn: dict) -> Iterator[Connection]:
    """取连接的上下文管理器 —— 与旧的 `pymysql.connect()` + `close()` 用法等价。

        with pooled_conn(self.dsn) as conn:
            with conn.cursor() as cur:
                ...
    """
    with pool_for(dsn).acquire() as conn:
        yield conn


@atexit.register
def close_all_pools() -> None:
    """进程正常退出时关掉空闲连接。

    不关也能跑（OS 会回收），但 MySQL 侧会把它们记成 `Aborted connection` 并累加
    `Aborted_clients` —— 正常退出就该是干净的（与 `log_handler` 的 atexit 刷盘同一考虑）。
    """
    with _pools_lock:
        pools = list(_pools.values())
    for pool in pools:
        try:
            pool.close()
        except Exception:  # 收尾失败无所谓，别在退出路径上抛
            pass
